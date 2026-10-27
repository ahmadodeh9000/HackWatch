"""Keep a source's last known events when it suddenly returns nothing.

In CI every run starts with an empty database, so if IEEE or Eventbrite errors
(or comes back empty) for a day, their events would vanish from the site. This
copies such a source's events back from the currently deployed events.json and
marks them stale, so the site can say they weren't re-checked today.
"""
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import requests

from hackwatch import db
from hackwatch.models import Event
from hackwatch.scrapers.base import DEFAULT_USER_AGENT

MIN_PREVIOUS_EVENTS = 3
# A source down this long loses its kept events: they may well be cancelled or moved.
STALE_MAX_DAYS = 7
RECORD_FIELDS = ("title", "url", "source", "organizer", "prize", "registration_deadline", "start_date",
                 "end_date", "start_time", "end_time", "location", "mode", "description", "type", "tags", "scope")


def load_json(location: str):
    """JSON from a URL or a local path; None if it can't be read."""
    try:
        if location.startswith(("http://", "https://")):
            resp = requests.get(location, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        return json.loads(Path(location).read_text(encoding="utf-8"))
    except (requests.RequestException, OSError, ValueError):
        return None


def load_previous(location: str) -> Optional[List[dict]]:
    """The previous export (a list of events) from a URL or a local path; None if unreadable."""
    data = load_json(location)
    return data if isinstance(data, list) else None


def _still_upcoming(record: dict, today: date) -> bool:
    last = record.get("end_date") or record.get("start_date")
    try:
        return last is None or date.fromisoformat(str(last)[:10]) >= today
    except ValueError:
        return False


def _expired(record: dict, today: date, max_days: int) -> bool:
    since = record.get("stale_since")
    try:
        return bool(since) and (today - date.fromisoformat(str(since)[:10])).days > max_days
    except ValueError:
        return False


def carry_over(conn, previous: List[dict], sources: List[str],
               min_events: int = MIN_PREVIOUS_EVENTS, today: Optional[date] = None,
               max_stale_days: int = STALE_MAX_DAYS) -> Dict[str, int]:
    """Restore events of configured sources that have 0 events now but had >= min_events before.

    Counts use each event's primary `source`. Each restored event keeps the date it
    first went stale (stale_since); after max_stale_days it is no longer restored.
    Returns {source: events restored}.
    """
    today = today or date.today()
    by_source: Dict[str, List[dict]] = {}
    for record in previous:
        by_source.setdefault(record.get("source"), []).append(record)

    restored: Dict[str, int] = {}
    for source in sources:
        old = by_source.get(source, [])
        if len(old) < min_events or db.count_observations(conn, source) > 0:
            continue
        events = []
        for record in old:
            if not _still_upcoming(record, today) or _expired(record, today, max_stale_days):
                continue
            fields = {k: record.get(k) for k in RECORD_FIELDS if record.get(k) is not None}
            since = record.get("stale_since") if record.get("stale") else None
            events.append(Event(**fields, stale=True, stale_since=since or today.isoformat()))
        with conn:
            for event in events:
                db.write_observation(conn, event, run_id=None)
        restored[source] = len(events)
    if restored:
        db.rebuild_events(conn)
    return restored
