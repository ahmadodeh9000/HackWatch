"""Find Jordan tech events we don't list yet and queue them for a human, in ONE GitHub issue.

Nothing is published from here. Each find is a checkbox in the "Candidate events" issue;
ticking it opens a pull request through `hackwatch add --from-url` (scripts/candidate_to_pr.py).
Text from other sites only reaches the issue after sanitize(), so it can't mention people or
inject markup. Keys of everything ever listed stay in a hidden comment, so a line you delete
doesn't come back.
"""
import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from hackwatch.filters import JORDAN_RE, TECH_RE
from hackwatch.fromurl import _jsonld_events, _place, _when, dates_in_text
from hackwatch.scrapers.base import DEFAULT_USER_AGENT
from hackwatch.urls import clean_url, normalize_url

ISSUE_TITLE = "Candidate events"
DAYS_AHEAD = 180
DEFAULT_DELAY = 5.0
LINE_RE = re.compile(r"^- \[(?P<tick>[ xX])\] (?P<text>.*?) ?<!--k:(?P<key>\w+)-->\s*$")
SEEN_RE = re.compile(r"<!--seen:([\w,]*)-->")
LINE_DATE_RE = re.compile(r"· (\d{4}-\d{2}-\d{2}) ·")
LINK_RE = re.compile(r"\[link\]\((https?://[^)\s]+)\)")
CSE_URL = "https://www.googleapis.com/customsearch/v1"
# A few searches a day: the free quota is 100.
CSE_QUERIES = ["hackathon Jordan university 2026", "tech workshop Amman register", "robotics competition Jordan",
               "AI conference Amman", "هاكاثون الأردن جامعة", "ورشة عمل برمجة عمان تسجيل", "مسابقة روبوت الأردن"]


@dataclass
class Candidate:
    title: str
    url: str
    source: str
    start: Optional[str] = None
    place: Optional[str] = None

    @property
    def key(self) -> str:
        return hashlib.sha256(normalize_url(self.url).encode()).hexdigest()[:10]


def sanitize(text: str, limit: int = 120) -> str:
    """Plain words for a Markdown checklist line: no markup, mentions, links or comments."""
    text = re.sub(r"[\[\]()<>`*_|#@!~\\]", " ", str(text or ""))
    return " ".join(text.split())[:limit].strip()


def _title_key(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (title or "").lower()).split())


def candidates_from_html(html: str, base_url: str, source: str, today: date) -> List[Candidate]:
    """JSON-LD events, then links with a future date next to them; tech ones only."""
    soup = BeautifulSoup(html, "html.parser")
    last = today + timedelta(days=DAYS_AHEAD)
    found: Dict[str, Candidate] = {}

    def keep(title, url, day, place=None):
        url = clean_url(urljoin(base_url, url or ""))
        if not url.startswith(("http://", "https://")) or not title or not TECH_RE.search(title):
            return
        if day and not today.isoformat() <= day <= last.isoformat():
            return
        c = Candidate(title=title, url=url, source=source, start=day, place=place)
        found.setdefault(c.key, c)

    for event in _jsonld_events(soup):
        day, _ = _when(event.get("startDate"))
        place, _mode = _place(event.get("location"))
        if day:
            keep(event.get("name"), event.get("url") or base_url, day, place)
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ").split())
        if not 12 <= len(title) <= 160 or a["href"].startswith(("#", "javascript:", "mailto:")):
            continue
        node, dates = a, []
        for _ in range(4):   # the date is usually in the same card as the link
            node = node.parent
            if node is None:
                break
            text = " ".join(node.get_text(" ").split())
            # Bigger than one card (several links or a lot of text): its dates aren't this link's.
            if len(text) > 500 or len({x["href"] for x in node.find_all("a", href=True)}) > 1:
                break
            dates = [d for d, _dl in dates_in_text(text)]
            if dates:
                break
        upcoming = [d for d in dates if today.isoformat() <= d <= last.isoformat()]
        if upcoming:
            keep(title, a["href"], upcoming[0])
    return list(found.values())


class PoliteFetcher:
    """One host at a time, honest User-Agent, robots.txt rules and Crawl-delay respected."""

    def __init__(self, session=None, sleep: Callable[[float], None] = time.sleep):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.robots: Dict[str, Optional[RobotFileParser]] = {}

    def _get(self, url: str):
        return self.session.get(url, timeout=30, headers={"User-Agent": DEFAULT_USER_AGENT})

    def _rules(self, url: str) -> Optional[RobotFileParser]:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self.robots:
            parser = RobotFileParser()
            try:
                resp = self._get(f"{host}/robots.txt")
                # 4xx = no rules (the usual reading of the standard). 5xx or no answer: stay away.
                if resp.status_code >= 500:
                    self.robots[host] = None
                    return None
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                self.robots[host] = None
                return None
            self.robots[host] = parser
        return self.robots[host]

    def fetch(self, url: str) -> Tuple[Optional[str], str]:
        """(html, status note). html is None when skipped or failed; the note says why."""
        rules = self._rules(url)
        if rules is None:
            return None, "robots.txt unavailable, skipped"
        if not rules.can_fetch(DEFAULT_USER_AGENT, url):
            return None, "disallowed by robots.txt"
        self.sleep(max(rules.crawl_delay(DEFAULT_USER_AGENT) or 0, DEFAULT_DELAY))
        try:
            resp = self._get(url)
        except requests.RequestException as exc:
            return None, type(exc).__name__
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        want, got = urlsplit(url).path.rstrip("/"), urlsplit(resp.url).path.rstrip("/")
        if want and not got.startswith(want):
            return None, f"redirects to {got or '/'}, skipped"
        return resp.text, "ok"


