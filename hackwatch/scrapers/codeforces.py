import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date, local_time

# Regular rated rounds; skips sponsored/special contests (Kotlin Heroes, ICPC challenges...).
DEFAULT_INCLUDE = [r"\bDiv\. ?[123]\b", r"^Educational Codeforces Round"]


@register("codeforces")
class CodeforcesScraper(BaseScraper):
    """Upcoming contests from the Codeforces API (https://codeforces.com/apiHelp)."""

    api_url = "https://codeforces.com/api/contest.list"

    def __init__(self, days_ahead: int = 30, include: Optional[List[str]] = None, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.days_ahead = days_ahead
        self.include = [re.compile(p) for p in (include if include is not None else DEFAULT_INCLUDE)]

    def fetch(self) -> List[Event]:
        data = self.get(self.api_url, params={"gym": "false"}).json()
        if data.get("status") != "OK":
            raise RuntimeError(f"Codeforces API: {data.get('comment') or data.get('status')}")
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=self.days_ahead)
        events = []
        for contest in data.get("result", []):
            name, start = contest.get("name") or "", contest.get("startTimeSeconds")
            if contest.get("phase") != "BEFORE" or not start:
                continue
            if not (now.timestamp() <= start <= until.timestamp()):
                continue
            if self.include and not any(p.search(name) for p in self.include):
                continue
            duration = int(contest.get("durationSeconds") or 0)
            hours, minutes = divmod(duration // 60, 60)
            events.append(Event(
                title=name,
                url=f"https://codeforces.com/contests/{contest['id']}",
                source=self.name,
                organizer="Codeforces",
                prize="N/A",
                start_date=local_date(start),
                end_date=local_date(start + duration),
                start_time=local_time(start),
                end_time=local_time(start + duration),
                mode="online",
                location="Online",
                description=f"{hours}h {minutes:02d}m Codeforces contest ({contest.get('type')} rules).",
            ))
        return events
