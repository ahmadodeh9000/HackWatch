"""The organizer census: what each organizer's site offers a polite reader.

`signals()` looks at one fetched page and reports what is on it (feeds, schema.org events,
dates, an empty app shell, a block page, social links). `classify()` turns the probes of
one organizer, from a home connection and from a GitHub runner, into one of CLASSES.
The census itself is organizers.yaml; scripts/census_probe.py fetches the pages.
"""
import json
import re
from datetime import date
from html import unescape
from typing import Dict, Iterable, List, Optional

CLASSES = (
    "api_feed",        # iCal, RSS with events, or a documented public API
    "clean_html",      # the events are in the HTML the server sends
    "js_endpoint",     # a script-built page with a public data endpoint behind it
    "js_no_endpoint",  # a script-built page; no public endpoint found
    "runner_blocked",  # works from a home connection, refused from GitHub's runners
    "blocked",         # refuses a script everywhere (WAF, captcha, robots.txt)
    "no_listing",      # a working site with no list of upcoming events
    "social_only",     # no site of its own: Instagram / Facebook / LinkedIn only
    "dead",            # the site is gone or the group is inactive
)

SOCIAL = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?", re.I),
    "facebook": re.compile(r"https?://(?:www\.|web\.|m\.)?facebook\.com/([A-Za-z0-9_.\-]+)/?", re.I),
    "linkedin": re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/((?:company|school|in|showcase)/[^/\"'?#\s]+)", re.I),
    "x": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]+)/?", re.I),
    "youtube": re.compile(r"https?://(?:www\.)?youtube\.com/((?:@|c/|channel/|user/)[^/\"'?#\s]+)", re.I),
}
SOCIAL_NOISE = {"sharer", "sharer.php", "share", "intent", "tr", "plugins", "dialog", "p", "reel", "explore",
                "home", "login", "hashtag", "search", "watch", "embed", "profile.php", "pages", "groups", "events"}

RSS_LINK = re.compile(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
ICAL = re.compile(r"(?:href|content)=[\"']([^\"']*(?:\.ics\b|[?&]ical=1|webcal:|/ical/)[^\"']*)[\"']", re.I)
JSONLD = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
GENERATOR = re.compile(r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']([^\"']+)[\"']", re.I)
TAGS = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>|<[^>]+>", re.I | re.S)
EVENT_LINK = re.compile(r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
EVENT_WORDS = re.compile(r"event|calendar|activit|workshop|hackathon|فعالي|نشاط|أنشطة|ورش|مؤتمر", re.I)
BLOCK_WORDS = ("request rejected", "captcha", "access denied", "just a moment", "attention required",
               "cf-challenge", "are you a robot", "incapsula", "not allowed")

MONTHS_EN = ("jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july "
             "august september october november december").split()
MONTH_NUM = {m[:3]: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
MONTHS_AR = {"كانون الثاني": 1, "يناير": 1, "شباط": 2, "فبراير": 2, "آذار": 3, "اذار": 3, "مارس": 3, "نيسان": 4,
             "أبريل": 4, "ابريل": 4, "أيار": 5, "ايار": 5, "مايو": 5, "حزيران": 6, "يونيو": 6, "تموز": 7,
             "يوليو": 7, "آب": 8, "أغسطس": 8, "اغسطس": 8, "أيلول": 9, "ايلول": 9, "سبتمبر": 9,
             "تشرين الأول": 10, "تشرين الاول": 10, "أكتوبر": 10, "اكتوبر": 10, "تشرين الثاني": 11,
             "نوفمبر": 11, "كانون الأول": 12, "كانون الاول": 12, "ديسمبر": 12}
DATE_ISO = re.compile(r"\b(20\d\d)[-/.](\d{1,2})[-/.](\d{1,2})\b")
DATE_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d\d)\b")
DATE_EN = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s,-]+(%s)\.?[\s,-]+(20\d\d)\b" % "|".join(MONTHS_EN), re.I)
DATE_EN2 = re.compile(r"\b(%s)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b" % "|".join(MONTHS_EN), re.I)
DATE_AR = re.compile(r"(\d{1,2})\s+(%s)\s+(20\d\d)" % "|".join(sorted(MONTHS_AR, key=len, reverse=True)))
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def visible_text(html: str) -> str:
    return " ".join(unescape(TAGS.sub(" ", html or "")).split())


