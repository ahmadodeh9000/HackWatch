import json

import pytest
import yaml

from hackwatch import cli, db
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


class FakeScraper(BaseScraper):
    def __init__(self, name, events=None, error=None):
        super().__init__(delay_seconds=0)
        self.name, self.events, self.error = name, events or [], error

    def fetch(self):
        if self.error:
            raise self.error
        return self.events


def test_run_fetch_stores_relevant_events_and_survives_errors(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    good = FakeScraper("manual", [Event(title="Club Hack", url="https://e.com/1", source="manual",
                                        start_date="2099-01-01", location="Amman, Jordan")])
    broken = FakeScraper("eventbrite", error=RuntimeError("site down"))
    seen = []

    run_id, results = cli.run_fetch(conn, [broken, good], on_result=seen.append)

    assert results == seen == [("eventbrite", 0, 0, "site down", 0, None), ("manual", 1, 1, None, 0, None)]
    assert [e.title for e in db.get_events(conn, only_new=True)] == ["Club Hack"]
    assert run_id == db.get_latest_fetch_run_id(conn)


def test_make_manual_entry_validates():
    entry = cli.make_manual_entry(" T ", "https://x.test", "2026-11-01 to 2026-11-02", "", "", "meetup")
    assert entry == {"title": "T", "url": "https://x.test", "dates": "2026-11-01 to 2026-11-02",
                     "location": "Online", "organizer": None, "type": "meetup"}
    with pytest.raises(ValueError, match="ISO date"):
        cli.make_manual_entry("T", "https://x.test", "Nov 1", "", "", None)
    with pytest.raises(ValueError, match="required"):
        cli.make_manual_entry("", "https://x.test", "", "", "", None)


def test_save_manual_entry_upserts_by_url(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("- title: Old\n  url: https://x.test/\n  start_date: 2026-11-01\n")
    new = cli.make_manual_entry("New", "https://X.test", "2026-12-01", "Online", "", None)

    assert cli.save_manual_entry(new, path) is True
    assert cli.save_manual_entry(cli.make_manual_entry("B", "https://b.test", "", "", "", None), path) is False
    assert [e["title"] for e in yaml.safe_load(path.read_text())] == ["New", "B"]


from typer.testing import CliRunner  # noqa: E402

runner = CliRunner()


def _db_with_events(tmp_path):
    path = tmp_path / "t.db"
    conn = db.get_connection(path)
    db.init_db(conn)
    for ev in [
        Event(title="CTF Night", url="https://a", source="manual", is_online=True, tags=["ctf", "security"],
              type="competition", scope="worldwide", start_date="2099-01-01"),
        Event(title="Robot Sumo", url="https://b", source="manual", location="Irbid, Jordan", tags=["robotics", "sumo"],
              type="competition", start_date="2099-01-02"),
        Event(title="AI Hybrid Talk", url="https://c", source="manual", location="Amman, Jordan", mode="hybrid",
              tags=["ai"], type="meetup", start_date="2099-01-03"),
    ]:
        db.upsert_event(conn, ev)
    return path


@pytest.mark.parametrize("args, expected", [
    (["--tag", "robotics"], ["Robot Sumo"]),
    (["--tag", "cybersecurity", "--tag", "ctf"], ["CTF Night"]),  # alias, and all tags required
    (["--mode", "hybrid"], ["AI Hybrid Talk"]),
    (["--scope", "jordan"], ["Robot Sumo", "AI Hybrid Talk"]),
    (["--type", "contest"], ["CTF Night", "Robot Sumo"]),  # alias of competition
])
def test_list_filters(tmp_path, args, expected):
    result = runner.invoke(cli.app, ["list", "--db", str(_db_with_events(tmp_path)), *args])
    assert result.exit_code == 0, result.output
    titles = [line.split("] ", 1)[1].split(" (")[0] for line in result.output.splitlines() if line.startswith("- [")]
    assert titles == expected


@pytest.mark.parametrize("args", [["--mode", "sometimes"], ["--scope", "mars"], ["--tag", "juggling"]])
def test_list_rejects_bad_filter_values(tmp_path, args):
    result = runner.invoke(cli.app, ["list", "--db", str(tmp_path / "t.db"), *args])
    assert result.exit_code == 1 and "Error:" in result.output


def test_export_keeps_legacy_fields(tmp_path):
    out = tmp_path / "events.json"
    result = runner.invoke(cli.app, ["export", "--db", str(_db_with_events(tmp_path)), "--out", str(out)])
    assert result.exit_code == 0, result.output
    records = {r["title"]: r for r in json.loads(out.read_text())}
    hybrid = records["AI Hybrid Talk"]
    assert hybrid["mode"] == "hybrid" and hybrid["is_online"] is True  # legacy flag still present
    assert hybrid["type"] == "meetup" and hybrid["scope"] == "jordan" and hybrid["tags"] == ["ai"]
    assert records["CTF Night"]["tags"] == ["ctf", "security"]


def test_add_with_mode_tags_scope(tmp_path):
    path = tmp_path / "m.yaml"
    result = runner.invoke(cli.app, [
        "add", "--file", str(path), "-t", "Line Follower Cup", "-u", "https://lf", "-d", "2026-12-05",
        "-l", "Amman, Jordan", "-o", "IEEE JU", "--type", "competition",
        "--mode", "in-person", "--tags", "line-follower, Robotics, IEEE",
    ])
    assert result.exit_code == 0, result.output
    (entry,) = yaml.safe_load(path.read_text())
    assert entry["mode"] == "in-person" and entry["tags"] == ["line-follower", "robotics", "ieee"]
    assert "scope" not in entry  # only written when given

    bad = runner.invoke(cli.app, ["add", "--file", str(path), "-t", "X", "-u", "https://x", "-d", "2026-12-05",
                                  "-l", "Online", "-o", "me", "--type", "other", "--tags", "juggling"])
    assert bad.exit_code == 1 and "unknown tag" in bad.output


def test_export_labels_for_the_site(tmp_path):
    labels = tmp_path / "labels.json"
    result = runner.invoke(cli.app, ["export", "--db", str(_db_with_events(tmp_path)),
                                     "--out", str(tmp_path / "e.json"), "--labels", str(labels)])
    assert result.exit_code == 0, result.output
    data = json.loads(labels.read_text())
    assert data["tags"]["cp"] == "Competitive programming"
    assert data["types"][-1] == "other"
    assert all("id" in r for r in json.loads((tmp_path / "e.json").read_text()))
