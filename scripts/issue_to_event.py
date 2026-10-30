"""Turn an approved "Submit an event" issue into a manual_events.yaml entry.

Run by .github/workflows/submission.yml. The issue body comes ONLY from the
ISSUE_BODY environment variable and is treated as data: it is parsed here in
Python and never pasted into a shell command.

Exit codes: 0 = entry added and `hackwatch validate` passed (PR files written),
            1 = the submission is invalid (errors.md written for the issue comment).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch import submissions  # noqa: E402
from hackwatch.submissions import build_entry, parse_issue_form  # noqa: E402,F401
from hackwatch.scrapers.base import DEFAULT_USER_AGENT  # noqa: E402
from hackwatch.scrapers.ics import load_calendars, parse_ics, validate_calendar  # noqa: E402
from hackwatch.urls import normalize_url  # noqa: E402



def append_entry(yaml_path: Path, entry: dict, issue_number: str) -> None:
    submissions.append_entry(yaml_path, entry, f"Submitted in issue #{issue_number}")


def add_calendar(fields: dict, path: Path, out_dir: Path, number: str, repo: str) -> None:
    """A calendar issue: check the link really is a calendar, append it. ValueError if not."""
    entry = {"name": fields.get("calendar_name", "").strip(), "url": fields.get("calendar_url", "").strip()}
    for key, field in (("city", "calendar_city"), ("page", "calendar_page")):
        if fields.get(field, "").strip():
            entry[key] = fields[field].strip()
    validate_calendar(entry)
    if normalize_url(entry["url"]) in {normalize_url(c["url"]) for c in load_calendars(path)}:
        raise ValueError("this calendar is already connected")
    try:
        resp = requests.get(entry["url"], timeout=30, headers={"User-Agent": DEFAULT_USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"couldn't read the calendar link ({type(exc).__name__}); is the calendar public?")
    if "BEGIN:VCALENDAR" not in resp.text[:2000]:
        raise ValueError("that link isn't an iCal calendar; use the link ending in .ics")
    submissions.append_entry(path, entry, f"Submitted in issue #{number}")
    name = entry["name"]
    (out_dir / "pr-title.txt").write_text(f"Connect calendar: {name}"[:240], encoding="utf-8")
    (out_dir / "commit-msg.txt").write_text(f"Connect calendar: {name}\n\nFrom issue #{number}.\n", encoding="utf-8")
    (out_dir / "pr-body.md").write_text(
        f"Connects the calendar submitted in #{number} (`calendars.yaml`). It holds "
        f"{len(parse_ics(resp.text))} events in total.\n\n"
        f"```yaml\n{yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=100)}```\n\n"
        f"Check it's really that club's calendar before merging: its events go on the site without further review.\n\n"
        f"Closes #{number}\n" + (f"\nIssue: https://github.com/{repo}/issues/{number}\n" if repo else ""),
        encoding="utf-8")
    print(f"Added calendar {name!r} from issue #{number}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", type=Path, default=Path("manual_events.yaml"))
    parser.add_argument("--calendars", type=Path, default=Path("calendars.yaml"))
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

    fields = parse_issue_form(os.environ.get("ISSUE_BODY", ""))
    if "calendar_url" in fields:
        try:
            add_calendar(fields, args.calendars, args.out_dir, number, repo)
        except ValueError as exc:
            return fail(str(exc))
        return 0
    try:
        entry = build_entry(fields)
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
        "`hackwatch validate` passed in the submission workflow (the `hackwatch/validate` status).\n\n"
        f"Closes #{number}\n"
        + (f"\nIssue: https://github.com/{repo}/issues/{number}\n" if repo else ""), encoding="utf-8")
    print(f"Added {title!r} from issue #{number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