def dates_in(text: str) -> List[date]:
    """Every date written in the text, in English, Arabic or digits (day first for 1/2/2026)."""
    text = (text or "").translate(ARABIC_DIGITS)
    found = []

    def add(y, m, d):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    for m in DATE_ISO.finditer(text):
        add(m[1], m[2], m[3])
    for m in DATE_DMY.finditer(text):
        add(m[3], m[2], m[1])
    for m in DATE_EN.finditer(text):
        add(m[3], MONTH_NUM[m[2][:3].lower()], m[1])
    for m in DATE_EN2.finditer(text):
        add(m[3], MONTH_NUM[m[1][:3].lower()], m[2])
    for m in DATE_AR.finditer(text):
        add(m[3], MONTHS_AR[m[2]], m[1])
    return found


def _jsonld_events(html: str) -> int:
    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, dict):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(isinstance(k, str) and k.endswith("Event") for k in kinds):
                count += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for block in JSONLD.findall(html or ""):
        try:
            walk(json.loads(block.strip()))
        except ValueError:
            continue
    return count


def social_links(html: str) -> Dict[str, str]:
    """The first account of each network linked from the page (links only; never fetched)."""
    out = {}
    for name, regex in SOCIAL.items():
        for m in regex.finditer(html or ""):
            handle = m.group(1).strip("/")
            if handle.split("/")[0].lower() in SOCIAL_NOISE:
                continue
            out[name] = m.group(0).rstrip("/")
            break
    return out


def signals(html: str, today: Optional[date] = None) -> dict:
    """What one page offers: feeds, schema.org events, dates, platform, social links."""
    today = today or date.today()
    html = html or ""
    text = visible_text(html)
    dates = dates_in(text)
    feeds = []
    for tag in RSS_LINK.findall(html):
        m = HREF.search(tag)
        if m:
            feeds.append(unescape(m.group(1)))
    low = html[:40000].lower()
    generator = GENERATOR.search(html)
    platform = generator.group(1) if generator else ""
    if not platform and ("/wp-content/" in html or "/wp-json" in html):
        platform = "WordPress"
    if "tribe-events" in html or "the-events-calendar" in html:
        platform = (platform + " + The Events Calendar").strip(" +")
    event_links = []
    for href, label in EVENT_LINK.findall(html):
        label = visible_text(label)[:60]
        if EVENT_WORDS.search(href) or EVENT_WORDS.search(label):
            if href not in [h for h, _ in event_links]:
                event_links.append((unescape(href), label))
    return {
        "text_chars": len(text),
        "scripts": len(re.findall(r"<script\b", html, re.I)),
        "app_shell": len(text) < 600 and len(re.findall(r"<script\b", html, re.I)) >= 1,
        "rss": feeds[:5],
        "ical": sorted({unescape(u) for u in ICAL.findall(html)})[:5],
        "jsonld_events": _jsonld_events(html),
        "dates": len(dates),
        "future_dates": len({d for d in dates if d >= today}),
        "platform": platform[:60],
        "block_words": [w for w in BLOCK_WORDS if w in low][:3],
        "social": social_links(html),
        "event_links": event_links[:12],
    }


def page_state(probe: Optional[dict]) -> str:
    """'ok' | 'blocked' | 'robots' | 'down' | 'missing' | 'none' for one probed URL."""
    if not probe:
        return "none"
    if probe.get("robots") == "disallowed":
        return "robots"
    status = probe.get("status")
    if status is None:
        return "down"
    if status == 200 and not (probe.get("block_words") and probe.get("text_chars", 0) < 1500):
        return "ok"
    if status in (401, 403, 405, 406, 429, 503) or probe.get("block_words"):
        return "blocked"
    if status in (404, 410):
        return "missing"
    return "down"


def reach(probes: Iterable[dict]) -> str:
    """One word for a whole organizer from one place: the best state among its pages."""
    states = [page_state(p) for p in probes]
    for state in ("ok", "blocked", "robots", "down", "missing"):
        if state in states:
            return state
    return "none"


def suggest(home: List[dict], runner: List[dict]) -> str:
    """A first guess at the class from the probes; the census records a human's decision."""
    if not home and not runner:
        return "social_only"
    h, r = reach(home), reach(runner)
    if h in ("blocked", "robots") and r != "ok":
        return "blocked"
    if h == "ok" and r in ("blocked", "down"):
        return "runner_blocked"
    if h in ("down", "missing") and r != "ok":
        return "dead"
    pages = [p for p in (home if h == "ok" else runner) if page_state(p) == "ok"]
    if any(p.get("ical") or p.get("tribe_events") is not None or p.get("jsonld_events") for p in pages):
        return "api_feed"
    if any(p.get("future_dates") for p in pages):
        return "clean_html"
    if pages and all(p.get("app_shell") for p in pages):
        return "js_no_endpoint"
    return "no_listing"
