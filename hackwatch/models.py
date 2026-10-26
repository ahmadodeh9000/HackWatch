from dataclasses import dataclass, field
from typing import Optional
import hashlib
import warnings
from hackwatch.countries import to_iso2

VALID_EVENT_TYPES = {"hackathon", "contest", "conference", "workshop", "meetup"}
DEFAULT_EVENT_TYPE = "hackathon"


def validate_event_type(value: Optional[str]) -> str:
    """Return a valid event type, defaulting to 'hackathon' with a warning on unknown values."""
    if value is None:
        return DEFAULT_EVENT_TYPE
    v = value.strip().lower()
    if v in VALID_EVENT_TYPES:
        return v
    warnings.warn(
        f"Unknown event type '{value}'; falling back to '{DEFAULT_EVENT_TYPE}'. "
        f"Allowed values: {', '.join(sorted(VALID_EVENT_TYPES))}.",
        stacklevel=2,
    )
    return DEFAULT_EVENT_TYPE


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
    is_online: bool = False
    description: Optional[str] = None
    country: Optional[str] = None
    type: str = DEFAULT_EVENT_TYPE
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    first_seen_run_id: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self):
        # Validate and normalise event type
        self.type = validate_event_type(self.type)
        if not self.country:
            self.country = to_iso2(self.location)
        if not self.id:
            # Deterministic ID generated from source and normalized URL
            norm_url = self.url.strip().rstrip("/").lower()
            self.id = hashlib.sha256(f"{self.source}:{norm_url}".encode("utf-8")).hexdigest()[:16]
