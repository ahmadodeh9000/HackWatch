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

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch import submissions  # noqa: E402
from hackwatch.submissions import build_entry, parse_issue_form  # noqa: E402,F401



def append_entry(yaml_path: Path, entry: dict, issue_number: str) -> None:
    submissions.append_entry(yaml_path, entry, f"Submitted in issue #{issue_number}")


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
        "`hackwatch validate` passed in the submission workflow. The PR check on this PR waits "
        "for a maintainer to approve it (GitHub's rule for first-time contributors).\n\n"
        f"Closes #{number}\n"
        + (f"\nIssue: https://github.com/{repo}/issues/{number}\n" if repo else ""), encoding="utf-8")
    print(f"Added {title!r} from issue #{number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
