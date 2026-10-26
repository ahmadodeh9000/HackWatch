import json
from typing import List, Optional
from urllib.parse import urlparse, urlunparse
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


# Jordan only. Worldwide online events come from purpose-built feeds (Devpost,
# CTFtime, Codeforces): Eventbrite's online search is mostly generic webinars.
# Results are de-duplicated by URL and filters.is_tech_related drops non-tech
# events. (As of 2026-10 Eventbrite returns the same ~10 Jordan events for any
# term, and /d/jordan/all-events/ returns fewer, so the term pages are the
# safest way to get everything.)
SEARCH_TERMS = [
    "hackathon", "tech", "ai", "programming", "robotics",
    "cybersecurity", "data-science", "developer",
]
DEFAULT_SEARCH_URLS = [f"https://www.eventbrite.com/d/jordan/{term}/" for term in SEARCH_TERMS]


def clean_eventbrite_url(url: str) -> str:
    """Strip tracking query parameters from Eventbrite URLs."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


class EventbriteScraper(BaseScraper):
    name: str = "eventbrite"

    def __init__(
        self,
        search_url: Optional[str] = None,
        search_urls: Optional[List[str]] = None,
        delay_seconds: float = 2.0,
    ):
        super().__init__(delay_seconds=delay_seconds)
        if search_urls:
            self.search_urls = search_urls
        elif search_url:
            self.search_urls = [search_url]
        else:
            self.search_urls = list(DEFAULT_SEARCH_URLS)
        self.search_url = self.search_urls[0]

    def fetch(self) -> List[Event]:
        events: List[Event] = []
        seen_urls = set()

        for search_url in self.search_urls:
            try:
                resp = self.get(search_url)
                soup = BeautifulSoup(resp.text, "html.parser")
            except Exception:
                continue

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
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    start_raw = event_data.get("startDate")
                    end_raw = event_data.get("endDate")
                    start_date = str(start_raw)[:10] if start_raw else None
                    end_date = str(end_raw)[:10] if end_raw else None

                    attendance_mode = str(event_data.get("eventAttendanceMode", ""))
                    is_online = "OnlineEventAttendanceMode" in attendance_mode
                    mode = "hybrid" if "MixedEventAttendanceMode" in attendance_mode else None

                    loc_info = event_data.get("location")
                    location = "Online" if is_online else None
                    country = None

                    if isinstance(loc_info, dict):
                        if loc_info.get("@type") == "VirtualLocation":
                            is_online = True
                            location = "Online"
                        else:
                            venue = loc_info.get("name")
                            addr = loc_info.get("address")
                            city = None
                            c_code = None
                            if isinstance(addr, dict):
                                city = addr.get("addressLocality") or addr.get("addressRegion")
                                c_code = addr.get("addressCountry")
                            elif isinstance(addr, str):
                                city = addr

                            c_display = "Jordan" if (c_code == "JO" or "jordan" in search_url) else c_code
                            if c_code:
                                country = c_code
                            elif "jordan" in search_url:
                                country = "JO"

                            parts = [p for p in (venue, city, c_display) if p]
                            # Never keep only the venue name
                            if len(parts) == 1 and venue:
                                parts.append("Jordan" if country == "JO" else "Unknown")
                            location = ", ".join(parts) if parts else ("Online" if is_online else "TBD")

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
                        mode=mode,
                        description=description,
                        country=country,
                    ))

        return events
