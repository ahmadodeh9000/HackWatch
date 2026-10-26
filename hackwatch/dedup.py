"""Find the same event listed by several sources and merge it into one.

Two listings are the same event when
  - their URLs normalise to the same key (hackwatch.urls.normalize_url), or
  - they come from different sources, start within ±1 day of each other, and
    their normalised titles are similar (difflib ratio >= TITLE_SIMILARITY).

The merged event takes each field from the highest-precedence listing that has
it: manual > Jordan sources > worldwide feeds.
"""
import re
import unicodedata
from dataclasses import replace
from datetime import date
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from hackwatch.models import Event
from hackwatch.urls import normalize_url

TITLE_SIMILARITY = 0.85
MAX_START_DAYS_APART = 1
# Words that say nothing about which event it is.
TITLE_NOISE = re.compile(r"\b(19|20)\d{2}\b|\b(the|a|an|of|in|at|for|and|by)\b")


def normalize_title(title: str) -> str:
    """Lower-case, letters/digits only (Arabic kept), diacritics, years and filler words dropped."""
    t = unicodedata.normalize("NFKD", title or "").lower()
    t = "".join(c for c in t if not unicodedata.category(c).startswith("M"))  # accents, Arabic diacritics
    t = re.sub(r"[^\w\s]", " ", t)          # punctuation, emoji
    t = TITLE_NOISE.sub(" ", t)
    return " ".join(t.split())


def _parse(d: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(d[:10]) if d else None
    except ValueError:
        return None


def rank(event: Event) -> int:
    """Lower is more trusted: manual (0) > Jordan sources (1) > worldwide feeds (2)."""
    if event.source == "manual":
        return 0
    return 1 if event.scope == "jordan" else 2


def same_event(a: Event, b: Event) -> bool:
    if normalize_url(a.url) == normalize_url(b.url):
        return True
    if a.source == b.source:
        return False  # one source listing two similar titles = two sessions, not a duplicate
    da, db_ = _parse(a.start_date), _parse(b.start_date)
    if not da or not db_ or abs((da - db_).days) > MAX_START_DAYS_APART:
        return False
    ta, tb = normalize_title(a.title), normalize_title(b.title)
    return bool(ta and tb) and SequenceMatcher(None, ta, tb).ratio() >= TITLE_SIMILARITY


def group_duplicates(events: List[Event]) -> List[List[Event]]:
    """Partition events into groups of the same real-world event (union-find)."""
    parent = list(range(len(events)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_url: Dict[str, int] = {}
    for i, ev in enumerate(events):
        key = normalize_url(ev.url)
        if key in by_url:
            parent[find(i)] = find(by_url[key])
        else:
            by_url[key] = i
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            if find(i) != find(j) and same_event(events[i], events[j]):
                parent[find(j)] = find(i)

    groups: Dict[int, List[Event]] = {}
    for i, ev in enumerate(events):
        groups.setdefault(find(i), []).append(ev)
    return list(groups.values())


MERGED_FIELDS = ("organizer", "prize", "registration_deadline", "start_date", "end_date",
                 "location", "country", "description")


def merge(group: List[Event]) -> Event:
    """One event from a group of listings; see the module docstring for precedence."""
    ordered = sorted(group, key=lambda e: (rank(e), e.first_seen_run_id or 0, e.source))
    primary = ordered[0]
    merged = replace(primary, tags=list(primary.tags))
    for name in MERGED_FIELDS:
        if not getattr(merged, name) or getattr(merged, name) == "N/A":
            for other in ordered[1:]:
                value = getattr(other, name)
                if value and value != "N/A":
                    setattr(merged, name, value)
                    break
    if merged.type in (None, "other"):
        merged.type = next((e.type for e in ordered if e.type not in (None, "other")), merged.type)
    for e in ordered[1:]:
        merged.tags += [t for t in e.tags if t not in merged.tags]
    merged.stale = all(e.stale for e in ordered)  # one fresh listing is enough
    merged.sources = list(dict.fromkeys(e.source for e in ordered))
    merged.urls = list(dict.fromkeys(e.url for e in ordered))
    seen_runs = [e.first_seen_run_id for e in ordered if e.first_seen_run_id is not None]
    merged.first_seen_run_id = min(seen_runs) if seen_runs else None
    created = [e.created_at for e in ordered if e.created_at]
    merged.created_at = min(created) if created else None
    return merged


def deduplicate(events: List[Event]) -> List[Event]:
    return [merge(g) for g in group_duplicates(events)]
