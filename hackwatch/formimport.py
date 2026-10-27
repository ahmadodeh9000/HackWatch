"""Import a Google Form responses CSV into manual_events.yaml.

The form asks the same questions as the GitHub issue form (see CONTRIBUTING.md for
the exact titles), so each CSV column is matched by the English part of its
question title. Every row goes through the same checks as `hackwatch validate`;
invalid rows are reported, not imported, and rows whose link is already in
manual_events.yaml (or earlier in the CSV) are skipped as duplicates.
"""
import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from hackwatch.scrapers.manual import load_manual_events
from hackwatch.submissions import LABELS, append_entry, build_entry
from hackwatch.taxonomy import site_labels
from hackwatch.urls import normalize_url

TIMESTAMP_COLUMN = "timestamp"


@dataclass
class ImportResult:
    added: List[str] = field(default_factory=list)       # titles
    duplicates: List[str] = field(default_factory=list)  # "row N: title"
    errors: List[str] = field(default_factory=list)      # "row N (title): problem"


def clock_time(value: str) -> str:
    """Google Forms 'Time' answers look like '6:00:00 PM'; short answers like '18:00'."""
    value = (value or "").strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(value.upper(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", value)
    return f"{m.group(1)}:{m.group(2)}" if m else value


def tag_ids(value: str) -> str:
    """Checkbox answers are joined with ', ' and may be labels ('AI & ML') or ids ('ai')."""
    by_label = {label.lower(): tag for tag, label in site_labels()["tags"].items()}
    # Split on commas, then map labels back to tag ids (no label contains a comma).
    parts = [p.strip() for p in re.split(r",\s*", value or "") if p.strip()]
    return ", ".join(by_label.get(p.lower(), p) for p in parts)


def row_fields(row: Dict[str, str]) -> Dict[str, str]:
    """{column title: answer} -> {field id: value}, the shape build_entry expects."""
    fields = {}
    for column, value in row.items():
        key = LABELS.get((column or "").split(" / ")[0].strip().lower())
        if key:
            fields[key] = (value or "").strip()
    for key in ("start_time", "end_time"):
        if fields.get(key):
            fields[key] = clock_time(fields[key])
    if fields.get("tags"):
        fields["tags"] = tag_ids(fields["tags"])
    return fields


def import_csv(csv_path: Path, yaml_path: Path, dry_run: bool = False) -> ImportResult:
    result = ImportResult()
    existing, _ = load_manual_events(yaml_path) if yaml_path.exists() else ([], [])
    seen = {normalize_url(e.url) for e in existing}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:  # Google adds a BOM
        rows = list(csv.DictReader(f))
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        fields = row_fields(row)
        title = fields.get("title") or "untitled"
        try:
            entry = build_entry(fields)
        except ValueError as exc:
            result.errors.append(f"row {number} ({title}): {exc}")
            continue
        key = normalize_url(entry["url"])
        if key in seen:
            result.duplicates.append(f"row {number}: {title}")
            continue
        seen.add(key)
        if not dry_run:
            stamp = next((v for k, v in row.items() if (k or "").strip().lower() == TIMESTAMP_COLUMN), "")
            append_entry(yaml_path, entry, f"From the Google Form{', submitted ' + stamp if stamp else ''}")
        result.added.append(entry["title"])
    return result
