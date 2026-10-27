import pytest

from hackwatch.cli import apply_source_defaults
from hackwatch.filters import is_relevant
from hackwatch.scrapers import ctftime
from hackwatch.scrapers.ctftime import extract_prize
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
    assert sudo.prize == "$900"
    assert sudo.description.endswith("Prizes: This year’s prize pool stands at $900 USD, along with "
                                      "plenty of goodies for the top 50 teams.")


@pytest.mark.parametrize("title, prize", [
    ("Sudocrypt v16.0", "$900"),
    ("HI Cyber Con 2026 CTF", "USD 2,500"),       # total pool, not the 1st-place amount after it
    ("Platypwn 2026", None),                      # "See https://platypwnies.de/..."
    ("Cyber Ninja CTF 2026 - BLACKOUT", "€1,500+"),  # "Plus de 1 500 € de lots..."
    ("BSides Algiers 2026", None),                # "Prizes will be announced soon."
])
def test_prize_is_a_short_amount(replay, frozen_today, configured, title, prize):
    event = fetched(replay, frozen_today, configured)[title]
    assert event.prize == prize
    assert "Prizes:" in event.description  # the full text isn't lost


@pytest.mark.parametrize("text, amount", [
    ("TBD Estimated 1100$ worth of prizes", "$1,100"),
    ("over $1,100 in prizes", "$1,100+"),
    ("$100k+ in prizes", "$100,000+"),
    ("1st: 300 USD + 1 year ExamBoot subscription", "USD 300"),
    ("More TBA 1 year .xyz domains pp", ""),
    ("To be announced!", ""),
    ("", ""),
])
def test_extract_prize(text, amount):
    assert extract_prize(text) == amount


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
