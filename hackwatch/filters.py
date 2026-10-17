import re
from datetime import date, timedelta

HACK_RE = re.compile(r"hack|datathon|ideathon|buildathon|challenge|competition|game jam|codefest", re.I)
BROAD_SOURCES = {"gdg", "eventbrite"}
MAX_DAYS_AHEAD = 365


def _parse(d):
    try:
        return date.fromisoformat(d[:10]) if d else None
    except ValueError:
        return None


def is_relevant(event) -> bool:
    if event.source == "manual":
        return True
    if "tbd" in (event.title or "").lower():
        return False
    start = _parse(event.start_date)
    if start and start > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        return False
    if event.source in BROAD_SOURCES:
        return bool(HACK_RE.search(f"{event.title or ''} {event.description or ''}"))
    return True
