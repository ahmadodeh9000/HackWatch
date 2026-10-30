"""Turn submission form answers (GitHub issue form, Google Form CSV) into manual_events.yaml entries.

Both forms ask the same questions; labels are "English / العربية" and matched by their
English part, so either form can change the Arabic text freely.
"""
import re
from pathlib import Path
from typing import Dict

import yaml

from hackwatch.urls import clean_url

# The English part of each form label (before " / ") -> field id.
LABELS = {
    "event title": "title",
    "event link": "url",
    "start date": "start_date",
    "end date": "end_date",
    "start time": "start_time",
    "end time": "end_time",
    "registration deadline": "registration_deadline",
    "format": "mode",
    "city and venue": "location",
    "organizer": "organizer",
    "event type": "type",
    "tags": "tags",
    "description": "description",
    "cost": "cost",
    "certificate": "certificate",
    "open to": "open_to",
    # The "Connect your club's calendar" form (calendar.yml)
    "club or organization": "calendar_name",
    "calendar link": "calendar_url",
    "city": "calendar_city",
    "public page": "calendar_page",
}
# Answers to the optional dropdowns ("Free / مجاني"); "Not sure" or no answer = unknown.
COSTS = {"free": "free", "paid": "paid"}
CERTIFICATE = {"yes": True, "no": False}
OPEN_TO = {"anyone": "anyone", "students": "students", "members": "members"}
NO_RESPONSE = "_No response_"
MAX_LEN = {"title": 200, "url": 500, "location": 200, "organizer": 200, "tags": 300, "description": 2000}


def parse_issue_form(body: str) -> Dict[str, str]:
    """Split a GitHub issue-form body ("### Label\\n\\nvalue") into {field id: value}."""
    fields: Dict[str, str] = {}
    sections = re.split(r"^###\s+(.+?)\s*$", (body or "").replace("\r\n", "\n"), flags=re.M)
    # sections = [preamble, label1, value1, label2, value2, ...]
    for label, value in zip(sections[1::2], sections[2::2]):
        key = LABELS.get(label.split(" / ")[0].strip().lower())
        if not key:
            continue
        value = value.strip()
        fields[key] = "" if value == NO_RESPONSE else value
    return fields


def first_word(choice: str) -> str:
    """'In-person / حضوري' -> 'in-person'."""
    return choice.split(" / ")[0].strip().lower()


def _choice(answer) -> str:
    """'Students / الطلاب' or 'Students only' -> 'students'."""
    words = first_word(answer or "").split()
    return words[0] if words else ""


def build_entry(fields: Dict[str, str]) -> dict:
    """A manual_events.yaml entry; raises ValueError with a readable message."""
    for key, limit in MAX_LEN.items():
        if len(fields.get(key, "")) > limit:
            raise ValueError(f"{key} is too long (max {limit} characters)")
    start, end = fields.get("start_date", "").strip(), fields.get("end_date", "").strip()
    if not start:
        raise ValueError("start date is required (YYYY-MM-DD)")
    dates = f"{start} to {end}" if end and end != start else start
    mode = first_word(fields.get("mode", "")) or None
    location = fields.get("location", "").strip()
    if mode == "online":
        location = location or "Online"
    elif not location:
        raise ValueError("city and venue are required for in-person and hybrid events")
    from hackwatch.cli import make_manual_entry  # late import: cli imports this module

    entry = make_manual_entry(
        title=fields.get("title", ""),
        url=fields.get("url", ""),
        dates=dates,
        location=location,
        organizer=fields.get("organizer", ""),
        event_type=first_word(fields.get("type", "")) or None,
        mode=mode,
        tags=fields.get("tags", "") or None,
        start_time=fields.get("start_time", "") or None,
        end_time=fields.get("end_time", "") or None,
        registration_deadline=fields.get("registration_deadline", "") or None,
        cost=COSTS.get(_choice(fields.get("cost"))),
        certificate=CERTIFICATE.get(_choice(fields.get("certificate"))),
        open_to=OPEN_TO.get(_choice(fields.get("open_to"))),
    )
    if not re.match(r"^https?://", entry["url"]):
        raise ValueError("event link must start with http:// or https://")
    entry["url"] = clean_url(entry["url"])  # drop ?utm_source=... and the like
    description = " ".join(fields.get("description", "").split())
    if description:
        entry["description"] = description
    return {k: v for k, v in entry.items() if v is not None}


def append_entry(yaml_path: Path, entry: dict, note: str) -> None:
    """Append without rewriting the file, so existing entries and comments stay as they are.

    `note` becomes a YAML comment above the entry (e.g. "Submitted in issue #12").
    """
    text = yaml_path.read_text(encoding="utf-8") if yaml_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=100)
    yaml_path.write_text(f"{text}# {note}\n{block}", encoding="utf-8")


