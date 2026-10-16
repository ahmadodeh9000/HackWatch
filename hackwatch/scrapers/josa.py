import re
from datetime import datetime, date
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


class JOSAScraper(BaseScraper):
    name: str = "josa"

    def __init__(self, events_url: str = "https://josa.ngo/events", delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.events_url = events_url

    def fetch(self) -> List[Event]:
        resp = self.get(self.events_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Event] = []

        # Current year fallback
        current_year = date.today().year

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
                day, month_name = date_match.group(1), date_match.group(2)
                for year in (current_year, current_year - 1, current_year + 1):
                    try:
                        dt = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y")
                        iso_date = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        pass

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
