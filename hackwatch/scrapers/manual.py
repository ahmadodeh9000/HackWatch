import re
from pathlib import Path
from typing import List, Optional, Tuple
import yaml

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper

DEFAULT_MANUAL_YAML = Path("manual_events.yaml")


def parse_manual_dates(date_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not date_str:
        return None, None
    s = date_str.strip()
    # Support "start to end", "start -> end", "start - end"
    split_pattern = r"\s+(?:to|->|-)\s+"
    parts = re.split(split_pattern, s)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return s, s


class ManualScraper(BaseScraper):
    name: str = "manual"

    def __init__(self, yaml_path: Path = DEFAULT_MANUAL_YAML):
        super().__init__(delay_seconds=0.0)
        self.yaml_path = yaml_path

    def fetch(self) -> List[Event]:
        if not self.yaml_path.exists():
            return []

        with open(self.yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data:
            return []

        raw_events = data if isinstance(data, list) else data.get("events", [])
        events: List[Event] = []

        for item in raw_events:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            url = item.get("url")
            if not title or not url:
                continue

            dates_val = item.get("dates")
            start_date = item.get("start_date")
            end_date = item.get("end_date")
            if not start_date and not end_date and dates_val:
                start_date, end_date = parse_manual_dates(str(dates_val))

            location = item.get("location")
            is_online = bool(item.get("is_online", False))
            if location and "online" in str(location).lower():
                is_online = True

            prize = item.get("prize") or "N/A"
            if prize == "$0":
                prize = "N/A"

            events.append(Event(
                title=title,
                url=url,
                source=self.name,
                organizer=item.get("organizer"),
                prize=prize,
                registration_deadline=item.get("registration_deadline") or end_date,
                start_date=start_date,
                end_date=end_date,
                location=location,
                is_online=is_online,
                description=item.get("description")
            ))

        return events
