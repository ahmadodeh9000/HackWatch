"""Pre-fill a manual event from its web page (`hackwatch add --from-url <url>`).

Reads what the page already says about itself, best source first:

1. schema.org JSON-LD `Event` (Luma, Eventbrite, GDG/Bevy, Meetup and many others)
2. a Google Calendar "add to calendar" link (IEEE vTools and others): exact UTC times
3. Open Graph / meta tags (title, description, `event:start_time`)
4. Google Forms: the form title and description, with dates found in the description

Timestamps with an offset are converted to Amman time; ones without are taken as written.
One page is fetched once, with the same honest User-Agent as the scrapers. Nothing here
guesses type or tags: the CLI runs the normal inference on the result.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from hackwatch.scrapers.base import DEFAULT_USER_AGENT, block_hint
from hackwatch.timeutil import local_date, local_time

FIELDS = ("title", "start_date", "end_date", "start_time", "end_time", "location", "mode",
          "organizer", "description", "registration_deadline")
MODES = {"OnlineEventAttendanceMode": "online", "OfflineEventAttendanceMode": "in-person",
         "MixedEventAttendanceMode": "hybrid"}
MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9
# "15 November 2026", "Nov 15, 2026", "2026-11-15"
_MONTH = r"(?:%s)\.?" % "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_RES = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(%s),?\s+(\d{4})\b" % _MONTH, re.I),
    re.compile(r"\b(%s)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b" % _MONTH, re.I),
)
DEADLINE_WORDS = re.compile(r"deadline|register (?:by|before)|apply (?:by|before)|registration closes|"
                            r"applications? (?:close|until)|until|آخر موعد|حتى", re.I)
# " | Google Developer Groups", " Tickets, Sat 7 Nov 2026 at 10:00 | Eventbrite"
TITLE_SUFFIX = re.compile(r"\s+(?:Tickets,.*|[|·–-]\s*(?:Eventbrite|Luma|Google Developer Groups|"
                          r"Startup Grind|Meetup|vTools Events)\b.*)$", re.I)


@dataclass
class Extracted:
    url: str
    values: Dict[str, str] = field(default_factory=dict)
    found_by: Dict[str, str] = field(default_factory=dict)   # field -> "json-ld" | "gcal-link" | ...
    labels: List[str] = field(default_factory=list)          # keywords/tags the page gives itself
    warnings: List[str] = field(default_factory=list)

    def offer(self, method: str, **values) -> None:
        """Set fields that are still empty (earlier, better methods win)."""
        for key, value in values.items():
            value = " ".join(str(value).split()) if isinstance(value, str) and key != "description" else value
            if value and not self.values.get(key):
                self.values[key] = value.strip() if isinstance(value, str) else value
                self.found_by[key] = method


def _when(value) -> tuple:
    """ISO timestamp -> (date, time) in Amman; naive -> as written; date only -> (date, None)."""
    text = str(value or "").strip()
    if not text:
        return None, None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text, None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if moment.tzinfo is None:
        return moment.date().isoformat(), moment.strftime("%H:%M")
    return local_date(text), local_time(text)


def _names(value) -> List[str]:
    items = value if isinstance(value, list) else [value]
    names = [(i.get("name") if isinstance(i, dict) else i) for i in items if i]
    return [str(n).strip() for n in names if n and str(n).strip()]


def _place(location) -> tuple:
    """schema.org location -> (text, mode or None)."""
    places = location if isinstance(location, list) else [location]
    texts, online, offline = [], False, False
    for place in places:
        if isinstance(place, str):
            texts.append(place)
            offline = True
            continue
        if not isinstance(place, dict):
            continue
        if "Virtual" in str(place.get("@type")):
            online = True
            continue
        offline = True
        address = place.get("address")
        parts = [place.get("name")]
        if isinstance(address, dict):
            country = address.get("addressCountry")
            country = country.get("name") if isinstance(country, dict) else country
            parts += [address.get("streetAddress"), address.get("addressLocality"),
                      "Jordan" if str(country).upper() in ("JO", "JOR") else country]
        elif address:
            parts.append(address)
        seen = []
        for part in parts:
            part = " ".join(str(part or "").split()).strip(", ")
            # Skip parts already contained in an earlier one ("Amman" after "..., Amman, Amman G...").
            if part and part.upper() not in ("TBA", "TBD") and not any(part.lower() in s.lower() for s in seen):
                seen.append(part)
        texts.append(", ".join(seen))
    mode = "hybrid" if online and offline else "online" if online else None
    return (", ".join(t for t in texts if t) or ("Online" if online else "")), mode


def _jsonld_events(soup: BeautifulSoup) -> Iterable[dict]:
    def walk(node):
        if isinstance(node, list):
            for item in node:
                yield from walk(item)
        elif isinstance(node, dict):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(t).endswith("Event") for t in types):
                yield node
            yield from walk(node.get("@graph") or [])
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            yield from walk(json.loads(script.string or script.get_text() or "null"))
        except (ValueError, TypeError):
            continue


def from_jsonld(soup: BeautifulSoup, out: Extracted) -> None:
    for event in _jsonld_events(soup):
        start_date, start_time = _when(event.get("startDate"))
        end_date, end_time = _when(event.get("endDate"))
        location, place_mode = _place(event.get("location"))
        mode = MODES.get(str(event.get("eventAttendanceMode") or "").rsplit("/", 1)[-1]) or place_mode
        offers = event.get("offers")
        offers = offers[0] if isinstance(offers, list) and offers else offers
        deadline, _ = _when((offers or {}).get("validThrough") if isinstance(offers, dict) else None)
        if deadline and start_date and deadline >= start_date:
            deadline = None  # often just the start time, not a real registration deadline
        out.offer("json-ld", title=event.get("name"), start_date=start_date, end_date=end_date,
                  start_time=start_time, end_time=end_time, location=location, mode=mode,
                  organizer=", ".join(_names(event.get("organizer"))[:2]),
                  description=event.get("description"), registration_deadline=deadline)
        keywords = event.get("keywords")
        out.labels += keywords if isinstance(keywords, list) else [k.strip() for k in str(keywords or "").split(",") if k.strip()]
        return  # the first event on the page is the page's own


def from_gcal_link(soup: BeautifulSoup, out: Extracted) -> None:
    """https://www.google.com/calendar/event?action=TEMPLATE&text=...&dates=20261101T070000Z/20261101T123000Z"""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "action=TEMPLATE" not in href or "google.com/calendar" not in href:
            continue
        # The link text isn't always URL-encoded (vTools), so split by hand on '&key='.
        query = urlparse(href.replace("\n", " ").replace(" ", "%20")).query
        params = {k: v[0] for k, v in parse_qs(query).items()}
        start, _, end = params.get("dates", "").partition("/")
        values = {}
        for key, raw in (("start", start), ("end", end)):
            if re.fullmatch(r"\d{8}T\d{6}Z", raw):
                iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[9:11]}:{raw[11:13]}:00+00:00"
                values[key + "_date"], values[key + "_time"] = local_date(iso), local_time(iso)
            elif re.fullmatch(r"\d{8}", raw):
                day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
                if key == "end":
                    day -= timedelta(days=1)  # all-day end is exclusive
                values[key + "_date"] = day.isoformat()
        location = params.get("location", "")
        # vTools repeats parts: "Jordan, Yarmouk University , Irbid, Jordan, Jordan, 21110"
        parts = []
        for p in (s.strip() for s in location.split(",")):
            if p and not p.isdigit() and p not in parts:
                parts.append(p)
        if parts and parts[0] == "Jordan" and len(parts) > 1:
            parts = parts[1:]
        out.offer("gcal-link", title=params.get("text"), location=", ".join(parts),
                  description=params.get("details"), **values)
        return


