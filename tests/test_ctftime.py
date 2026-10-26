from hackwatch.cli import apply_source_defaults
from hackwatch.filters import is_relevant
from hackwatch.scrapers import ctftime
from hackwatch.timeutil import local_date


def fetched(replay, frozen_today, configured):
    replay("ctftime")
    frozen_today(ctftime)
    scraper = configured("ctftime")
    events = scraper.fetch()
    for e in events:
        apply_source_defaults(e, scraper)
    return {e.title: e for e in events}


def test_ctftime_events(replay, frozen_today, configured):
    events = fetched(replay, frozen_today, configured)
    assert len(events) == 36

    sudo = events["Sudocrypt v16.0"]
    assert sudo.url == "https://ctftime.org/event/3443/"
    assert (sudo.start_date, sudo.end_date) == ("2026-10-27", "2026-10-28")
    assert sudo.mode == "online" and sudo.scope == "worldwide"
    assert sudo.type == "competition"
    assert sudo.tags == ["ctf", "security"]  # fixed; not guessed from the category list
    assert sudo.organizer == "exunclan"
    assert sudo.description.startswith("Hack quest · Open CTF.")
    assert sudo.prize.startswith("This year’s prize pool stands at $900 USD")


def test_onsite_ctfs_abroad_are_dropped(replay, frozen_today, configured):
    events = fetched(replay, frozen_today, configured)
    riyadh = events["BlackHat MEA CTF Final 2026"]
    assert riyadh.mode == "in-person" and riyadh.location == "Riyadh, Saudi Arabia"
    assert not is_relevant(riyadh)
    assert sum(is_relevant(e) for e in events.values()) == 27


def test_local_date_uses_amman_time():
    assert local_date("2026-10-27T22:30:00+00:00") == "2026-10-28"  # 01:30 in Amman
    assert local_date("2026-10-27T20:00:00Z") == "2026-10-27"
    assert local_date(1793457300) == "2026-10-31"
    assert local_date("2026-10-27T22:30:00Z", "America/Bogota") == "2026-10-27"
    assert local_date(None) is None
