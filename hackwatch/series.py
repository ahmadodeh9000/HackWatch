"""Weekly series: one source listing the same event every week (GDG's "Flutter Bootcamp").

GDG on Campus PSUT listed its bootcamp ("three consecutive Saturdays, starting October 24th")
as three events, one per Saturday, 09:00–17:00 each, but gave every listing an end date two
weeks after its start (24 Oct → 7 Nov, 31 Oct → 14 Nov, 7 Nov → 21 Nov). The end date is the
organiser counting the whole run from that session, not how long the session lasts: the
series actually ends on 7 Nov. So:

- fix_session_ends(): in a series whose listings all overlap the next one, each listing is
  one session on its start date (used for every output: calendar, digest, share pages);
- merge_series(): for the site, the upcoming sessions become one record with `sessions`,
  `recurrence: weekly` and `series_until`; its dates are the next session's, so the
  countdown is to the next session.

A series = at least 2 listings from the same source with the same title (ignoring emoji,
case and spacing) and organiser, on different dates that are whole weeks apart.
"""
import re
from dataclasses import replace
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from hackwatch.models import Event

NOISE = re.compile(r"[^\w\s]+", re.U)


def _key(e: Event) -> Tuple[str, str, str]:
    title = " ".join(NOISE.sub(" ", e.title or "").lower().split())
    return (e.source or "", title, (e.organizer or "").strip().lower())


def _day(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def find_series(events: Iterable[Event]) -> List[List[Event]]:
    """Groups of listings that form a weekly series, each sorted by start date."""
    groups: Dict[tuple, List[Event]] = {}
    for e in events:
        if _day(e.start_date):
            groups.setdefault(_key(e), []).append(e)
    series = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda e: e.start_date)
        starts = [_day(e.start_date) for e in members]
        gaps = [(b - a).days for a, b in zip(starts, starts[1:])]
        if all(g > 0 and g % 7 == 0 for g in gaps):
            series.append(members)
    return series


def fix_session_ends(events: List[Event]) -> List[Event]:
    """Copies of `events` where series listings that run into the next session are one day."""
    fixed = {}
    for members in find_series(events):
        starts = [_day(e.start_date) for e in members]
        ends = [_day(e.end_date) or s for e, s in zip(members, starts)]
        # Every listing but the last runs into the next session: they're sessions, not spans.
        if all(end >= nxt for end, nxt in zip(ends, starts[1:])):
            for e in members:
                fixed[id(e)] = replace(e, end_date=e.start_date)
    return [fixed.get(id(e), e) for e in events]


def merge_series(events: List[Event], today: Optional[date] = None) -> List[dict]:
    """[{"event": Event, "sessions": [...], "until": "YYYY-MM-DD"}] with series merged.

    Sessions before today are dropped; a series with one session left is a normal event.
    `events` should already have gone through fix_session_ends.
    """
    today = today or date.today()
    in_series = {}
    for members in find_series(events):
        upcoming = [e for e in members if (_day(e.end_date) or _day(e.start_date)) >= today]
        for e in members:
            in_series[id(e)] = upcoming
    out, done = [], set()
    for e in events:
        upcoming = in_series.get(id(e))
        if upcoming is None:
            out.append({"event": e, "sessions": None, "until": None})
            continue
        if e not in upcoming or id(upcoming[0]) in done:
            continue
        done.add(id(upcoming[0]))
        if len(upcoming) == 1:
            out.append({"event": upcoming[0], "sessions": None, "until": None})
            continue
        out.append({"event": upcoming[0], "members": upcoming,
                    "sessions": [{"date": s.start_date, "url": s.url, "id": s.id} for s in upcoming],
                    "until": upcoming[-1].start_date})
    return out
