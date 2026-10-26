"""Offline baseline tests: each scraper parses its recorded real responses.

These pin down what the scrapers do *today* (Phase 0), so later changes that
break parsing show up as test failures instead of an empty website.
"""
import textwrap

import pytest

from hackwatch.scrapers import gdg, josa
from hackwatch.scrapers.devpost import DevpostScraper, parse_devpost_dates
from hackwatch.scrapers.eventbrite import EventbriteScraper
from hackwatch.scrapers.gdg import GDGScraper
from hackwatch.scrapers.josa import JOSAScraper
from hackwatch.scrapers.manual import ManualEventError, ManualScraper


def by_title(events):
    return {e.title: e for e in events}


def test_devpost_parses_api_pages(replay):
    replay("devpost")
    events = DevpostScraper(delay_seconds=0).fetch()

    assert len(events) == 18  # 2 pages x 9 per page
    ev = by_title(events)["Nebius x NVIDIA Global AI Hackathon"]
    assert ev.url == "https://nebiusglobalaihackathon.devpost.com/"
    assert (ev.start_date, ev.end_date) == ("2026-08-26", "2026-10-30")
    assert ev.is_online and ev.location == "Online"
    assert ev.prize == "$50,000"


def test_devpost_date_formats():
    assert parse_devpost_dates("Aug 31 - Oct 23, 2026") == ("2026-08-31", "2026-10-23")
    assert parse_devpost_dates("Oct 05 - 23, 2026") == ("2026-10-05", "2026-10-23")
    assert parse_devpost_dates("Dec 20, 2026 - Jan 10, 2027") == ("2026-12-20", "2027-01-10")
    assert parse_devpost_dates(None) == (None, None)


def test_eventbrite_parses_jordan_pages(replay):
    replay("eventbrite")
    events = EventbriteScraper(delay_seconds=0).fetch()

    assert len(events) == 11  # 8 Jordan term pages, de-duplicated by URL
    assert not any(e.is_online for e in events)

    amman = by_title(events)["Pocket Gamer Connects Jordan 2026"]
    assert "?" not in amman.url  # tracking params stripped
    assert amman.country == "JO"
    assert amman.location == "Abdali Boulevard, Amman, Jordan"
    assert (amman.start_date, amman.end_date) == ("2026-11-07", "2026-11-08")


def test_gdg_parses_jordan_chapters(replay, frozen_today):
    replay("gdg")
    frozen_today(gdg)
    events = GDGScraper(delay_seconds=0).fetch()

    # Past events are skipped, so only upcoming ones remain.
    assert sorted(e.title for e in events) == [
        "DevFest Amman 2026",
        "Mastering Research Papers: How to Read Them Effectively",
        "🚀 Flutter Bootcamp: Learn App Development",
        "🚀 Flutter Bootcamp: Learn App Development",
    ]
    devfest = by_title(events)["DevFest Amman 2026"]
    assert devfest.organizer == "GDG Amman"
    assert devfest.start_date == "2026-11-28"
    assert devfest.country == "JO" and not devfest.is_online


def test_josa_parses_event_previews(replay, frozen_today):
    replay("josa")
    frozen_today(josa)
    events = JOSAScraper(delay_seconds=0).fetch()

    assert len(events) == 5
    ev = by_title(events)["Hacktoberfest 2026 Amman"]
    assert ev.url == "https://josa.ngo/events/265"
    assert ev.start_date == "2026-10-24"
    assert ev.location == "Amman, Jordan" and not ev.is_online


def test_manual_reads_yaml(tmp_path):
    path = tmp_path / "events.yaml"
    path.write_text(textwrap.dedent("""\
        - title: Club Hackathon
          url: https://example.com/hack
          dates: 2026-11-15 to 2026-11-17
          location: Amman, Jordan
          organizer: My Club
        - title: Online Meetup
          url: https://example.com/meetup
          dates: 2026-12-01
          location: Online
    """))
    events = ManualScraper(yaml_path=path).fetch()

    assert [e.title for e in events] == ["Club Hackathon", "Online Meetup"]
    hack, meetup = events
    assert (hack.start_date, hack.end_date) == ("2026-11-15", "2026-11-17")
    assert hack.country == "JO" and not hack.is_online
    assert meetup.is_online and meetup.start_date == meetup.end_date == "2026-12-01"
    assert hack.registration_deadline is None  # not copied from end_date


def write_yaml(tmp_path, body):
    path = tmp_path / "events.yaml"
    path.write_text(textwrap.dedent(body))
    return ManualScraper(yaml_path=path)


def test_manual_accepts_yaml_dates_and_explicit_fields(tmp_path):
    (ev,) = write_yaml(tmp_path, """\
        - title: A
          url: https://example.com/a
          start_date: 2026-11-01
          end_date: '2026-11-02'
          registration_deadline: 2026-10-30
    """).fetch()
    assert (ev.start_date, ev.end_date, ev.registration_deadline) == ("2026-11-01", "2026-11-02", "2026-10-30")


@pytest.mark.parametrize("bad, message", [
    ("dates: 11/01/2026", "dates must be an ISO date"),
    ("dates: Nov 1 to Nov 3", "dates (start) must be an ISO date"),
    ("start_date: 2026-02-30", "start_date must be an ISO date"),
    ("dates: 2026-11-05 to 2026-11-01", "end date 2026-11-01 is before start date"),
])
def test_manual_rejects_bad_dates(tmp_path, bad, message):
    scraper = write_yaml(tmp_path, f"""\
        - title: Good
          url: https://example.com/good
          dates: 2026-11-01
        - title: Broken
          url: https://example.com/broken
          {bad}
    """)
    with pytest.raises(ManualEventError) as exc:
        scraper.fetch()
    assert "entry #2 (Broken)" in str(exc.value)
    assert message in str(exc.value)


def test_manual_requires_title_and_url(tmp_path):
    with pytest.raises(ManualEventError, match="title and url are required"):
        write_yaml(tmp_path, "- title: no url\n").fetch()


def test_josa_year_inference_picks_nearest_year():
    from datetime import date
    from hackwatch.scrapers.josa import infer_year

    assert infer_year(24, "October", date(2026, 10, 26)) == date(2026, 10, 24)
    assert infer_year(5, "January", date(2026, 12, 28)) == date(2027, 1, 5)    # Dec -> next Jan
    assert infer_year(28, "December", date(2027, 1, 3)) == date(2026, 12, 28)  # Jan -> last Dec
    assert infer_year(29, "February", date(2027, 6, 1)) == date(2028, 2, 29)   # only leap year fits
    assert infer_year(3, "Smarch", date(2026, 1, 1)) is None
