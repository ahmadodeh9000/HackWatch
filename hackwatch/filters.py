import re
from datetime import date, timedelta

JORDAN_RE = re.compile(r"\b(jordan|amman|irbid|aqaba|zarqa|madaba|jerash|karak)\b", re.I)
HACK_RE = re.compile(r"hack|datathon|ideathon|buildathon|challenge|competition|game jam|codefest", re.I)
BROAD_SOURCES = {"gdg", "eventbrite"}
MAX_DAYS_AHEAD = 365


def _parse(d):
    try:
        return date.fromisoformat(d[:10]) if d else None
    except ValueError:
        return None


def is_in_jordan(event) -> bool:
    country = (event.country or "").upper()
    if country:  # a detected country always wins ("Jordan, MN, US" is not Jordan)
        return country == "JO"
    return bool(JORDAN_RE.search(event.location or ""))


def is_relevant(event) -> bool:
    """Online events from anywhere are kept; in-person events only if they are in Jordan."""
    if event.source == "manual":
        return True
    if "tbd" in (event.title or "").lower():
        return False
    start = _parse(event.start_date)
    if start and start > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        return False
    if not event.is_online and not is_in_jordan(event):
        return False
    if event.source in BROAD_SOURCES:
        return bool(HACK_RE.search(f"{event.title or ''} {event.description or ''}"))
    return True
