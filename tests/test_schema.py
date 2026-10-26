"""Event schema: type values, defaults, and SQLite migration of old databases."""
import sqlite3

import pytest

from hackwatch import cli, db
from hackwatch.models import Event, validate_event_type

# The events table as created before Phase 2 (no type/mode/tags/scope columns).
OLD_SCHEMA = """
CREATE TABLE fetch_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE events (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
    organizer TEXT, prize TEXT, registration_deadline TEXT, start_date TEXT, end_date TEXT,
    location TEXT, country TEXT, is_online INTEGER DEFAULT 0, description TEXT,
    first_seen_run_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@pytest.mark.parametrize("raw, expected", [
    ("Hackathon", "hackathon"),
    ("contest", "competition"),
    (" Competition ", "competition"),
    (None, "other"),
    ("", "other"),
])
def test_validate_event_type(raw, expected):
    assert validate_event_type(raw) == expected


def test_unknown_type_becomes_other_with_warning():
    with pytest.warns(UserWarning, match="Unknown event type 'party'"):
        assert validate_event_type("party") == "other"


def test_unset_type_stays_none_until_defaults():
    assert Event(title="t", url="https://x", source="gdg").type is None


class FakeScraper:
    name = "devpost"
    default_type = "hackathon"

    def __init__(self, events):
        self.events = events

    def fetch(self):
        return self.events


def test_source_default_type_does_not_override_explicit(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    events = [
        Event(title="A", url="https://a", source="devpost", is_online=True),
        Event(title="B", url="https://b", source="devpost", is_online=True, type="competition"),
    ]
    cli.run_fetch(conn, [FakeScraper(events)])
    assert {e.title: e.type for e in db.get_events(conn, show_all=True)} == {"A": "hackathon", "B": "competition"}


def test_unset_type_is_stored_as_other(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="X", url="https://x", source="gdg", location="Amman, Jordan"))
    assert db.get_events(conn, show_all=True)[0].type == "other"


def test_migrates_pre_phase2_database(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.execute("INSERT INTO events (id, title, url, source, location, country, is_online) "
                "VALUES ('1', 'Old online', 'https://old', 'devpost', 'Online', NULL, 1)")
    raw.commit()
    raw.close()

    conn = db.get_connection(path)
    db.init_db(conn)
    db.init_db(conn)  # running twice must be harmless
    (ev,) = db.get_events(conn, show_all=True)
    assert ev.title == "Old online" and ev.type == "other"


def test_migration_renames_contest(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    conn.execute("INSERT INTO events (id, title, url, source, type) VALUES ('1', 'C', 'https://c', 'manual', 'contest')")
    db.init_db(conn)
    assert db.get_events(conn, show_all=True)[0].type == "competition"
