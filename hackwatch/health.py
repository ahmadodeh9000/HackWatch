"""Track sources that keep coming back empty and keep a GitHub issue per broken source.

Each fetch report (status.json) gets a per-source zero_streak, continued from the
previously deployed status.json. At ZERO_RUNS_FOR_ISSUE consecutive empty runs an
issue "Source down: <name>" is opened (or its description updated); when the source
returns events again the issue gets a comment and is closed.
"""
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

import requests

from hackwatch.scrapers.base import DEFAULT_USER_AGENT

ZERO_RUNS_FOR_ISSUE = 2
ISSUE_PREFIX = "Source down: "
STATUS_URL = "https://ahmadodeh9000.github.io/HackWatch/status.json"


def is_zero(row: dict) -> bool:
    return not row.get("ok") or not row.get("fetched")


def update_streaks(current: dict, previous: Optional[dict], exempt: Iterable[str] = ()) -> dict:
    """Add zero_streak to every source row (in place) and return `current`.

    A previous report without zero_streak (older format) counts as 1 if that run was
    empty. Exempt sources (empty is normal, e.g. manual) always get 0.
    """
    exempt = set(exempt)
    before: Dict[str, int] = {}
    for row in (previous or {}).get("sources") or []:
        streak = row.get("zero_streak")
        before[row.get("source")] = int(streak) if streak is not None else (1 if is_zero(row) else 0)
    for row in current.get("sources") or []:
        name = row.get("source")
        if name in exempt:
            row["zero_streak"] = 0
            row["may_be_empty"] = True
        else:
            row["zero_streak"] = before.get(name, 0) + 1 if is_zero(row) else 0
    return current


def issue_body(row: dict, run_url: Optional[str]) -> str:
    statuses = ", ".join(f"{code} × {n}" for code, n in sorted((row.get("http_status") or {}).items())) or "none"
    lines = [
        f"The **{row['source']}** source has returned no events for **{row['zero_streak']} runs in a row**.",
        "",
        "| | |",
        "|---|---|",
        f"| Error | {(row.get('error') or 'none (it answered, but listed 0 events)').replace('|', '/')} |",
        f"| HTTP status | {statuses} |",
        f"| Block hints | {', '.join(row.get('block_hints') or []) or 'none'} |",
        f"| Request errors | {'; '.join(row.get('request_errors') or []).replace('|', '/') or 'none'} |",
        f"| Requests / time | {row.get('requests', 0)} / {row.get('seconds', 0)} s |",
        "",
        "Its events from the last good deploy stay on the site, marked stale, for up to 7 days.",
        f"Latest report: {STATUS_URL}" + (f" · run: {run_url}" if run_url else ""),
        "",
        "_This issue is updated by the daily deploy and closed automatically when the source recovers._",
    ]
    return "\n".join(lines)


class GitHubIssues:
    """The few issue operations health tracking needs (REST API, GITHUB_TOKEN)."""

    def __init__(self, repo: str, token: str, session=None):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                        "User-Agent": DEFAULT_USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}

    def _call(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, self.base + path, headers=self.headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def find_open(self, title: str) -> Optional[dict]:
        for page in (1, 2, 3):
            issues = self._call("GET", "/issues", params={"state": "open", "per_page": 100, "page": page})
            for issue in issues:
                if "pull_request" not in issue and issue.get("title") == title:
                    return issue
            if len(issues) < 100:
                break
        return None

    def create(self, title: str, body: str) -> dict:
        return self._call("POST", "/issues", json={"title": title, "body": body})

    def update(self, number: int, body: str) -> dict:
        return self._call("PATCH", f"/issues/{number}", json={"body": body})

    def comment(self, number: int, body: str) -> dict:
        return self._call("POST", f"/issues/{number}/comments", json={"body": body})

    def close(self, number: int) -> dict:
        return self._call("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})


def sync_issues(status: dict, api, threshold: int = ZERO_RUNS_FOR_ISSUE,
                run_url: Optional[str] = None, log: Callable[[str], None] = print) -> List[str]:
    """Open/update issues for sources at the threshold, close them for recovered ones."""
    actions = []
    for row in status.get("sources") or []:
        if row.get("may_be_empty"):
            continue
        title = ISSUE_PREFIX + row["source"]
        streak = row.get("zero_streak", 0)
        if streak < threshold and streak != 0:
            continue  # one empty run: wait and see
        existing = api.find_open(title)
        if streak >= threshold:
            body = issue_body(row, run_url)
            if existing:
                api.update(existing["number"], body)
                actions.append(f"updated #{existing['number']} {title}")
            else:
                created = api.create(title, body)
                actions.append(f"opened #{created['number']} {title}")
        elif existing:
            api.comment(existing["number"],
                        f"✅ **{row['source']}** is back: {row.get('kept', 0)} events in the latest run. Closing."
                        + (f" ({run_url})" if run_url else ""))
            api.close(existing["number"])
            actions.append(f"closed #{existing['number']} {title}")
    for action in actions:
        log(action)
    return actions


class DryRunIssues:
    """Stand-in used without a token (local runs): sync_issues reports what it would do."""

    def __init__(self, log=print):
        self.log = log

    def find_open(self, title):
        return None

    def create(self, title, body):
        return {"number": "(dry run)"}

    def update(self, number, body):
        return {}

    def comment(self, number, body):
        return {}

    def close(self, number):
        return {}


FRESHNESS_TITLE = "Site not updating"
MAX_AGE_HOURS = 36


def age_hours(status: Optional[dict], now: datetime) -> Optional[float]:
    """Hours since the deployed status.json was generated; None if it's missing or unreadable."""
    try:
        made = datetime.fromisoformat(str((status or {}).get("generated_at")).replace("Z", "+00:00"))
        return (now - made).total_seconds() / 3600
    except ValueError:
        return None


def sync_freshness(status: Optional[dict], api, now: Optional[datetime] = None, max_age: float = MAX_AGE_HOURS,
                   log: Callable[[str], None] = print) -> str:
    """Open/update the "Site not updating" issue when the last deploy is too old; close it after."""
    now = now or datetime.now(timezone.utc)
    age = age_hours(status, now)
    existing = api.find_open(FRESHNESS_TITLE)
    if age is not None and age <= max_age:
        if existing:
            api.comment(existing["number"], f"✅ The site updated {age:.0f} hours ago. Closing.")
            api.close(existing["number"])
            log(f"closed #{existing['number']}")
            return "closed"
        log(f"Fresh: last deploy {age:.1f} hours ago.")
        return "fresh"
    seen = "couldn't read the live status.json" if age is None else f"the last successful deploy was **{age:.0f} hours ago**"
    body = "\n".join([
        f"HackWatch normally deploys every day, but {seen} (limit: {max_age:.0f} hours).",
        "",
        f"- Live report: {STATUS_URL}",
        "- Check the runs of the *Update HackWatch Events & Deploy* workflow in the Actions tab.",
        "",
        f"_Checked {now.strftime('%Y-%m-%d %H:%M')} UTC. Updated every 6 hours; closed automatically once the site is fresh._",
    ])
    if existing:
        api.update(existing["number"], body)
        log(f"updated #{existing['number']}")
        return "updated"
    created = api.create(FRESHNESS_TITLE, body)
    log(f"opened #{created['number']}")
    return "opened"
