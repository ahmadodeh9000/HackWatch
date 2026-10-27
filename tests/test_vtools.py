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
    # The fixture pages also contain 3 other-section events each, which must be skipped,
    # and "Best Poster Competition Report" is a report, not an event.
    assert len(events) == 14
    assert not any("Report" in e.title for e in events)
    assert all(e.country == "JO" and e.scope == "jordan" and "ieee" in e.tags for e in events)


def test_ieee_event_fields(replay, configured):
    by_url = {e.url: e for e in fetched(replay, configured)}
    pes = by_url["https://events.vtools.ieee.org/m/586685"]
    assert pes.title == "IEEE PES&IAS MEETING"
    assert pes.organizer == "Hashemite University, PE31/IA34"
    assert pes.start_date == "2026-11-05" and pes.mode == "in-person"
    assert pes.location == "Az Zarqa, Jordan"
    assert pes.type == "meetup"  # "MEETING"

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


def test_branch_key_groups_branch_chapters_and_affinity_groups():
    from hackwatch.scrapers.vtools import branch_key
    assert branch_key("STB25091") == branch_key("SBC25091A") == branch_key("SBA25091") == "branch-25091"
    assert branch_key("SBC61971D") == "branch-61971"
    assert branch_key("CH09455") == "CH09455"  # section chapters keep their own id
    assert branch_key(None) == ""


def test_cancelled_and_report_entries_are_skipped(monkeypatch):
    scraper = VToolsScraper(section_spoids=["R80079"], delay_seconds=0)
    host = {"section_spoids": "R80079", "spoid": "STB1", "name": "X"}

    def item(title, **kw):
        return {"attributes": {"id": len(title), "title": title, "primary-host": host,
                               "start-time": "2026-11-01T10:00:00Z", "location-type": "physical", **kw}}

    class Resp:
        def json(self):
            return {"meta": {"paging": {"total_pages": 1}}, "data": [
                item("IEEE Day"), item("Workshop Report"), item("تقرير ورشة"), item("Talk", cancelled=True)]}

    monkeypatch.setattr(scraper, "get", lambda *a, **k: Resp())
    assert [e.title for e in scraper.fetch()] == ["IEEE Day"]


def test_same_branch_same_day_listings_merge(replay, configured, tmp_path):
    from hackwatch import cli, db
    replay("ieee")
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    cli.run_fetch(conn, [configured("ieee")])
    events = db.get_events(conn, show_all=True)

    # Oct 27: two Yarmouk chapters (SBC25091A, SBC25091F) posted the same celebration.
    oct27 = [e for e in events if e.start_date == "2026-10-27"]
    assert len(oct27) == 1 and len(oct27[0].urls) == 2
    # Nov 1: the Yarmouk branch, its WIE group and its RA24 chapter all posted IEEE Day.
    nov1 = [e for e in events if e.start_date == "2026-11-01"]
    assert len(nov1) == 1 and len(nov1[0].urls) == 3
    assert len(events) == 11  # 14 listings - 1 - 2 merged
