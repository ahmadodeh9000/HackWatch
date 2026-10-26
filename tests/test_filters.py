import pytest

from hackwatch import filters
from hackwatch.models import Event
from hackwatch.scrapers import gdg
from hackwatch.scrapers.eventbrite import EventbriteScraper
from hackwatch.scrapers.gdg import GDGScraper


def ev(title, source="eventbrite", online=True, location=None, description=None, **kw):
    return Event(title=title, url=f"https://example.com/{title}", source=source,
                 is_online=online, location=location or ("Online" if online else None),
                 description=description, **kw)


@pytest.mark.parametrize("title", [
    "AI & Digital Transformation Conference 2026",
    "Cybersecurity & Data Protection Forum 2027",
    "Healthcare Innovation & Medical Technology Summit 2027",
    "Flutter Bootcamp: Learn App Development",
    "Intro to Robotics with Arduino",
    "ورشة برمجة للمبتدئين",
    "هاكاثون الذكاء الاصطناعي",
])
def test_tech_titles_are_tech(title):
    assert filters.is_tech_related(ev(title))


@pytest.mark.parametrize("title", [
    "Costume Party 2026",
    "Entrepreneurship & Startup Growth Summit 2027",
    "Getting The Most Out of Skills-Based Volunteering",
    "Fair trade coffee tasting",  # "ai" inside a word must not match
])
def test_non_tech_titles_are_not_tech(title):
    assert not filters.is_tech_related(ev(title))


def test_description_counts():
    assert filters.is_tech_related(ev("The Multiplier", description="Build a live app with AI"))


def test_in_person_outside_jordan_dropped():
    assert not filters.is_relevant(ev("Python Meetup", online=False, location="Berlin, Germany"))


def test_tech_only_sources_skip_keyword_check():
    assert filters.is_relevant(ev("Mastering Research Papers", source="gdg",
                                  online=False, location="Zarqa, Jordan"))


def test_gdg_fixture_events_all_kept(replay, frozen_today):
    replay("gdg")
    frozen_today(gdg)
    events = GDGScraper(delay_seconds=0).fetch()
    assert events and all(filters.is_relevant(e) for e in events)


def test_eventbrite_fixture_keeps_jordan_tech_events(replay, frozen_today):
    replay("eventbrite")
    frozen_today(filters)
    kept = {e.title for e in EventbriteScraper(delay_seconds=0).fetch() if filters.is_relevant(e)}
    assert "AI & Digital Transformation Conference 2026  Range Event Managment" in kept
    assert "Cybersecurity & Data Protection Forum 2027 Range Event Management" in kept
    assert "Costume Party 2026" not in kept
