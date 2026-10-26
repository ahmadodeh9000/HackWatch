"""Turn an approved "Submit an event" issue into a manual_events.yaml entry.

Run by .github/workflows/submission.yml. The issue body comes ONLY from the
ISSUE_BODY environment variable and is treated as data: it is parsed here in
Python and never pasted into a shell command.

Exit codes: 0 = entry added and `hackwatch validate` passed (PR files written),
            1 = the submission is invalid (errors.md written for the issue comment).
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch.cli import make_manual_entry  # noqa: E402
from hackwatch.urls import clean_url  # noqa: E402

# The English part of each form label (before " / ") -> field id.
LABELS = {
    "event title": "title",
    "event link": "url",
    "start date": "start_date",
    "end date": "end_date",
    "format": "mode",
    "city and venue": "location",
    "organizer": "organizer",
    "event type": "type",
    "tags": "tags",
    "description": "description",
}
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
    entry = make_manual_entry(
        title=fields.get("title", ""),
        url=fields.get("url", ""),
        dates=dates,
        location=location,
        organizer=fields.get("organizer", ""),
        event_type=first_word(fields.get("type", "")) or None,
        mode=mode,
        tags=fields.get("tags", "") or None,
    )
    if not re.match(r"^https?://", entry["url"]):
        raise ValueError("event link must start with http:// or https://")
    entry["url"] = clean_url(entry["url"])  # drop ?utm_source=... and the like
    description = " ".join(fields.get("description", "").split())
    if description:
        entry["description"] = description
    return {k: v for k, v in entry.items() if v is not None}


def append_entry(yaml_path: Path, entry: dict, issue_number: str) -> None:
    """Append without rewriting the file, so existing entries and comments stay as they are."""
    text = yaml_path.read_text(encoding="utf-8") if yaml_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    block = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=100)
    yaml_path.write_text(f"{text}# Submitted in issue #{issue_number}\n{block}", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", type=Path, default=Path("manual_events.yaml"))
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    number = os.environ.get("ISSUE_NUMBER", "")
    if not number.isdigit():
        raise SystemExit("ISSUE_NUMBER must be set to the issue number")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    def fail(problems: str) -> int:
        (args.out_dir / "errors.md").write_text(
            "Thanks for the submission! It couldn't be added yet:\n\n"
            f"```\n{problems.strip()}\n```\n\n"
            "Please **edit the issue** to fix this; a maintainer will then re-apply the `approved` label.\n\n"
            "شكراً! لم نتمكن من إضافة الفعالية بعد. يرجى **تعديل الطلب** لتصحيح المشكلة أعلاه، "
            "وسيعيد أحد المشرفين إضافة وسم `approved`.\n", encoding="utf-8")
        print(problems, file=sys.stderr)
        return 1

    try:
        entry = build_entry(parse_issue_form(os.environ.get("ISSUE_BODY", "")))
    except ValueError as exc:
        return fail(str(exc))

    append_entry(args.yaml, entry, number)
    check = subprocess.run([sys.executable, "-m", "hackwatch.cli", "validate", "--file", str(args.yaml)],
                           capture_output=True, text=True)
    if check.returncode != 0:
        return fail(check.stdout + check.stderr)

    title = entry["title"]
    (args.out_dir / "pr-title.txt").write_text(f"Add event: {title}"[:240], encoding="utf-8")
    (args.out_dir / "commit-msg.txt").write_text(
        f"Add event: {title}\n\nFrom issue #{number}.\n", encoding="utf-8")
    (args.out_dir / "pr-body.md").write_text(
        f"Adds the event submitted in #{number} to `manual_events.yaml`.\n\n"
        f"```yaml\n{yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=100)}```\n\n"
        "`hackwatch validate` passed in the submission workflow. (PRs opened by GitHub Actions "
        "don't trigger the PR check workflow, so validation runs before the PR is opened.)\n\n"
        f"Closes #{number}\n"
        + (f"\nIssue: https://github.com/{repo}/issues/{number}\n" if repo else ""), encoding="utf-8")
    print(f"Added {title!r} from issue #{number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
