import re
from datetime import datetime, date
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register


def infer_year(day: int, month_name: str, today: date) -> Optional[date]:
    """Pick the year that puts "day month" nearest to today.

    JOSA shows dates without a year, and lists both recent and upcoming events,
    so "5 January" seen in late December means next year, and "28 December"
    seen in early January means last year.
    """
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y").date())
        except ValueError:
            pass  # bad month name, or 29 February in a non-leap year
    if not candidates:
        return None
    return min(candidates, key=lambda d: abs((d - today).days))


@register("josa")
class JOSAScraper(BaseScraper):
    def __init__(self, events_url: str = "https://josa.ngo/events", delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.events_url = events_url

    def fetch(self) -> List[Event]:
        resp = self.get(self.events_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Event] = []

        today = date.today()

        previews = soup.select("div.preview")
        for preview in previews:
            strings = list(preview.stripped_strings)
            if not strings:
                continue

            raw_date = strings[0]
            title = strings[1] if len(strings) > 1 else None
            if not title:
                continue

            link_tag = preview.find("a", href=lambda h: h and "/events/" in h)
            if not link_tag or not link_tag.get("href"):
                continue

            url = urljoin("https://josa.ngo", link_tag["href"])

            # Location / Venue if present
            location = "Amman, Jordan"
            for s in strings[2:]:
                if "Jordan Open Source Association" in s or "School of" in s or "King Abdullah" in s:
                    location = f"{s}, Amman, Jordan"
                    break

            # Date parsing (e.g. "Saturday - 24 October")
            iso_date = None
            date_match = re.search(r"(\d{1,2})\s+([A-Za-z]+)", raw_date)
            if date_match:
                found = infer_year(int(date_match.group(1)), date_match.group(2), today)
                iso_date = found.isoformat() if found else None

            is_online = "online" in title.lower() or "webinar" in title.lower()

            events.append(Event(
                title=title,
                url=url,
                source=self.name,
                organizer="Jordan Open Source Association (JOSA)",
                prize="N/A",
                registration_deadline=iso_date,
                start_date=iso_date,
                end_date=iso_date,
                location="Online" if is_online else location,
                is_online=is_online,
                description=None
            ))

        return events
