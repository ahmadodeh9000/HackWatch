"""Turn source timestamps into the local calendar date people will see."""
from datetime import datetime, timezone
from typing import Optional, Union

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

DEFAULT_TZ = "Asia/Amman"


def _zone(name: Optional[str]):
    for candidate in (name, DEFAULT_TZ):
        if candidate and ZoneInfo:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return timezone.utc


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
    return moment.astimezone(_zone(tz)).date().isoformat()
