from datetime import datetime
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


def parse_devpost_dates(date_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse Devpost date ranges like 'Aug 31 - Oct 23, 2026' into ISO (YYYY-MM-DD)."""
    if not date_str:
        return None, None

    parts = [p.strip() for p in date_str.split(" - ")]
    date_formats = ["%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%Y-%m-%d"]

    if len(parts) == 1:
        for fmt in date_formats:
            try:
                dt = datetime.strptime(parts[0], fmt)
                iso = dt.strftime("%Y-%m-%d")
                return iso, iso
            except ValueError:
                pass
        return None, None

    end_str = parts[1]
    start_str = parts[0]
    end_dt = None

    for fmt in date_formats:
        try:
            end_dt = datetime.strptime(end_str, fmt)
            break
        except ValueError:
            pass

    if not end_dt:
        return None, None

    end_iso = end_dt.strftime("%Y-%m-%d")

    # Try parsing start with full format first
    for fmt in date_formats:
        try:
            start_dt = datetime.strptime(start_str, fmt)
            return start_dt.strftime("%Y-%m-%d"), end_iso
        except ValueError:
            pass

    # Try attaching end_dt's year
    for fmt in ["%b %d, %Y", "%B %d, %Y"]:
        try:
            start_dt = datetime.strptime(f"{start_str}, {end_dt.year}", fmt)
            # If start month is after end month, start year might be previous year
            if start_dt > end_dt:
                start_dt = start_dt.replace(year=end_dt.year - 1)
            return start_dt.strftime("%Y-%m-%d"), end_iso
        except ValueError:
            pass

    return None, end_iso


class DevpostScraper(BaseScraper):
    name: str = "devpost"

    def __init__(self, max_pages: int = 2, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.max_pages = max_pages
        self.api_url = "https://devpost.com/api/hackathons"

    def fetch(self) -> List[Event]:
        events: List[Event] = []

        for page in range(1, self.max_pages + 1):
            params = {
                "status[]": ["upcoming", "open"],
                "page": page
            }
            resp = self.get(self.api_url, params=params)
            data = resp.json()
            hackathons = data.get("hackathons", [])
            if not hackathons:
                break

            for item in hackathons:
                title = item.get("title")
                url = item.get("url")
                if not title or not url:
                    continue

                # Prize extraction & tag strip
                prize_raw = item.get("prize_amount")
                prize = None
                if prize_raw:
                    prize = BeautifulSoup(str(prize_raw), "html.parser").get_text(strip=True)

                # Organizer
                organizer = item.get("organization_name")

                # Location & Online status
                loc_data = item.get("displayed_location")
                location = None
                is_online = False
                if isinstance(loc_data, dict):
                    location = loc_data.get("location")
                elif isinstance(loc_data, str):
                    location = loc_data

                if location and "online" in location.lower():
                    is_online = True

                # Dates
                dates_raw = item.get("submission_period_dates")
                start_date, end_date = parse_devpost_dates(dates_raw)
                registration_deadline = end_date

                # Themes / Description
                themes = [t.get("name") for t in item.get("themes", []) if isinstance(t, dict) and t.get("name")]
                description = f"Themes: {', '.join(themes)}" if themes else None

                event = Event(
                    title=title,
                    url=url,
                    source=self.name,
                    organizer=organizer,
                    prize=prize,
                    registration_deadline=registration_deadline,
                    start_date=start_date,
                    end_date=end_date,
                    location=location,
                    is_online=is_online,
                    description=description
                )
                events.append(event)

        return events
