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

    run_id, results = cli.run_fetch(conn, [broken, good], on_result=lambda *r: seen.append(r))

    assert results == seen == [("eventbrite", 0, 0, "site down"), ("manual", 1, 1, None)]
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