# gdg.community.dev/events/details/google-gdg-amman-presents-devfest-amman-2026/
BEVY_HOST_RE = re.compile(r"/events/details/(?:google-)?(.+?)-presents-")


def from_bevy(url: str, soup: BeautifulSoup, out: Extracted) -> None:
    """GDG and Startup Grind pages (Bevy): JSON-LD says only "Google Developer Groups" as
    organiser; the chapter is in the URL. The page's own event tags are labels."""
    m = BEVY_HOST_RE.search(urlparse(url).path)
    if m:
        words = [w.upper() if w in ("gdg", "ieee", "ai") else w.capitalize() for w in m.group(1).split("-")]
        out.values["organizer"] = " ".join(words)
        out.found_by["organizer"] = "bevy-url"
    tags = soup.find("script", id="event_tags")
    try:
        out.labels += [str(t) for t in json.loads(tags.string)] if tags and tags.string else []
    except ValueError:
        pass


def from_meta(soup: BeautifulSoup, out: Extracted) -> None:
    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"]
        return None
    title = meta("og:title", "twitter:title") or (soup.title.string if soup.title else None)
    start_date, start_time = _when(meta("event:start_time", "og:start_time"))
    end_date, end_time = _when(meta("event:end_time"))
    out.offer("open-graph", title=TITLE_SUFFIX.sub("", title or "").strip(),
              description=meta("og:description", "description", "twitter:description"),
              start_date=start_date, start_time=start_time, end_date=end_date, end_time=end_time)
    keywords = meta("keywords")
    if keywords:
        out.labels += [k.strip() for k in keywords.split(",") if k.strip()]


def from_google_form(html: str, soup: BeautifulSoup, out: Extracted) -> None:
    """Forms put the description in FB_PUBLIC_LOAD_DATA_ = [null, [description, ...], ...]."""
    m = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);\s*</script>", html, re.S)
    if not m:
        return
    try:
        data = json.loads(m.group(1))
        description = data[1][0] if isinstance(data[1][0], str) else None
        title = data[1][8] if len(data[1]) > 8 and isinstance(data[1][8], str) else None
    except (ValueError, IndexError, TypeError):
        return
    out.offer("google-form", title=title, description=description)
    out.warnings.append("Google Form: the link is a registration form; dates come from its description, check them.")