def google_candidates(key: str, engine: str, session=None) -> List[Candidate]:
    """Optional searches (GOOGLE_CSE_KEY + GOOGLE_CSE_ID). Dates are often unknown here."""
    session = session or requests.Session()
    found = []
    for query in CSE_QUERIES:
        try:
            resp = session.get(CSE_URL, params={"key": key, "cx": engine, "q": query, "num": 10,
                                                "dateRestrict": "m1"}, timeout=30)
            resp.raise_for_status()
            items = resp.json().get("items") or []
        except (requests.RequestException, ValueError):
            continue
        for item in items:
            title, url = item.get("title") or "", item.get("link") or ""
            text = f"{title} {item.get('snippet') or ''}"
            if url.startswith("http") and TECH_RE.search(text) and (JORDAN_RE.search(text) or "الأردن" in text or "عمان" in text):
                upcoming = [d for d, _ in dates_in_text(text) if d >= date.today().isoformat()]
                found.append(Candidate(title=title, url=clean_url(url), source="Google search",
                                       start=upcoming[0] if upcoming else None))
    return found


def not_listed(candidates: Iterable[Candidate], listed: Iterable[dict]) -> List[Candidate]:
    """Drop what's already on the site: same link or same title, and repeats among the finds."""
    urls, titles = set(), set()
    for event in listed or []:
        titles.add(_title_key(event.get("title")))
        for url in [event.get("url")] + list(event.get("urls") or []):
            if url:
                urls.add(normalize_url(url))
    out = []
    for c in candidates:
        if normalize_url(c.url) in urls or _title_key(c.title) in titles:
            continue
        urls.add(normalize_url(c.url))
        titles.add(_title_key(c.title))
        out.append(c)
    return out


def candidate_line(c: Candidate) -> str:
    parts = [f"**{sanitize(c.title)}**", c.start or "date unknown", sanitize(c.place, 60) or "place unknown",
             f"[link]({c.url.replace(')', '%29').replace(' ', '%20')})", sanitize(c.source, 30)]
    return f"- [ ] {' · '.join(parts)} <!--k:{c.key}-->"


def merge_body(existing: Optional[str], candidates: Iterable[Candidate], report: List[Tuple[str, str, int]],
               today: date) -> Tuple[str, int]:
    """The issue text: lines people already have, minus expired unticked ones, plus new finds."""
    kept, seen = [], set()
    match = SEEN_RE.search(existing or "")
    if match:
        seen.update(k for k in match.group(1).split(",") if k)
    for raw in (existing or "").splitlines():
        line = LINE_RE.match(raw)
        if not line:
            continue
        seen.add(line.group("key"))
        when = LINE_DATE_RE.search(line.group("text"))
        if line.group("tick") == " " and when and when.group(1) < today.isoformat():
            continue
        kept.append(raw.rstrip())
    new = [c for c in candidates if c.key not in seen]
    seen.update(c.key for c in new)
    lines = kept + [candidate_line(c) for c in new]
    checked = "\n".join(f"| {sanitize(n, 40)} | {sanitize(s, 60)} | {count} |" for n, s, count in report)
    body = "\n".join([
        "Possible Jordan tech events found automatically. **Nothing here is published on its own.**",
        "",
        "Tick a box to open a pull request adding that event (through `hackwatch add --from-url`); "
        "merging the PR is what publishes it. Delete a line to dismiss it; it won't come back.",
        "",
        "\n".join(lines) if lines else "_No candidates right now._",
        "",
        "### Checked in the last run",
        "",
        "| Source | Result | Finds |",
        "|---|---|---|",
        checked,
        "",
        f"_Updated {today.isoformat()}._",
        f"<!--seen:{','.join(sorted(seen))}-->",
    ])
    return body, len(new)


def run(pages: List[dict], listed: List[dict], api, fetcher: Optional[PoliteFetcher] = None,
        today: Optional[date] = None, env=os.environ, log: Callable[[str], None] = print) -> int:
    """Check every page, update the one issue; returns how many new lines were added."""
    today = today or date.today()
    fetcher = fetcher or PoliteFetcher()
    found: List[Candidate] = []
    report: List[Tuple[str, str, int]] = []
    for page in pages:
        html, note = fetcher.fetch(page["url"])
        finds = candidates_from_html(html, page["url"], page["name"], today) if html else []
        fresh = not_listed(finds, listed)
        report.append((page["name"], note, len(fresh)))
        found += fresh
    key, engine = env.get("GOOGLE_CSE_KEY"), env.get("GOOGLE_CSE_ID")
    if key and engine:
        fresh = not_listed(google_candidates(key, engine), listed)
        report.append(("Google search", "ok", len(fresh)))
        found += fresh
    found = not_listed(found, [])
    existing = api.find_open(ISSUE_TITLE)
    body, added = merge_body(existing["body"] if existing else None, found, report, today)
    if existing:
        api.update(existing["number"], body)
    else:
        api.create(ISSUE_TITLE, body)
    log(f"{added} new candidate(s); checked {len(report)} source(s).")
    for name, note, count in report:
        log(f"  {name}: {note}, {count} find(s)")
    return added
