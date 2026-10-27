from dataclasses import dataclass, field
from typing import List, Optional
import hashlib
import warnings
from hackwatch.countries import to_iso2
from hackwatch.taxonomy import normalize_tags
from hackwatch.urls import clean_url, normalize_url

VALID_EVENT_TYPES = ("hackathon", "competition", "conference", "workshop", "meetup", "other")
TYPE_ALIASES = {"contest": "competition"}
DEFAULT_EVENT_TYPE = "other"


def validate_event_type(value: Optional[str], strict: bool = False) -> str:
    """Return a valid event type: aliases are mapped, unknown values become 'other'.

    Unknown values warn, or raise ValueError when strict (manual YAML).
    """
    if value is None or not str(value).strip():
        return DEFAULT_EVENT_TYPE
    v = str(value).strip().lower()
    v = TYPE_ALIASES.get(v, v)
    if v in VALID_EVENT_TYPES:
        return v
    if strict:
        raise ValueError(f"type must be one of {', '.join(VALID_EVENT_TYPES)}, got {value!r}")
    warnings.warn(
        f"Unknown event type '{value}'; falling back to '{DEFAULT_EVENT_TYPE}'. "
        f"Allowed values: {', '.join(sorted(VALID_EVENT_TYPES))}.",
        stacklevel=2,
    )
    return DEFAULT_EVENT_TYPE

VALID_MODES = ("in-person", "online", "hybrid")
MODE_ALIASES = {"in person": "in-person", "inperson": "in-person", "offline": "in-person",
                "onsite": "in-person", "on-site": "in-person", "virtual": "online", "remote": "online"}


def validate_mode(value: str) -> str:
    """Normalise a mode value; raises ValueError for anything unrecognised."""
    v = str(value).strip().lower()
    v = MODE_ALIASES.get(v, v)
    if v not in VALID_MODES:
        raise ValueError(f"mode must be one of {', '.join(VALID_MODES)}, got {value!r}")
    return v

VALID_SCOPES = ("jordan", "worldwide")


def validate_scope(value: str) -> str:
    v = str(value).strip().lower()
    if v not in VALID_SCOPES:
        raise ValueError(f"scope must be one of {', '.join(VALID_SCOPES)}, got {value!r}")
    return v


@dataclass
class Event:
    title: str
    url: str
    source: str
    organizer: Optional[str] = None
    prize: Optional[str] = None
    registration_deadline: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    # Legacy flag kept for the JSON export. If mode is given, is_online is derived
    # from it (hybrid counts as online: you can attend without being there);
    # otherwise mode is derived from is_online.
    is_online: bool = False
    mode: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    # None = not set by the source; run_fetch applies the scraper's default_type,
    # and anything still unset is stored as DEFAULT_EVENT_TYPE.
    type: Optional[str] = None
    # Tag ids from taxonomy.yaml; unknown tags are dropped with a warning.
    tags: List[str] = field(default_factory=list)
    # jordan | worldwide. None = not set; run_fetch applies the scraper's
    # default_scope, and db.upsert_event falls back to the event's location.
    scope: Optional[str] = None
    # The source's own category labels (GDG event tags, Devpost themes). Only used
    # as input for type/tag inference; not stored or exported.
    source_labels: List[str] = field(default_factory=list)
    # Set on merged events (hackwatch/dedup.py): every source and URL that listed
    # this event, most trusted first. `source`/`url` are the first of each.
    sources: List[str] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)
    # True when the source failed or returned nothing this run and the event was
    # copied from the previous deploy (hackwatch/carryover.py).
    stale: bool = False
    # Date (YYYY-MM-DD) the event was first carried over; carryover drops it after 7 days.
    stale_since: Optional[str] = None
    # Who listed it, when a source can tell (IEEE: the student branch number). Two
    # same-day listings from one source with the same host_key may be merged (dedup.py).
    host_key: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    first_seen_run_id: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self):
        if self.mode:
            self.mode = validate_mode(self.mode)
            self.is_online = self.mode != "in-person"
        else:
            self.mode = "online" if self.is_online else "in-person"
        if self.type is not None:
            self.type = validate_event_type(self.type)
        self.tags = normalize_tags(self.tags)
        if self.scope is not None:
            self.scope = validate_scope(self.scope)
        if not self.country:
            self.country = to_iso2(self.location)
        self.url = clean_url(self.url)
        if not self.id:
            # Deterministic ID from source + normalized URL (ignores tracking params, www, slash...)
            self.id = hashlib.sha256(f"{self.source}:{normalize_url(self.url)}".encode("utf-8")).hexdigest()[:16]
