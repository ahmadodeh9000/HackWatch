from datetime import datetime
from typing import List, Optional
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_time

GDG_AUDIENCE_MODES = {"IN_PERSON": "in-person", "VIRTUAL": "online", "HYBRID": "hybrid"}


@register("gdg")
class GDGScraper(BaseScraper):
    def __init__(
        self,
        api_url: Optional[str] = None,
        chapter_ids: Optional[List[int]] = None,
        delay_seconds: float = 2.0,
    ):
        super().__init__(delay_seconds=delay_seconds)
        self.api_url = api_url
        if not api_url and not chapter_ids:
            raise ValueError("gdg needs chapter_ids (or api_url)")
        self.chapter_ids = chapter_ids or []

    def fetch(self) -> List[Event]:
        events: List[Event] = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        if self.api_url:
            return self._fetch_url(self.api_url)

        seen_urls = set()
        for cid in self.chapter_ids:
            try:
                resp = self.get(f"https://gdg.community.dev/api/event/?chapter={cid}")
                data = resp.json()
                results = data.get("results", [])
            except Exception:
                continue

            for item in results:
                url = item.get("url")
                if not url or url in seen_urls:
                    continue

                start_raw = item.get("start_date")
                start_date = str(start_raw)[:10] if start_raw else None
                if start_date and start_date < today_str:
                    continue

                event_id = item.get("id")
                detail = {}
                if event_id:
                    try:
                        det_resp = self.get(f"https://gdg.community.dev/api/event/{event_id}/")
                        detail = det_resp.json()
                    except Exception:
                        pass

                title = detail.get("title") or item.get("title")
                if not title:
                    continue

                seen_urls.add(url)
                end_raw = detail.get("end_date") or item.get("end_date")
                end_date = str(end_raw)[:10] if end_raw else None

                chapter = detail.get("chapter", {}) if isinstance(detail.get("chapter"), dict) else {}
                organizer = chapter.get("title") or "Google Developer Groups"

                venue = detail.get("venue_name")
                city = detail.get("venue_city") or detail.get("city_name") or chapter.get("city") or "Amman"
                country = detail.get("country_name") or chapter.get("country_name") or "Jordan"
                loc_parts = [p for p in (venue, city, country) if p]
                location = ", ".join(loc_parts) if loc_parts else "Amman, Jordan"

                title_lower = title.lower()
                is_online = (
                    bool(detail.get("is_virtual_event"))
                    or detail.get("live_url") is not None
                    or "virtual" in title_lower
                    or "online" in title_lower
                )
                # audience_type is GDG's own mode field; older events only had the flags above.
                mode = GDG_AUDIENCE_MODES.get(str(detail.get("audience_type") or "").upper())
                if mode:
                    is_online = mode != "in-person"
                if is_online and not venue:
                    location = "Online"

                desc = detail.get("description_short") or detail.get("description") or item.get("description_short") or ""

                events.append(
                    Event(
                        title=title,
                        url=url,
                        source=self.name,
                        organizer=organizer,
                        prize="N/A",
                        # GDG doesn't publish a registration deadline.
                        start_date=start_date,
                        end_date=end_date,
                        start_time=local_time(detail.get("start_date") or start_raw),
                        end_time=local_time(end_raw),
                        location=location or "Online",
                        is_online=is_online,
                        mode=mode,
                        description=desc,
                        country="JO",
                        source_labels=[str(t) for t in detail.get("tags") or []],
                    )
                )

        return events

    def _fetch_url(self, url: str) -> List[Event]:
        resp = self.get(url)
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

            chapter = item.get("chapter", {}) if isinstance(item.get("chapter"), dict) else {}
            organizer = chapter.get("title") or "Google Developer Groups"

            city = item.get("city_name") or chapter.get("city")
            country = item.get("country_name") or chapter.get("country_name")
            location_parts = [p for p in (city, country) if p]
            location = ", ".join(location_parts) if location_parts else chapter.get("chapter_location")

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
                start_date=start_date,
                end_date=end_date,
                start_time=local_time(start_raw),
                end_time=local_time(end_raw),
                location=location or "Online",
                is_online=is_online,
                description=desc,
                country="JO",
            ))

        return events
