"""IEEE RAS UJ (ras-uj.site), the University of Jordan robotics society.

The site looks JavaScript-only, but its /e/<date-slug> pages are prerendered with the event's
record in <script id="ev-data">, and sitemap.xml lists them all. robots.txt allows both (it
disallows /f/, /hub/ and /.netlify/). So: the sitemap, then only pages dated today or later. The
/f/ registration link is passed on for people to click; it's never fetched.
"""
import json
import re
from datetime import date
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hackwatch.filters import TECH_RE
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date, local_time

SLUG_RE = re.compile(r"<loc>(https://ras-uj\.site/e/(\d{4}-\d{2}-\d{2})-[^<]+)</loc>")
# The site's own category. "event" is general club life (an iftar, say): see low_signal below.
KINDS = {"workshop": "workshop", "ورشة": "workshop", "competition": "competition", "مسابقة": "competition",
         "talk": "meetup", "lecture": "meetup", "محاضرة": "meetup"}


def upcoming_pages(sitemap: str, today: date) -> List[str]:
    return [url for url, day in SLUG_RE.findall(sitemap) if day >= today.isoformat()]


def page_record(html: str) -> Optional[dict]:
    node = BeautifulSoup(html, "html.parser").find("script", id="ev-data")
    try:
        return json.loads(node.string)["event"] if node and node.string else None
    except (ValueError, KeyError):
        return None


@register("rasuj")
class RasUjScraper(BaseScraper):
    sitemap_url = "https://ras-uj.site/sitemap.xml"

    def __init__(self, organizer: str = "IEEE RAS UJ", city: str = "Amman", open_to: Optional[str] = None,
                 delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.organizer = organizer
        self.city = city
        self.open_to = open_to
        self.today: Optional[date] = None   # tests pin this

    def fetch(self) -> List[Event]:
        events = []
        for url in upcoming_pages(self.get(self.sitemap_url).text, self.today or date.today()):
            record = page_record(self.get(url).text)
            if record and record.get("published") and record.get("starts_at"):
                events.append(self._event(url, record))
        return events

    def _event(self, url: str, r: dict) -> Event:
        venue = (r.get("venue") or "").strip()
        online = venue.lower() == "online" or venue == "عن بعد"
        title_ar, title_en = (r.get("title_ar") or "").strip(), (r.get("title_en") or "").strip()
        kind = str(r.get("kind") or "").strip().lower()
        words = f"{title_ar} {title_en}"
        link = r.get("link")
        return Event(
            title=title_ar or title_en,   # as the club wrote it
            url=url,
            source=self.name,
            organizer=self.organizer,
            start_date=local_date(r["starts_at"]),
            end_date=local_date(r.get("ends_at") or r["starts_at"]),
            start_time=local_time(r["starts_at"]),
            end_time=local_time(r["ends_at"]) if r.get("ends_at") else None,
            location="Online" if online else ", ".join(p for p in (venue, self.city, "Jordan") if p),
            mode="online" if online else "in-person",
            country=None if online else "JO",
            type=KINDS.get(kind),
            description=" ".join((r.get("desc_ar") or r.get("desc_en") or "").split())[:600] or None,
            registration_url=urljoin(url, link) if link else None,
            open_to=self.open_to,
            source_labels=[title_en] if title_en else [],   # lets inference read the English title
            # A general club event with nothing technical in its name (an iftar) is club life.
            low_signal=True if kind == "event" and not TECH_RE.search(words) else None,
        )
