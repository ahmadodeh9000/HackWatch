from datetime import datetime, timedelta, timezone
from typing import List

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date


@register("ctftime")
class CTFtimeScraper(BaseScraper):
    """Upcoming CTFs from the public CTFtime API (https://ctftime.org/api/)."""

    api_url = "https://ctftime.org/api/v1/events/"

    def __init__(self, days_ahead: int = 60, limit: int = 100, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.days_ahead = days_ahead
        self.limit = limit

    def fetch(self) -> List[Event]:
        # Window starts at today's midnight UTC so the request URL is the same all day.
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        finish = start + timedelta(days=self.days_ahead)
        resp = self.get(self.api_url, params={
            "limit": self.limit, "start": int(start.timestamp()), "finish": int(finish.timestamp()),
        })
        events = []
        for item in resp.json():
            title, url = item.get("title"), item.get("ctftime_url") or item.get("url")
            if not title or not url:
                continue
            onsite = bool(item.get("onsite"))
            details = [item.get("format"), item.get("restrictions")]
            summary = " · ".join(d for d in details if d)
            text = " ".join((item.get("description") or "").split())
            description = f"{summary} CTF. {text}"[:600] if summary else text[:600]
            prize = " ".join((item.get("prizes") or "").split())[:120] or "N/A"
            events.append(Event(
                title=title,
                url=url,
                source=self.name,
                organizer=", ".join(o["name"] for o in item.get("organizers") or [] if o.get("name")) or None,
                prize=prize,
                start_date=local_date(item.get("start")),
                end_date=local_date(item.get("finish")),
                mode="in-person" if onsite else "online",
                location=(item.get("location") or None) if onsite else "Online",
                description=description,
            ))
        return events
