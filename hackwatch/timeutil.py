"""Turn source timestamps into the local calendar date people will see."""
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

DEFAULT_TZ = "Asia/Amman"


def zone(name: Optional[str]):
    """A tzinfo for `name`, falling back to Amman, then UTC."""
    for candidate in (name, DEFAULT_TZ):
        if candidate and ZoneInfo:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return timezone.utc


def _moment(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_time(value: Union[str, int, float, None], tz: Optional[str] = DEFAULT_TZ) -> Optional[str]:
    """Like local_date, but the 'HH:MM' clock time (24 h) in time zone `tz`."""
    moment = _moment(value)
    return moment.astimezone(zone(tz)).strftime("%H:%M") if moment else None


def local_date(value: Union[str, int, float, None], tz: Optional[str] = DEFAULT_TZ) -> Optional[str]:
    """'2026-10-27T22:30:00+00:00' or a Unix timestamp -> 'YYYY-MM-DD' in time zone `tz`.

    A CTF starting 22:30 UTC on the 27th starts on the 28th in Amman.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone(tz)).date().isoformat()


def deadline_date(value: Union[str, int, float, None], tz: Optional[str] = DEFAULT_TZ) -> Optional[str]:
    """Like local_date, for a registration end: exactly midnight means 'end of the day before'.

    vTools stores "registration closes 20 Oct" as 2026-10-20T21:00Z, which is 00:00 on
    the 21st in Amman; people read that as the 20th.
    """
    moment = _moment(value)
    if not moment:
        return None
    local = moment.astimezone(zone(tz))
    if (local.hour, local.minute, local.second) == (0, 0, 0):
        local -= timedelta(days=1)
    return local.date().isoformat()
