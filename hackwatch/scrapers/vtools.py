from typing import List

import requests
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date

LOCATION_MODES = {"physical": "in-person", "virtual": "online", "hybrid": "hybrid"}


def html_to_text(html: str, limit: int = 600) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())[:limit]


@register("vtools")
class VToolsScraper(BaseScraper):
    """IEEE events from the public vTools Events API, kept only for the given sections.

    The public API can't filter by section (per-section feeds need a request to
    IEEE staff), so this pages through all upcoming events worldwide and keeps
    those hosted or co-hosted by `section_spoids` (Jordan Section = R80079).
    """

    api_url = "https://events.vtools.ieee.org/RST/events/api/public/v8/events/list"

    def __init__(self, section_spoids: List[str], days_ahead: int = 60, page_size: int = 100,
                 max_pages: int = 20, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        if not section_spoids:
            raise ValueError("vtools needs section_spoids (e.g. [R80079] for the Jordan Section)")
        self.section_spoids = set(section_spoids)
        self.days_ahead = days_ahead
        self.page_size = page_size
        self.max_pages = max_pages

    def _page(self, page: int) -> dict:
        params = {"span": f"now~now+{self.days_ahead}", "limit": self.page_size, "page": page}
        try:
            return self.get(self.api_url, params=params).json()
        except requests.Timeout:
            return self.get(self.api_url, params=params).json()  # the API is slow at times; retry once

    def _in_sections(self, attrs: dict) -> bool:
        hosts = [attrs.get("primary-host") or {}] + list(attrs.get("cohosts") or [])
        for host in hosts:
            spoids = str(host.get("section_spoids") or "").replace(";", ",").split(",")
            if self.section_spoids & {s.strip() for s in spoids}:
                return True
        return False

    def fetch(self) -> List[Event]:
        events = []
        page, total_pages = 1, 1
        while page <= min(total_pages, self.max_pages):
            data = self._page(page)
            total_pages = int(((data.get("meta") or {}).get("paging") or {}).get("total_pages") or 1)
            for item in data.get("data") or []:
                attrs = item.get("attributes") or {}
                if not attrs.get("title") or not self._in_sections(attrs):
                    continue
                tz = (attrs.get("time-zone") or {}).get("name")
                mode = LOCATION_MODES.get(str(attrs.get("location-type") or "").lower(), "in-person")
                # City names are typed freely ("amman", "Az Zarqa"); capitalise all-lowercase ones.
                place = [p.strip() for p in (attrs.get("building"), attrs.get("city")) if p and p.strip()]
                place = [p.title() if p.islower() else p for p in place]
                location = "Online" if mode == "online" else ", ".join(place + ["Jordan"])
                host = attrs.get("primary-host") or {}
                events.append(Event(
                    title=" ".join(attrs["title"].split()),
                    url=f"https://events.vtools.ieee.org/m/{attrs.get('id') or item.get('id')}",
                    source=self.name,
                    organizer=host.get("name"),
                    prize="N/A",
                    registration_deadline=local_date(attrs.get("registration-end-time"), tz),
                    start_date=local_date(attrs.get("start-time"), tz),
                    end_date=local_date(attrs.get("end-time"), tz),
                    mode=mode,
                    location=location,
                    country="JO",
                    description=html_to_text(attrs.get("description")),
                    source_labels=[str(t).lstrip("#") for t in attrs.get("tags") or []],
                ))
            page += 1
        return events