def dates_in_text(text: str) -> List[tuple]:
    """[(iso_date, is_deadline)] in the order they appear."""
    found = []
    for regex in DATE_RES:
        for m in regex.finditer(text or ""):
            g = m.groups()
            try:
                if regex is DATE_RES[0]:
                    d = date(int(g[0]), int(g[1]), int(g[2]))
                elif regex is DATE_RES[1]:
                    d = date(int(g[2]), MONTHS[g[1].lower().rstrip(".")], int(g[0]))
                else:
                    d = date(int(g[2]), MONTHS[g[0].lower().rstrip(".")], int(g[1]))
            except (ValueError, KeyError):
                continue
            # Only the words just before this date, in the same sentence.
            before = re.split(r"[.!?\n]\s", text[max(0, m.start() - 40):m.start()])[-1]
            found.append((m.start(), d.isoformat(), bool(DEADLINE_WORDS.search(before))))
    return [(d, dl) for _, d, dl in sorted(found)]


def from_text(out: Extracted) -> None:
    """Last resort for pages without structured dates (Google Forms, plain pages)."""
    if out.values.get("start_date"):
        return
    found = dates_in_text(out.values.get("description", ""))
    deadlines = [d for d, is_deadline in found if is_deadline]
    others = sorted({d for d, is_deadline in found if not is_deadline})
    if others:
        out.offer("text", start_date=others[0], end_date=others[-1] if len(others) > 1 else None)
    if deadlines and (not others or deadlines[0] <= others[0]):
        out.offer("text", registration_deadline=deadlines[0])


def extract(html: str, url: str) -> Extracted:
    soup = BeautifulSoup(html, "html.parser")
    out = Extracted(url=url)
    from_jsonld(soup, out)
    if re.search(r"(gdg\.community\.dev|startupgrind\.com)/events/details/", url):
        from_bevy(url, soup, out)
    from_gcal_link(soup, out)
    if "docs.google.com/forms" in url or "FB_PUBLIC_LOAD_DATA_" in html:
        from_google_form(html, soup, out)
    from_meta(soup, out)
    from_text(out)
    v = out.values
    if v.get("end_date") and v.get("end_date") == v.get("start_date"):
        v.pop("end_date")
    if v.get("registration_deadline") and v["registration_deadline"] > (v.get("end_date") or v.get("start_date") or "9999"):
        out.warnings.append(f"Dropped registration deadline {v.pop('registration_deadline')}: after the event.")
    if v.get("mode") == "online":
        v["location"] = "Online"
    if v.get("description"):
        v["description"] = " ".join(v["description"].split())[:600]
    if not v.get("start_date"):
        out.warnings.append("No date found on the page; enter it by hand.")
    return out


def fetch_html(url: str, timeout: float = 30.0) -> tuple:
    """(final_url, html). Raises ValueError with a readable reason on failure."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"})
    except requests.RequestException as exc:
        raise ValueError(f"couldn't fetch {url}: {type(exc).__name__}") from exc
    hint = block_hint(resp)
    if resp.status_code >= 400:
        raise ValueError(f"{url} answered HTTP {resp.status_code}" + (f" ({hint})" if hint else ""))
    return resp.url, resp.text


def extract_from_url(url: str) -> Extracted:
    final_url, html = fetch_html(url)
    out = extract(html, final_url)
    # Keep the link people shared (forms.gle/..., lu.ma/...) unless it only redirected to a login.
    out.url = url
    return out


def suggest(out: Extracted) -> Dict[str, str]:
    """The extracted fields as `hackwatch add` options, plus inferred type and tags.

    Adds warnings for things that would hide or drop the event (club life, in person
    outside Jordan).
    """
    from hackwatch.countries import to_iso2
    from hackwatch.infer import infer_tags, infer_type, is_low_signal
    from hackwatch.models import Event

    v = out.values
    event = Event(title=v.get("title") or "", url=out.url, source="manual",
                  description=v.get("description"), source_labels=list(out.labels))
    dates = v.get("start_date")
    if dates and v.get("end_date"):
        dates += f" to {v['end_date']}"
    result = {"title": v.get("title"), "url": out.url, "dates": dates, "location": v.get("location"),
              "organizer": v.get("organizer"), "mode": v.get("mode"), "type": infer_type(event) or "other",
              "tags": ",".join(infer_tags(event)), "start_time": v.get("start_time"),
              "end_time": v.get("end_time"), "deadline": v.get("registration_deadline"),
              "description": v.get("description")}
    if is_low_signal(event):
        out.warnings.append("The title looks like club life (low_signal): hidden on the site unless toggled.")
    country = to_iso2(v.get("location") or "")
    if v.get("mode") != "online" and country and country != "JO":
        # Manual entries skip filters.is_relevant, so nothing would stop it: say so here.
        out.warnings.append(f"In person outside Jordan ({country}): HackWatch only lists in-person events "
                            "in Jordan; add it only if it's also online.")
    return {k: val for k, val in result.items() if val}
