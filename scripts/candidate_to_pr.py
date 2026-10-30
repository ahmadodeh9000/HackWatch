"""A box was ticked in the "Candidate events" issue: open a PR per newly ticked line.

Run by .github/workflows/candidates.yml. The issue body comes ONLY from the ISSUE_BODY
environment variable and is treated as data; links go to subprocesses as single arguments, never
through a shell. Each PR adds the event with `hackwatch add --from-url`. A maintainer merging it
is what publishes the event.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch.discovery import ISSUE_TITLE, LINE_RE, LINK_RE  # noqa: E402
from hackwatch.health import GitHubIssues  # noqa: E402

DONE_RE = re.compile(r"(PR #\d+|couldn't add)")


def ticked_lines(body: str) -> List[Tuple[str, str, str]]:
    """(key, url, whole line) for ticked lines without an outcome yet."""
    out = []
    for raw in (body or "").splitlines():
        line = LINE_RE.match(raw)
        if line and line.group("tick") in "xX" and not DONE_RE.search(raw):
            link = LINK_RE.search(raw)
            if link:
                out.append((line.group("key"), link.group(1), raw))
    return out


def mark(body: str, raw: str, note: str) -> str:
    """Put the outcome before the line's hidden key."""
    return body.replace(raw, raw.replace(" <!--k:", f" · {note} <!--k:", 1))


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def open_pr(key: str, url: str, issue: str, sh: Callable = run) -> str:
    """Branch, add, validate, push, PR. Returns the note for the line."""
    branch = f"candidate/{key}"
    for cmd in (["git", "checkout", "-B", branch, "origin/main"],):
        if sh(cmd).returncode:
            return "couldn't add: git checkout failed"
    added = sh([sys.executable, "-m", "hackwatch.cli", "add", "--from-url", url, "--yes", "--file", "manual_events.yaml"])
    if added.returncode:
        reason = " ".join((added.stdout + added.stderr).split())[-90:]
        return f"couldn't add: {reason or 'see the run log'}; add it by hand".replace("[", " ").replace("]", " ")
    checked = sh([sys.executable, "-m", "hackwatch.cli", "validate"])
    if checked.returncode:
        return "couldn't add: entry failed validation; add it by hand"
    title = next((l[len("Saved event '"):].rsplit("' in ", 1)[0] for l in added.stdout.splitlines()
                  if l.startswith("Saved event '")), url)
    steps = [["git", "add", "manual_events.yaml"],
             ["git", "commit", "-m", f"Add event: {title}", "-m", f"Candidate from issue #{issue}."],
             ["git", "push", "origin", branch]]
    for cmd in steps:
        if sh(cmd).returncode:
            return f"couldn't add: {cmd[1]} failed"
    pr = sh(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Add event: {title}"[:240],
             "--body", f"From the [candidate list](#{issue}): {url}\n\nFilled in by `hackwatch add --from-url`. "
                       "**Check the details against the page before merging**; merging publishes it.\n\n"
                       "```\n" + added.stdout[:1500] + "\n```"])
    if pr.returncode:
        return "couldn't add: gh pr create failed"
    number = pr.stdout.strip().rsplit("/", 1)[-1]
    return f"PR #{number}"


def main() -> int:
    issue = os.environ["ISSUE_NUMBER"]
    if not issue.isdigit():
        raise SystemExit("ISSUE_NUMBER must be a number")
    body = os.environ.get("ISSUE_BODY", "")
    todo = ticked_lines(body)
    if not todo:
        print("No newly ticked candidates.")
        return 0
    notes = [(raw, open_pr(key, url, issue)) for key, url, raw in todo]
    api = GitHubIssues(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    current = api._call("GET", f"/issues/{issue}")
    if current.get("title") != ISSUE_TITLE:
        raise SystemExit("not the candidates issue")
    text = current.get("body") or ""
    for raw, note in notes:
        print(note)
        text = mark(text, raw, note)
    api.update(int(issue), text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
