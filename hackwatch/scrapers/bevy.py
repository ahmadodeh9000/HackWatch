"""Events from Bevy community sites (gdg.community.dev, startupgrind.com) via their public pages.

Bevy's /api/ path is disallowed in those sites' robots.txt, so this reads what a
visitor sees instead: each chapter page links its upcoming events, and each event
page carries a schema.org Event in JSON-LD (dates, place, attendance mode, and the
registration close time in offers.validThrough), plus the chapter's own event tags.
"""
import html
import json
import re
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from hackwatch.filters import JORDAN_RE
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date, local_time

ATTENDANCE_MODES = {"OfflineEventAttendanceMode": "in-person", "OnlineEventAttendanceMode": "online",
                    "MixedEventAttendanceMode": "hybrid"}
AUDIENCE_MODES = {"IN_PERSON": "in-person", "VIRTUAL": "online", "HYBRID": "hybrid"}
AUDIENCE_RE = re.compile(r"""["']audience_type["']\s*:\s*["'](\w+)["']""")
DETAILS_RE = re.compile(r"^(/events/details/[^/]+/)")
# /events/details/google-gdg-aqaba-presents-devfest/ -> google-gdg-aqaba
HOST_RE = re.compile(r"/events/details/(.+?)-presents-")


def own_chapter(url: str, chapters: List[str]) -> Optional[str]:
    """Which of `chapters` hosts this event, from its URL. Chapter pages also list events
    they only co-host: GDG Aqaba's lists GDG on Campus Sudan University's."""
    m = HOST_RE.search(urlsplit(url).path)
    if m:
        for slug in chapters:
            if m.group(1) == slug or m.group(1).endswith("-" + slug):
                return slug
    return None


def upcoming_event_links(html: str, base_url: str, limit: int) -> List[str]:
    """Event page URLs listed above the chapter page's "Past events" heading."""
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for node in soup.find_all(["h1", "h2", "a"]):
        if node.name in ("h1", "h2"):
            if "past events" in node.get_text(" ", strip=True).lower():
                break
            continue
        path = urlsplit(urljoin(base_url, node.get("href") or "")).path
        m = DETAILS_RE.match(path)  # drops suffixes like /cohost-gdg-amman
        if m:
            url = urljoin(base_url, m.group(1))
            if url not in links:
                links.append(url)
    return links[:limit]


def chapter_name(html: str) -> Optional[str]:
    """'GDG Amman | Google Developer Groups' -> 'GDG Amman'."""
    og = BeautifulSoup(html, "html.parser").find("meta", property="og:title")
    return og["content"].split(" | ")[0].strip() if og and og.get("content") else None


def parse_event_page(html: str) -> Optional[dict]:
    """The JSON-LD Event, the page's event tags and audience_type, or None."""
    soup = BeautifulSoup(html, "html.parser")
    event = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Event":
                event = item
    if not event:
        return None
    tags_script = soup.find("script", id="event_tags")
    try:
        tags = json.loads(tags_script.string) if tags_script and tags_script.string else []
    except ValueError:
        tags = []
    audience = AUDIENCE_RE.search(html)
    return {"event": event, "tags": [str(t) for t in tags], "audience": audience.group(1) if audience else None}


def _cost(price) -> Optional[str]:
    """Bevy ticket price: 0 (an RSVP) = free, more = paid, missing = unknown."""
    try:
        return None if price is None or price == "" else ("free" if float(price) == 0 else "paid")
    except (TypeError, ValueError):
        return None


def _location(event: dict, mode: str) -> str:
    if mode == "online":
        return "Online"
    place = event.get("location") or {}
    if isinstance(place, list):
        place = next((p for p in place if p.get("@type") == "Place"), place[0] if place else {})
    address = place.get("address") or {}
    if isinstance(address, str):
        address = {"streetAddress": address}
    venue = place.get("name") if place.get("name") not in (None, "", "TBA") else None
    city = address.get("addressLocality")
    country = address.get("addressCountry")
    # Bevy's country can be wrong: GDG Aqaba's DevFest at iPARK, Aqaba says "US". A Jordanian
    # city or venue wins, else the filter would drop the event as abroad.
    if country in ("JO", "Jordan") or JORDAN_RE.search(f"{venue or ''} {city or ''}"):
        country = "Jordan"
    parts = [p for p in (venue or address.get("streetAddress"), city, country) if p]
    return ", ".join(dict.fromkeys(parts)) or "TBA"


@register("bevy")
class BevyScraper(BaseScraper):
    def __init__(self, base_url: str, chapters: List[str], max_events_per_chapter: int = 15,
                 organizer: str = "{chapter}", delay_seconds: float = 2.0):
        """organizer: template for the organizer name; {chapter} is the chapter page's
        own name (og:title), e.g. "GDG Amman", or just "Amman" on Startup Grind."""
        super().__init__(delay_seconds=delay_seconds)  # robots.txt asks for Crawl-delay: 2
        if not chapters:
            raise ValueError("bevy needs chapters (chapter page slugs, e.g. gdg-amman)")
        self.base_url = base_url.rstrip("/") + "/"
        self.chapters = list(chapters)
        self.max_events_per_chapter = max_events_per_chapter
        self.organizer = organizer

    def fetch(self) -> List[Event]:
        # Chapter pages first: an event may be listed on another chapter's page than its own.
        pages = {slug: self.get(urljoin(self.base_url, slug.strip("/") + "/")).text for slug in self.chapters}
        names = {slug: chapter_name(html) for slug, html in pages.items()}
        events: List[Event] = []
        seen = set()
        for html in pages.values():
            for url in upcoming_event_links(html, self.base_url, self.max_events_per_chapter):
                if url in seen:
                    continue  # co-hosted events appear on several chapter pages
                seen.add(url)
                host = own_chapter(url, self.chapters)
                if not host:
                    continue  # another chapter's event, only co-hosted by one of ours
                page = parse_event_page(self.get(url).text)
                if page:
                    name = names[host]
                    events.append(self._event(url, page, self.organizer.format(chapter=name) if name else None))
        return events

    def _event(self, url: str, page: dict, organizer: Optional[str]) -> Event:
        ev = page["event"]
        mode = (AUDIENCE_MODES.get((page["audience"] or "").upper())
                or ATTENDANCE_MODES.get(str(ev.get("eventAttendanceMode", "")).rsplit("/", 1)[-1], "in-person"))
        offers = ev.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        description = " ".join(BeautifulSoup(ev.get("description") or "", "html.parser").get_text(" ").split())
        start_date = local_date(ev.get("startDate"))
        # offers.validThrough is when registration closes. Often it's just the start of the
        # event, which isn't a deadline worth showing; keep it only if it's earlier.
        deadline = local_date(offers.get("validThrough"))
        if deadline and start_date and deadline >= start_date:
            deadline = None
        return Event(
            cost=_cost(offers.get("price")),
            title=" ".join(html.unescape(str(ev.get("name") or "")).split()),
            url=url,
            source=self.name,
            organizer=organizer,
            prize="N/A",
            registration_deadline=deadline,
            start_date=start_date,
            end_date=local_date(ev.get("endDate")),
            start_time=local_time(ev.get("startDate")),
            end_time=local_time(ev.get("endDate")),
            mode=mode,
            location=_location(ev, mode),
            description=description[:600] or None,
            source_labels=page["tags"],
        )
