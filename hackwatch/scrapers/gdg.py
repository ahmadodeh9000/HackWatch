from typing import List, Optional
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


class GDGScraper(BaseScraper):
    name: str = "gdg"

    def __init__(self, api_url: str = "https://gdg.community.dev/api/event/?page_size=30", delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.api_url = api_url

    def fetch(self) -> List[Event]:
        resp = self.get(self.api_url)
        data = resp.json()
        results = data.get("results", [])
        events: List[Event] = []

        for item in results:
            title = item.get("title")
            url = item.get("url")
            if not title or not url:
                continue

            start_raw = item.get("start_date")
            end_raw = item.get("end_date")
            start_date = str(start_raw)[:10] if start_raw else None
            end_date = str(end_raw)[:10] if end_raw else None

            # Chapter / Organizer
            chapter = item.get("chapter", {}) if isinstance(item.get("chapter"), dict) else {}
            organizer = chapter.get("title") or "Google Developer Groups"

            # Location
            city = item.get("city_name") or chapter.get("city")
            country = item.get("country_name") or chapter.get("country_name")
            location_parts = [p for p in (city, country) if p]
            location = ", ".join(location_parts) if location_parts else chapter.get("chapter_location")

            # Online check
            title_lower = title.lower()
            is_online = "virtual" in title_lower or "online" in title_lower or not location
            if is_online and not location:
                location = "Online"

            desc = item.get("description_short") or item.get("event_type_title")

            events.append(Event(
                title=title,
                url=url,
                source=self.name,
                organizer=organizer,
                prize="N/A",
                registration_deadline=start_date,
                start_date=start_date,
                end_date=end_date,
                location=location or "Online",
                is_online=is_online,
                description=desc
            ))

        return events
