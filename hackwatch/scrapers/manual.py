import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple
import yaml

from hackwatch.models import Event, validate_event_type, validate_mode, validate_scope
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.taxonomy import normalize_tags

DEFAULT_MANUAL_YAML = Path("manual_events.yaml")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _NoDatesLoader(yaml.SafeLoader):
    """SafeLoader that leaves 2026-11-01 as a string.

    PyYAML's own date conversion crashes on values like 2026-02-30 with an error
    that doesn't say which entry is wrong; to_iso_date gives a clearer one.
    """


_NoDatesLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def to_iso_date(value, field: str) -> Optional[str]:
    """Return value as 'YYYY-MM-DD', or raise ValueError naming the field.

    YAML turns an unquoted 2026-11-01 into a date object, so both dates and
    ISO strings are accepted. Anything else (11/01/2026, "Nov 1") is rejected.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if ISO_DATE_RE.match(s):
        try:
            return date.fromisoformat(s).isoformat()
        except ValueError:
            pass  # e.g. 2026-02-30
    raise ValueError(f"{field} must be an ISO date like 2026-11-01, got {value!r}")


def parse_manual_dates(value) -> Tuple[Optional[str], Optional[str]]:
    """Parse the `dates` field: a single date, or "start to end" ("->" or " - " also work)."""
    if value is None or value == "":
        return None, None
    if isinstance(value, (date, datetime)):
        d = to_iso_date(value, "dates")
        return d, d
    parts = re.split(r"\s+(?:to|->|-)\s+", str(value).strip())
    if len(parts) == 2:
        return to_iso_date(parts[0], "dates (start)"), to_iso_date(parts[1], "dates (end)")
    d = to_iso_date(parts[0], "dates")
    return d, d


def parse_manual_item(item: dict) -> Event:
    """Turn one YAML entry into an Event, raising ValueError on bad fields."""
    title = item.get("title")
    url = item.get("url")
    if not title or not url:
        raise ValueError("title and url are required")

    start_date = to_iso_date(item.get("start_date"), "start_date")
    end_date = to_iso_date(item.get("end_date"), "end_date")
    if not start_date and not end_date:
        start_date, end_date = parse_manual_dates(item.get("dates"))
    if start_date and end_date and end_date < start_date:
        raise ValueError(f"end date {end_date} is before start date {start_date}")

    location = item.get("location")
    mode = validate_mode(item["mode"]) if item.get("mode") else None
    is_online = bool(item.get("is_online", False))
    if not mode and location and "online" in str(location).lower():
        is_online = True

    prize = item.get("prize") or "N/A"
    if prize == "$0":
        prize = "N/A"

    return Event(
        title=title,
        url=url,
        source=ManualScraper.name,
        organizer=item.get("organizer"),
        prize=prize,
        # Only set when given: an event's end is not its registration deadline.
        registration_deadline=to_iso_date(item.get("registration_deadline"), "registration_deadline"),
        start_date=start_date,
        end_date=end_date,
        location=location,
        is_online=is_online,
        mode=mode,
        tags=normalize_tags(item.get("tags"), strict=True),
        scope=validate_scope(item["scope"]) if item.get("scope") else None,
        description=item.get("description"),
        type=validate_event_type(item["type"], strict=True) if item.get("type") else None,
    )


def load_manual_yaml(path: Path):
    """Load the YAML file with dates left as strings (see _NoDatesLoader)."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=_NoDatesLoader)


def load_manual_events(path: Path) -> Tuple[List[Event], List[str]]:
    """Parse every entry, returning (valid events, error messages).

    Each error names the entry by position and title. A YAML syntax error
    raises, since then no entry can be trusted.
    """
    if not path.exists():
        return [], []
    data = load_manual_yaml(path)
    if not data:
        return [], []
    raw_events = data if isinstance(data, list) else data.get("events", [])

    events: List[Event] = []
    errors: List[str] = []
    seen_urls = {}
    for idx, item in enumerate(raw_events, 1):
        if not isinstance(item, dict):
            errors.append(f"entry #{idx}: expected a mapping, got {type(item).__name__}")
            continue
        label = f"entry #{idx} ({item.get('title') or 'untitled'})"
        try:
            event = parse_manual_item(item)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
            continue
        norm_url = event.url.strip().rstrip("/").lower()
        if norm_url in seen_urls:
            errors.append(f"{label}: duplicate url, same as entry #{seen_urls[norm_url]}")
            continue
        seen_urls[norm_url] = idx
        events.append(event)
    return events, errors


def report_error(path: Path, message: str) -> None:
    """Print loudly to stderr; on GitHub Actions also as an error annotation."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error file={path}::{message}", file=sys.stderr)
    else:
        print(f"ERROR {path}: {message}", file=sys.stderr)


@register("manual")
class ManualScraper(BaseScraper):
    def __init__(self, yaml_path: Path = DEFAULT_MANUAL_YAML):
        super().__init__(delay_seconds=0.0)
        self.yaml_path = Path(yaml_path)

    def fetch(self) -> List[Event]:
        """Import valid entries; invalid ones are skipped with an error each.

        One bad community submission must not hide every other manual event.
        `hackwatch.cli validate` is the strict check that fails on any error.
        """
        events, self.errors = load_manual_events(self.yaml_path)
        for message in self.errors:
            report_error(self.yaml_path, message)
        return events
