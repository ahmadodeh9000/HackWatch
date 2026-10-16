from dataclasses import dataclass
from typing import Optional
import hashlib


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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    first_seen_run_id: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            # Deterministic ID generated from source and normalized URL
            norm_url = self.url.strip().rstrip("/").lower()
            self.id = hashlib.sha256(f"{self.source}:{norm_url}".encode("utf-8")).hexdigest()[:16]
