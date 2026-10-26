import pytest
import requests

from hackwatch.cli import apply_source_defaults
from hackwatch.scrapers.vtools import VToolsScraper


def fetched(replay, configured):
    replay("ieee")
    scraper = configured("ieee")
    events = scraper.fetch()
    for e in events:
        apply_source_defaults(e, scraper)
    return events


def test_only_jordan_section_events_are_kept(replay, configured):
    events = fetched(replay, configured)
    # The fixture pages also contain 3 other-section events each, which must be skipped.
    assert len(events) == 15
    assert all(e.country == "JO" and e.scope == "jordan" and "ieee" in e.tags for e in events)


def test_ieee_event_fields(replay, configured):
    by_url = {e.url: e for e in fetched(replay, configured)}
    pes = by_url["https://events.vtools.ieee.org/m/586685"]
    assert pes.title == "IEEE PES&IAS MEETING"
    assert pes.organizer == "Hashemite University, PE31/IA34"
    assert pes.start_date == "2026-11-05" and pes.mode == "in-person"
    assert pes.location == "Az Zarqa, Jordan"

    bau = by_url["https://events.vtools.ieee.org/m/587642"]
    assert bau.location == "Amman, Jordan"  # source had "amman"
    assert bau.type == "meetup"             # "(IEEE Day)" in the title

    day = by_url["https://events.vtools.ieee.org/m/582932"]
    assert day.title == "IEEE Day 2026" and day.type == "meetup"


def test_needs_a_section():
    with pytest.raises(ValueError, match="section_spoids"):
        VToolsScraper(section_spoids=[])


def test_cohost_section_counts():
    scraper = VToolsScraper(section_spoids=["R80079"])
    assert scraper._in_sections({"primary-host": {"section_spoids": "R90729"},
                                 "cohosts": [{"section_spoids": "R80079"}]})
    assert not scraper._in_sections({"primary-host": {"section_spoids": "R90729"}, "cohosts": []})


def test_slow_page_is_retried_once(monkeypatch):
    scraper = VToolsScraper(section_spoids=["R80079"], delay_seconds=0)
    calls = []

    class Resp:
        def json(self):
            return {"meta": {"paging": {"total_pages": 1}}, "data": []}

    def get(url, params=None):
        calls.append(params["page"])
        if len(calls) == 1:
            raise requests.Timeout("slow")
        return Resp()

    monkeypatch.setattr(scraper, "get", get)
    assert scraper.fetch() == []
    assert calls == [1, 1]
