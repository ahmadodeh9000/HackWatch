"""Duplicate detection, merging, and removing events a source no longer lists."""
from datetime import date, timedelta

import pytest

from hackwatch import cli, db
from hackwatch.dedup import deduplicate, normalize_title, same_event
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper


def soon(days: int) -> str:
    """A date within the next year, so filters.is_relevant keeps it."""
    return (date.today() + timedelta(days=days)).isoformat()


def ev(title, source, url, start="2099-11-28", scope=None, **kw):
    return Event(title=title, source=source, url=url, start_date=start, scope=scope, **kw)


def test_normalize_title():
    assert normalize_title("🚀 DevFest Amman 2026!") == "devfest amman"
    assert normalize_title("The AI Hackathon, by GDG") == "ai hackathon gdg"
    assert normalize_title("هاكاثون عمّان 2026") == "هاكاثون عمان"


@pytest.mark.parametrize("a, b, same", [
    # same page, different spelling of the URL
    (ev("X", "gdg", "https://gdg.dev/e/1/"), ev("Y", "eventbrite", "http://www.gdg.dev/e/1?utm_source=z"), True),
    # similar title, different sources, start within a day
    (ev("DevFest Amman 2026", "gdg", "https://a"), ev("Devfest Amman", "eventbrite", "https://b", start="2099-11-29"), True),
    # ...but not two days apart
    (ev("DevFest Amman 2026", "gdg", "https://a"), ev("Devfest Amman", "eventbrite", "https://b", start="2099-11-30"), False),
    # same source, similar titles = separate sessions
    (ev("Flutter Bootcamp", "gdg", "https://a"), ev("Flutter Bootcamp", "gdg", "https://b"), False),
    # different events on the same day
    (ev("DevFest Amman", "gdg", "https://a"), ev("PyCon Amman", "eventbrite", "https://b"), False),
    # no start date: only the URL can match
    (ev("DevFest Amman", "gdg", "https://a", start=None), ev("DevFest Amman", "eventbrite", "https://b", start=None), False),
])
def test_same_event(a, b, same):
    assert same_event(a, b) is same


def test_merge_precedence_and_field_filling():
    worldwide = ev("Global AI Hackathon", "devpost", "https://ai.devpost.com/", scope="worldwide",
                   prize="$10,000", description="Long description", tags=["ai"], type="hackathon", is_online=True)
    jordan = ev("Global AI Hackathon", "eventbrite", "https://eventbrite.com/e/ai-hack-1", scope="jordan",
                tags=["web"], type="other", location="Amman, Jordan", mode="hybrid")
    manual = ev("Global AI Hackathon (Amman hub)", "manual", "https://ai.devpost.com", scope="jordan",
                organizer="IEEE PSUT")

    (merged,) = deduplicate([worldwide, jordan, manual])

    assert merged.source == "manual" and merged.title == "Global AI Hackathon (Amman hub)"
    assert merged.sources == ["manual", "eventbrite", "devpost"]
    assert merged.urls == ["https://ai.devpost.com", "https://eventbrite.com/e/ai-hack-1", "https://ai.devpost.com/"]
    assert merged.organizer == "IEEE PSUT"          # from manual
    assert merged.location == "Amman, Jordan"       # manual had none -> next (Jordan source)
    assert merged.prize == "$10,000"                # only the worldwide feed had it
    assert merged.type == "hackathon"               # 'other' is filled from a later source
    assert merged.tags == ["web", "ai"]
    assert merged.scope == "jordan"


def test_jordan_source_beats_worldwide_feed():
    a = ev("Space Apps Amman", "devpost", "https://x/1", scope="worldwide")
    b = ev("Space Apps Amman", "eventbrite", "https://x/2", scope="jordan")
    (merged,) = deduplicate([a, b])
    assert merged.source == "eventbrite" and merged.url == "https://x/2"


class Listing(BaseScraper):
    def __init__(self, name, events=None, error=None):
        super().__init__(delay_seconds=0)
        self.name, self.events, self.error = name, events or [], error

    def fetch(self):
        if self.error:
            raise RuntimeError(self.error)
        return list(self.events)


