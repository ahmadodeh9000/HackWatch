"""Write events as an iCalendar (RFC 5545) feed people can subscribe to."""
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional

from hackwatch.models import Event
from hackwatch.tidy import deadline_phrase, shown_organizer, shown_title
from hackwatch.timeutil import DEFAULT_TZ, zone

PRODID = "-//HackWatch//Jordan tech events//EN"
UID_DOMAIN = "hackwatch.ahmadodeh9000.github.io"


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines (RFC 5545 §3.3.11)."""
    return (str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line: str) -> str:
    """Split a content line into chunks of at most 75 octets (not characters: Arabic
    letters are 2 bytes in UTF-8), continuing with CRLF + a space (§3.1)."""
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not out else 74  # continuation lines start with a space
        if size + n > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += n
    out.append(current)
    return "\r\n ".join(out)


def _ics_date(d: str) -> str:
    return date.fromisoformat(d[:10]).strftime("%Y%m%d")


def _stamp(event: Event) -> str:
    """DTSTAMP from when we last saw the event, so the feed doesn't change every run."""
    for value in (event.updated_at, event.created_at):
        if value:
            try:
                moment = datetime.fromisoformat(str(value).replace(" ", "T"))
                return moment.strftime("%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
    return "20260101T000000Z"


DEFAULT_TIMED_HOURS = 2


def _utc_stamp(day: date, clock: str) -> datetime:
    hour, minute = (int(x) for x in clock.split(":"))
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone(DEFAULT_TZ))
    return local.astimezone(timezone.utc)


def _when_lines(event: Event, start: date, end: date) -> List[str]:
    """DTSTART/DTEND: timed (UTC) when a start time is known, otherwise all-day."""
    if event.start_time:
        begins = _utc_stamp(start, event.start_time)
        ends = _utc_stamp(end, event.end_time) if event.end_time else begins + timedelta(hours=DEFAULT_TIMED_HOURS)
        if ends <= begins:
            ends = begins + timedelta(hours=DEFAULT_TIMED_HOURS)
        return [f"DTSTART:{begins.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{ends.strftime('%Y%m%dT%H%M%SZ')}"]
    return [
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        # All-day events: DTEND is the day *after* the last day (exclusive).
        f"DTEND;VALUE=DATE:{(end + timedelta(days=1)).strftime('%Y%m%d')}",
    ]


def event_lines(event: Event) -> List[str]:
    start = date.fromisoformat(event.start_date[:10])
    end = date.fromisoformat((event.end_date or event.start_date)[:10])
    if end < start:
        end = start
    details = [event.description or ""]
    if event.registration_deadline:
        details.append(f"{deadline_phrase(event)}: {event.registration_deadline}")
    if event.organizer:
        details.append(f"Organizer: {shown_organizer(event)}")
    if event.prize and event.prize != "N/A":
        details.append(f"Prize: {event.prize}")
    details.append(f"Type: {event.type or 'other'} · {event.mode}")
    details.append(f"More: {event.url}")
    location = "Online" if event.mode == "online" else (event.location or "")
    if event.mode == "hybrid":
        location += " (also online)"
    categories = [event.type or "other"] + list(event.tags)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.id}@{UID_DOMAIN}",
        f"DTSTAMP:{_stamp(event)}",
        *_when_lines(event, start, end),
        f"SUMMARY:{escape_text(shown_title(event))}",
        f"DESCRIPTION:{escape_text(chr(10).join(d for d in details if d))}",
        f"URL:{event.url}",
    ]
    if location:
        lines.append(f"LOCATION:{escape_text(location)}")
    lines.append("CATEGORIES:" + ",".join(escape_text(c) for c in categories))
    lines.append("TRANSP:TRANSPARENT")  # all-day listings shouldn't block people's time
    lines.append("END:VEVENT")
    return lines


def build_calendar(events: Iterable[Event], name: Optional[str] = "HackWatch: Jordan tech events") -> str:
    """The subscribable feed, or with name=None a one-off file to import (no refresh, no calendar name)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    if name:
        lines += [
            f"X-WR-CALNAME:{escape_text(name)}",
            "X-WR-TIMEZONE:Asia/Amman",
            "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
            "X-PUBLISHED-TTL:PT12H",
        ]
    for event in sorted(events, key=lambda e: (e.start_date or "", e.title)):
        if event.start_date:
            lines.extend(event_lines(event))
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)


def calendar_events(events: Iterable[Event], scope: Optional[str] = "jordan",
                    keep_days_after_end: int = 30, today: Optional[date] = None) -> List[Event]:
    """Events for the feed: in `scope`, with a date, not ended more than N days ago.

    Keeping recently ended events stops calendar apps from deleting an event
    the day after it finishes.
    """
    cutoff = (today or date.today()) - timedelta(days=keep_days_after_end)
    chosen = []
    for e in events:
        if scope and e.scope != scope or not e.start_date:
            continue
        if e.low_signal:  # club-life events stay off the feed, as on the site by default
            continue
        last = date.fromisoformat((e.end_date or e.start_date)[:10])
        if last >= cutoff:
            chosen.append(e)
    return chosen
