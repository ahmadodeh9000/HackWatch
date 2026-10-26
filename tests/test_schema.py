"""Event schema: type values, defaults, and SQLite migration of old databases."""
import sqlite3

import pytest

from hackwatch import cli, db
from hackwatch.models import Event, validate_event_type
from hackwatch.scrapers.base import BaseScraper

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


class FakeScraper(BaseScraper):
    name = "devpost"
    default_type = "hackathon"

    def __init__(self, events):
        super().__init__(delay_seconds=0)
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


@pytest.mark.parametrize("kwargs, mode, is_online", [
    ({}, "in-person", False),
    ({"is_online": True}, "online", True),
    ({"mode": "Hybrid"}, "hybrid", True),
    ({"mode": "virtual"}, "online", True),
    ({"mode": "in person", "is_online": True}, "in-person", False),  # explicit mode wins
])
def test_mode_and_legacy_is_online(kwargs, mode, is_online):
    ev = Event(title="t", url="https://x", source="manual", **kwargs)
    assert (ev.mode, ev.is_online) == (mode, is_online)


def test_bad_mode_raises():
    with pytest.raises(ValueError, match="mode must be one of"):
        Event(title="t", url="https://x", source="manual", mode="sometimes")


def test_hybrid_outside_jordan_is_kept_in_person_is_not():
    from hackwatch.filters import is_relevant
    common = dict(title="Python conf", url="https://x", source="eventbrite", location="Berlin, Germany")
    assert is_relevant(Event(mode="hybrid", **common))
    assert not is_relevant(Event(mode="in-person", **common))


def test_migration_sets_mode_from_is_online(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.execute("INSERT INTO events (id, title, url, source, is_online) VALUES ('1', 'On', 'https://on', 'devpost', 1)")
    raw.execute("INSERT INTO events (id, title, url, source, is_online) VALUES ('2', 'Off', 'https://off', 'josa', 0)")
    raw.commit()
    raw.close()
    conn = db.get_connection(path)
    db.init_db(conn)
    assert {e.title: e.mode for e in db.get_events(conn, show_all=True)} == {"On": "online", "Off": "in-person"}


def test_manual_mode_field(tmp_path):
    from hackwatch.scrapers.manual import ManualEventError, ManualScraper
    path = tmp_path / "m.yaml"
    path.write_text("- title: H\n  url: https://h\n  location: Amman, Jordan\n  mode: hybrid\n")
    (ev,) = ManualScraper(yaml_path=path).fetch()
    assert ev.mode == "hybrid" and ev.location == "Amman, Jordan"
    path.write_text("- title: H\n  url: https://h\n  mode: maybe\n")
    with pytest.raises(ManualEventError, match="mode must be one of"):
        ManualScraper(yaml_path=path).fetch()


def test_tags_are_normalised_against_taxonomy():
    ev = Event(title="t", url="https://x", source="gdg", tags=["Cybersecurity", "CTF", "security", "ML"])
    assert ev.tags == ["security", "ctf", "ai"]


def test_unknown_scraped_tag_is_dropped_with_warning():
    with pytest.warns(UserWarning, match="unknown tag"):
        ev = Event(title="t", url="https://x", source="gdg", tags=["ai", "basket-weaving"])
    assert ev.tags == ["ai"]


def test_manual_unknown_tag_is_an_error(tmp_path):
    from hackwatch.scrapers.manual import ManualEventError, ManualScraper
    path = tmp_path / "m.yaml"
    path.write_text("- title: H\n  url: https://h\n  tags: [robotics, sumo]\n")
    assert ManualScraper(yaml_path=path).fetch()[0].tags == ["robotics", "sumo"]
    path.write_text("- title: H\n  url: https://h\n  tags: robotics, juggling\n")
    with pytest.raises(ManualEventError, match="unknown tag"):
        ManualScraper(yaml_path=path).fetch()


def test_source_default_tags_are_added_and_stored(tmp_path):
    class GDG(FakeScraper):
        name = "gdg"
        default_type = None
        default_tags = ["gdg"]

    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    ev = Event(title="Flutter", url="https://f", source="gdg", location="Amman, Jordan", tags=["mobile"])
    cli.run_fetch(conn, [GDG([ev])])
    assert db.get_events(conn, show_all=True)[0].tags == ["mobile", "gdg"]


def test_scope_from_source_default_event_override_and_location(tmp_path):
    class Worldwide(FakeScraper):
        name = "devpost"
        default_scope = "worldwide"

    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    events = [
        Event(title="Default", url="https://a", source="devpost", is_online=True),
        Event(title="Override", url="https://b", source="devpost", is_online=True, scope="jordan"),
    ]
    cli.run_fetch(conn, [Worldwide(events)])
    # No scraper default and no override: decided by location.
    db.upsert_event(conn, Event(title="Amman", url="https://c", source="manual", location="Amman, Jordan"))
    db.upsert_event(conn, Event(title="Remote", url="https://d", source="manual", is_online=True))
    assert {e.title: e.scope for e in db.get_events(conn, show_all=True)} == {
        "Default": "worldwide", "Override": "jordan", "Amman": "jordan", "Remote": "worldwide"}


def test_bad_scope_is_an_error():
    with pytest.raises(ValueError, match="scope must be one of"):
        Event(title="t", url="https://x", source="manual", scope="mars")


def test_manual_scope_override(tmp_path):
    from hackwatch.scrapers.manual import ManualScraper
    path = tmp_path / "m.yaml"
    path.write_text("- title: MLH GHW\n  url: https://g\n  location: Online\n  scope: worldwide\n")
    assert ManualScraper(yaml_path=path).fetch()[0].scope == "worldwide"


def test_migration_sets_scope(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.execute("INSERT INTO events (id, title, url, source, is_online) VALUES ('1', 'D', 'https://d', 'devpost', 1)")
    raw.execute("INSERT INTO events (id, title, url, source, country) VALUES ('2', 'G', 'https://g', 'gdg', 'JO')")
    raw.commit()
    raw.close()
    conn = db.get_connection(path)
    db.init_db(conn)
    assert {e.title: e.scope for e in db.get_events(conn, show_all=True)} == {"D": "worldwide", "G": "jordan"}