def jo(title, source, n):
    return Event(title=title, url=f"https://{source}.test/{n}", source=source,
                 location="Amman, Jordan", start_date=soon(n))


@pytest.fixture
def conn(tmp_path):
    c = db.get_connection(tmp_path / "t.db")
    db.init_db(c)
    return c


def titles(conn):
    return sorted(e.title for e in db.get_events(conn, show_all=True))


def test_events_a_source_drops_are_removed(conn):
    cli.run_fetch(conn, [Listing("gdg", [jo("A", "gdg", 1), jo("B", "gdg", 2)]),
                         Listing("josa", [jo("J", "josa", 3)])])
    _, results = cli.run_fetch(conn, [Listing("gdg", [jo("A", "gdg", 1)]),
                                      Listing("josa", [jo("J", "josa", 3)])])
    assert titles(conn) == ["A", "J"]
    assert results[0].removed == 1


def test_errored_source_keeps_its_events(conn):
    cli.run_fetch(conn, [Listing("gdg", [jo("A", "gdg", 1)]), Listing("josa", [jo("J", "josa", 3)])])
    _, results = cli.run_fetch(conn, [Listing("gdg", error="timeout"), Listing("josa", [])])
    assert results[0].error == "RuntimeError: timeout"
    assert titles(conn) == ["A"]  # josa fetched fine and listed nothing -> its event is gone


def test_suddenly_empty_source_is_not_wiped(conn):
    events = [jo(t, "gdg", n) for n, t in enumerate("ABC", 1)]
    cli.run_fetch(conn, [Listing("gdg", events)])
    _, (result,) = cli.run_fetch(conn, [Listing("gdg", [])])
    assert "kept its 3 stored events" in result.note
    assert titles(conn) == ["A", "B", "C"]


def test_duplicates_across_sources_are_merged_in_db(conn):
    cli.run_fetch(conn, [
        Listing("gdg", [Event(title="DevFest Amman 2026", url="https://gdg.test/devfest", source="gdg",
                              location="Amman, Jordan", start_date=soon(30), tags=["gdg"])]),
        Listing("eventbrite", [Event(title="DevFest Amman", url="https://eb.test/devfest?aff=x", source="eventbrite",
                                     location="Amman, Jordan", start_date=soon(30), description="Talks")]),
    ])
    (merged,) = db.get_events(conn, show_all=True)
    assert merged.sources == ["eventbrite", "gdg"]  # equally trusted: ties break by name
    assert len(merged.urls) == 2 and "https://eb.test/devfest" in merged.urls  # tracking param gone
    assert merged.description == "Talks"


def test_new_flag_and_ids_are_stable_across_runs(conn):
    cli.run_fetch(conn, [Listing("gdg", [jo("A", "gdg", 1)])])
    (first,) = db.get_events(conn, show_all=True)
    cli.run_fetch(conn, [Listing("gdg", [jo("A", "gdg", 1), jo("B", "gdg", 2)])])
    assert [e.title for e in db.get_events(conn, only_new=True, show_all=True)] == ["B"]
    assert {e.title: e.id for e in db.get_events(conn, show_all=True)}["A"] == first.id


def test_old_database_rows_become_observations(tmp_path):
    import sqlite3
    from tests.test_schema import OLD_SCHEMA
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.execute("INSERT INTO events (id, title, url, source, location, start_date) "
                "VALUES ('1', 'Old', 'https://old.test/e', 'josa', 'Amman, Jordan', ?)", (soon(5),))
    raw.commit()
    raw.close()
    conn = db.get_connection(path)
    db.init_db(conn)
    assert db.count_observations(conn, "josa") == 1
    (event,) = db.get_events(conn, show_all=True)
    assert event.sources == ["josa"] and event.urls == ["https://old.test/e"]
    # ...so the next successful josa fetch can remove it
    cli.run_fetch(conn, [Listing("josa", [jo("New", "josa", 2)])])
    assert titles(conn) == ["New"]
