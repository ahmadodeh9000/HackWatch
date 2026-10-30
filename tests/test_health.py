"""Source health: zero streaks across runs and 'Source down' issues."""
import json

from typer.testing import CliRunner

from hackwatch import cli
from hackwatch.health import sync_issues, update_streaks


def row(source, ok=True, fetched=5, **kw):
    return {"source": source, "ok": ok, "fetched": fetched, "kept": fetched, "error": None,
            "http_status": {"200": 1}, "block_hints": [], "request_errors": [], "requests": 1, "seconds": 1, **kw}


def test_streaks_continue_from_previous_report():
    previous = {"sources": [row("ieee", ok=False, fetched=0, zero_streak=1),
                            row("eventbrite", ok=False, fetched=0),   # old format: no zero_streak
                            row("gdg", zero_streak=0)]}
    current = {"sources": [row("ieee", ok=False, fetched=0), row("eventbrite", ok=False, fetched=0),
                           row("gdg"), row("josa", fetched=0), row("manual", fetched=0)]}
    update_streaks(current, previous, exempt=["manual"])
    assert {r["source"]: r["zero_streak"] for r in current["sources"]} == {
        "ieee": 2, "eventbrite": 2, "gdg": 0, "josa": 1, "manual": 0}
    assert current["sources"][-1]["may_be_empty"] is True


def test_no_previous_report_starts_at_one():
    current = {"sources": [row("ieee", ok=False, fetched=0)]}
    assert update_streaks(current, None)["sources"][0]["zero_streak"] == 1


class FakeIssues:
    def __init__(self, open_issues=()):
        self.open = {i["title"]: i for i in open_issues}
        self.calls = []

    def find_open(self, title):
        return self.open.get(title)

    def create(self, title, body):
        self.calls.append(("create", title, body))
        return {"number": 42}

    def update(self, number, body):
        self.calls.append(("update", number, body))

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def close(self, number):
        self.calls.append(("close", number))


def test_opens_issue_at_two_empty_runs_with_the_error():
    status = {"sources": [row("eventbrite", ok=False, fetched=0, zero_streak=2,
                              error="RuntimeError: all 8 Eventbrite search pages failed",
                              http_status={"405": 8}, block_hints=["page mentions 'captcha'"]),
                          row("josa", fetched=0, zero_streak=1)]}
    api = FakeIssues()
    actions = sync_issues(status, api, run_url="https://github.com/x/y/actions/runs/1", log=lambda m: None)
    assert actions == ["opened #42 Source down: eventbrite"]
    (_, title, body), = api.calls
    assert "2 runs in a row" in body and "405 × 8" in body and "captcha" in body and "runs/1" in body


def test_updates_existing_issue_instead_of_opening_another():
    api = FakeIssues([{"title": "Source down: ieee", "number": 7}])
    sync_issues({"sources": [row("ieee", ok=False, fetched=0, zero_streak=3)]}, api, log=lambda m: None)
    assert [c[0] for c in api.calls] == ["update"] and api.calls[0][1] == 7


def test_closes_issue_when_source_recovers():
    api = FakeIssues([{"title": "Source down: ieee", "number": 7}])
    actions = sync_issues({"sources": [row("ieee", fetched=14, zero_streak=0)]}, api, log=lambda m: None)
    assert actions == ["closed #7 Source down: ieee"]
    assert [c[0] for c in api.calls] == ["comment", "close"] and "is back: 14 events" in api.calls[0][2]


def test_exempt_and_single_empty_runs_do_nothing():
    api = FakeIssues([{"title": "Source down: manual", "number": 3}])
    status = {"sources": [row("manual", fetched=0, zero_streak=0, may_be_empty=True),
                          row("josa", fetched=0, zero_streak=1)]}
    assert sync_issues(status, api, log=lambda m: None) == [] and api.calls == []


def test_health_command_writes_streaks_and_dry_runs_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"sources": [row("ieee", ok=False, fetched=0), row("manual", fetched=0)]}))
    previous = tmp_path / "prev.json"
    previous.write_text(json.dumps({"sources": [row("ieee", ok=False, fetched=0, zero_streak=1)]}))
    result = CliRunner().invoke(cli.app, ["health", "--status", str(status), "--previous", str(previous)])
    assert result.exit_code == 0, result.output
    assert "opened #(dry run) Source down: ieee" in result.output
    written = {r["source"]: r["zero_streak"] for r in json.loads(status.read_text())["sources"]}
    assert written == {"ieee": 2, "manual": 0}


class FreshnessIssues:
    def __init__(self, open_issue=None):
        self.open_issue, self.calls = open_issue, []

    def find_open(self, title):
        assert title == "Site not updating"
        return self.open_issue

    def create(self, title, body):
        self.calls.append(("create", body))
        return {"number": 9}

    def update(self, number, body):
        self.calls.append(("update", number))

    def comment(self, number, body):
        self.calls.append(("comment", number))

    def close(self, number):
        self.calls.append(("close", number))


def _freshness(generated_at, open_issue=None):
    from datetime import datetime, timezone
    from hackwatch.health import sync_freshness
    api = FreshnessIssues(open_issue)
    status = {"generated_at": generated_at} if generated_at else None
    result = sync_freshness(status, api, now=datetime(2026, 10, 30, 12, tzinfo=timezone.utc), log=lambda m: None)
    return result, api.calls


def test_freshness_quiet_when_recent():
    assert _freshness("2026-10-29T09:20:09+00:00") == ("fresh", [])


def test_freshness_opens_issue_after_36_hours():
    result, calls = _freshness("2026-10-28T23:00:00+00:00")
    assert result == "opened" and calls[0][0] == "create" and "37 hours" in calls[0][1]


def test_freshness_updates_open_issue_and_treats_unreadable_as_stale():
    assert _freshness("2026-10-20T00:00:00+00:00", {"number": 4}) == ("updated", [("update", 4)])
    result, calls = _freshness(None)
    assert result == "opened" and "couldn't read" in calls[0][1]


def test_freshness_closes_issue_on_recovery():
    assert _freshness("2026-10-30T03:00:00+00:00", {"number": 4}) == ("closed", [("comment", 4), ("close", 4)])
