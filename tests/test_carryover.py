"""Per-source deploy guard: keep last deployed events of a source that returned nothing."""
import json
from datetime import date

import pytest
from typer.testing import CliRunner

from hackwatch import cli, db
from hackwatch.carryover import carry_over, load_previous
from hackwatch.models import Event

TODAY = date(2026, 10, 27)


def record(title, source, start="2026-11-05", end=None, **kw):
    return {"title": title, "url": f"https://{source}.test/{title.replace(' ', '-')}", "source": source,
            "start_date": start, "end_date": end, "location": "Amman, Jordan", "mode": "in-person",
            "type": "meetup", "tags": ["ieee"] if source == "ieee" else [], "scope": "jordan",
            "sources": [source], "urls": [], "is_online": False, **kw}


PREVIOUS = [record(f"IEEE {i}", "ieee") for i in range(4)] + [
    record("IEEE ended", "ieee", start="2026-10-01"),
    record("Eventbrite 1", "eventbrite"), record("Eventbrite 2", "eventbrite"),
    record("GDG 1", "gdg"), record("GDG 2", "gdg"), record("GDG 3", "gdg"),
]


@pytest.fixture
def conn(tmp_path):
    c = db.get_connection(tmp_path / "t.db")
    db.init_db(c)
    return c


def test_restores_only_empty_sources_that_had_enough_events(conn):
    # GDG fetched fine this run; IEEE (5 before) and Eventbrite (2 before) returned nothing.
    db.upsert_event(conn, Event(title="GDG new", url="https://gdg.test/new", source="gdg",
                                location="Amman, Jordan", start_date="2026-11-20"))
    restored = carry_over(conn, PREVIOUS, ["ieee", "eventbrite", "gdg"], today=TODAY)

    assert restored == {"ieee": 4}  # the ended one isn't brought back; eventbrite had < 3
    events = {e.title: e for e in db.get_events(conn, show_all=True)}
    assert set(events) == {"GDG new", "IEEE 0", "IEEE 1", "IEEE 2", "IEEE 3"}
    assert events["IEEE 0"].stale and events["IEEE 0"].tags == ["ieee"]
    assert not events["GDG new"].stale


def test_sources_not_in_config_are_ignored(conn):
    assert carry_over(conn, PREVIOUS, ["gdg"], today=TODAY) == {"gdg": 3}


def test_stale_flag_clears_when_a_fresh_listing_merges(conn):
    carry_over(conn, PREVIOUS, ["ieee"], today=TODAY)
    fresh = record("IEEE 0", "ieee")
    db.upsert_event(conn, Event(title=fresh["title"], url=fresh["url"], source="manual",
                                location="Amman, Jordan", start_date=fresh["start_date"]))
    merged = {e.title: e for e in db.get_events(conn, show_all=True)}["IEEE 0"]
    assert merged.sources == ["manual", "ieee"] and not merged.stale


def test_load_previous_handles_missing_and_bad_files(tmp_path):
    assert load_previous(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_previous(str(bad)) is None
    good = tmp_path / "good.json"
    good.write_text(json.dumps(PREVIOUS))
    assert len(load_previous(str(good))) == len(PREVIOUS)


def test_command_warns_in_log_and_job_summary(tmp_path, monkeypatch):
    previous = tmp_path / "events.json"
    previous.write_text(json.dumps([record(f"IEEE {i}", "ieee", start="2099-01-01") for i in range(3)]))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["carry-over", "--db", str(tmp_path / "t.db"), "--previous", str(previous)])
    assert result.exit_code == 0, result.output
    assert "::warning title=Source returned nothing::ieee returned no events this run (it had 3" in result.output
    assert "Deploy guard" in summary.read_text()

    out = tmp_path / "out.json"
    runner.invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"), "--out", str(out)])
    assert all(r["stale"] for r in json.loads(out.read_text()))


def test_command_without_previous_export_does_nothing(tmp_path):
    result = CliRunner().invoke(cli.app, ["carry-over", "--db", str(tmp_path / "t.db"),
                                          "--previous", str(tmp_path / "missing.json")])
    assert result.exit_code == 0 and "nothing carried over" in result.output
