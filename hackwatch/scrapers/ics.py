"""Clubs' public calendars (iCalendar feeds, e.g. Google Calendar), listed in calendars.yaml.

No new dependency: only the parts of RFC 5545 that calendars in the wild use. Recurring
events: weekly rules (with UNTIL, COUNT, INTERVAL, EXDATE) are expanded, so hackwatch/series.py
can show them as one card; anything else lists its first date only.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

import requests
import yaml
from bs4 import BeautifulSoup

from hackwatch.filters import JORDAN_RE
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import DEFAULT_TZ, zone

ONLINE_RE = re.compile(r"\bonline\b|\bzoom\b|meet\.google|teams\.microsoft|https?://|عن بعد|عن بُعد", re.I)
GOOGLE_ICS_RE = re.compile(r"calendar\.google\.com/calendar/ical/([^/]+)/")
LINK_RE = re.compile(r"https?://[^\s<>\"')\]]+")
MAX_OCCURRENCES = 60


def validate_calendar(entry: dict) -> dict:
    """One calendars.yaml entry; raises ValueError with a readable message."""
    if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
        raise ValueError("a calendar needs a name")
    url = str(entry.get("url") or "").strip()
    if not url.startswith("https://"):
        raise ValueError(f"calendar {entry.get('name')!r}: the link must start with https://")
    unknown = set(entry) - {"name", "url", "city", "page"}
    if unknown:
        raise ValueError(f"calendar {entry['name']!r}: unknown key(s) {', '.join(sorted(unknown))}")
    return entry


def load_calendars(path: Path) -> List[dict]:
    if not Path(path).exists():
        return []
    return [validate_calendar(e) for e in yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []]


def parse_ics(text: str) -> List[Dict[str, Tuple[dict, str]]]:
    """VEVENTs as {PROPERTY: (params, value)}; EXDATE values are joined with commas."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text or "")
    events, current = [], None
    for line in unfolded.splitlines():
        if line.strip() == "BEGIN:VEVENT":
            current = {}
        elif line.strip() == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *raw = head.split(";")
            params = dict(p.split("=", 1) for p in raw if "=" in p)
            name = name.upper()
            if name == "EXDATE" and name in current:
                value = f"{current[name][1]},{value}"
            current[name] = (params, value)
    return events


def _text(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\")).strip()


def _moment(params: dict, value: str) -> Optional[Tuple[datetime, bool]]:
    """(local Amman datetime, is_all_day). Floating times are taken as Amman time."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=zone(DEFAULT_TZ)), True
        naive = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    if value.endswith("Z"):
        moment = naive.replace(tzinfo=timezone.utc)
    else:
        moment = naive.replace(tzinfo=zone(params.get("TZID") or DEFAULT_TZ))
    return moment.astimezone(zone(DEFAULT_TZ)), False


def _occurrences(start: datetime, rule: str, exdates: str, today: date, last: date) -> List[datetime]:
    """Start times in [today, last], expanding weekly rules."""
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    if parts.get("FREQ") != "WEEKLY" or "," in parts.get("BYDAY", ""):
        return [start] if today <= start.date() <= last else []
    until = re.match(r"\d{8}", parts.get("UNTIL", ""))
    end = min(last, datetime.strptime(until.group(0), "%Y%m%d").date()) if until else last
    count = int(parts["COUNT"]) if parts.get("COUNT", "").isdigit() else MAX_OCCURRENCES
    step = timedelta(weeks=int(parts["INTERVAL"]) if parts.get("INTERVAL", "").isdigit() else 1)
    skipped = set(re.findall(r"\d{8}", exdates or ""))
    out, moment = [], start
    for _ in range(min(count, MAX_OCCURRENCES)):
        if moment.date() > end:
            break
        if moment.date() >= today and moment.strftime("%Y%m%d") not in skipped:
            out.append(moment)
        moment += step
    return out


def _public_page(calendar: dict) -> str:
    """Where a card links when an event has no link of its own."""
    if calendar.get("page"):
        return calendar["page"]
    google = GOOGLE_ICS_RE.search(calendar["url"])
    if google:
        return f"https://calendar.google.com/calendar/embed?src={quote(unquote(google.group(1)))}"
    return calendar["url"]


def events_from_ics(text: str, calendar: dict, source: str, today: date, days_ahead: int = 120) -> List[Event]:
    last = today + timedelta(days=days_ahead)
    events = []
    for raw in parse_ics(text):
        if raw.get("STATUS", ({}, ""))[1].strip().upper() == "CANCELLED" or "DTSTART" not in raw or "SUMMARY" not in raw:
            continue
        begun = _moment(*raw["DTSTART"])
        if not begun:
            continue
        start, all_day = begun
        ended = _moment(*raw["DTEND"]) if "DTEND" in raw else None
        length = (ended[0] - start) if ended else timedelta(0)
        if all_day and length:
            length -= timedelta(days=1)   # all-day DTEND is exclusive
        rule = raw.get("RRULE", ({}, ""))[1]
        description = BeautifulSoup(_text(raw.get("DESCRIPTION", ({}, ""))[1]), "html.parser").get_text(" ")
        description = " ".join(description.split())[:600] or None
        where = _text(raw.get("LOCATION", ({}, ""))[1])
        online = bool(ONLINE_RE.search(where)) or (not where and not calendar.get("city")
                                                  and bool(ONLINE_RE.search(description or "")))
        if online:
            location = "Online"
        else:
            parts = [where] if where else []
            if not JORDAN_RE.search(where):
                parts += [calendar["city"]] if calendar.get("city") else []
                parts.append("Jordan")
            location = ", ".join(parts)
        link = _text(raw.get("URL", ({}, ""))[1])
        if not link.startswith(("http://", "https://")):
            found = LINK_RE.search(description or "")
            link = found.group(0) if found else ""
        uid = raw.get("UID", ({}, raw["SUMMARY"][1]))[1]
        for moment in _occurrences(start, rule, raw.get("EXDATE", ({}, ""))[1], today, last) if rule else (
                [start] if today <= (start + length).date() and start.date() <= last else []):
            finish = moment + length
            # A shared link would merge every event of the calendar: each needs its own URL.
            key = hashlib.sha256(f"{uid}{moment.date() if rule else ''}".encode()).hexdigest()[:12]
            url = link if link and not rule else f"{link or _public_page(calendar)}{'&' if '?' in (link or _public_page(calendar)) else '?'}event={key}"
            events.append(Event(
                title=" ".join(_text(raw["SUMMARY"][1]).split()),
                url=url,
                source=source,
                organizer=calendar["name"],
                start_date=moment.date().isoformat(),
                end_date=finish.date().isoformat(),
                start_time=None if all_day else moment.strftime("%H:%M"),
                end_time=None if all_day or not ended else finish.strftime("%H:%M"),
                location=location,
                mode="online" if online else "in-person",
                country=None if online else "JO",
                description=description,
            ))
    return events


@register("ics")
class IcsScraper(BaseScraper):
    def __init__(self, calendars_path: str = "calendars.yaml", days_ahead: int = 120, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.calendars_path = Path(calendars_path)
        self.days_ahead = days_ahead

    def fetch(self) -> List[Event]:
        calendars = load_calendars(self.calendars_path)
        events, failures = [], []
        for calendar in calendars:
            try:
                text = self.get(calendar["url"]).text
            except requests.RequestException as exc:
                failures.append(f"{calendar['name']}: {type(exc).__name__}")
                continue
            events += events_from_ics(text, calendar, self.name, date.today(), self.days_ahead)
        if calendars and len(failures) == len(calendars):
            raise RuntimeError("all calendars failed: " + "; ".join(failures))
        return events
