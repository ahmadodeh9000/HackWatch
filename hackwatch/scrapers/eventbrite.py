import json
from typing import List, Optional
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


def clean_eventbrite_url(url: str) -> str:
    """Strip tracking query parameters from Eventbrite URLs."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


class EventbriteScraper(BaseScraper):
    name: str = "eventbrite"

    def __init__(self, search_url: str = "https://www.eventbrite.com/d/online/hackathon/", delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.search_url = search_url

    def fetch(self) -> List[Event]:
        resp = self.get(self.search_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        events: List[Event] = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            if data.get("@type") != "ItemList":
                continue

            items = data.get("itemListElement", [])
            for it in items:
                event_data = it.get("item", {}) if isinstance(it, dict) else {}
                title = event_data.get("name")
                raw_url = event_data.get("url")
                if not title or not raw_url:
                    continue

                url = clean_eventbrite_url(raw_url)

                start_raw = event_data.get("startDate")
                end_raw = event_data.get("endDate")
                start_date = str(start_raw)[:10] if start_raw else None
                end_date = str(end_raw)[:10] if end_raw else None

                attendance_mode = str(event_data.get("eventAttendanceMode", ""))
                is_online = "OnlineEventAttendanceMode" in attendance_mode

                loc_info = event_data.get("location")
                location = "Online" if is_online else None
                if isinstance(loc_info, dict):
                    if loc_info.get("@type") == "VirtualLocation":
                        is_online = True
                        location = "Online"
                    elif loc_info.get("name"):
                        location = loc_info.get("name")
                    elif loc_info.get("address"):
                        addr = loc_info["address"]
                        if isinstance(addr, dict):
                            parts = [addr.get("addressLocality"), addr.get("addressCountry")]
                            location = ", ".join(p for p in parts if p)
                        elif isinstance(addr, str):
                            location = addr

                organizer = None
                org_info = event_data.get("organizer")
                if isinstance(org_info, dict):
                    organizer = org_info.get("name")
                elif isinstance(org_info, str):
                    organizer = org_info

                description = event_data.get("description")

                events.append(Event(
                    title=title,
                    url=url,
                    source=self.name,
                    organizer=organizer,
                    prize="N/A",
                    registration_deadline=start_date,
                    start_date=start_date,
                    end_date=end_date,
                    location=location or ("Online" if is_online else "TBD"),
                    is_online=is_online,
                    description=description
                ))

        return events
