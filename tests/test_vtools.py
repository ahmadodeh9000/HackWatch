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
    assert len(events) == 12
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

    # Nov 1: the Yarmouk branch, its WIE group and its RA24 chapter all posted IEEE Day.
    # (Two chapters' Oct 27 posts were merged the same way; see test_dedup.py.)
    nov1 = [e for e in events if e.start_date == "2026-11-01"]
    assert len(nov1) == 1 and len(nov1[0].urls) == 3
    assert len(events) == 10  # 12 listings, 3 of them merged into 1


def test_registration_deadline_midnight_means_the_day_before(replay, configured):
    by_url = {e.url: e for e in fetched(replay, configured)}
    # registration-end-time 2026-10-20T21:00Z = 00:00 on the 21st in Amman: closes end of the 20th.
    assert by_url["https://events.vtools.ieee.org/m/580512"].registration_deadline == "2026-10-20"
    # 2026-11-16T21:00Z, event on the 17th: closes the day before, not on the day.
    assert by_url["https://events.vtools.ieee.org/m/588216"].registration_deadline == "2026-11-16"
    # 2026-11-09T19:00Z = 22:00 in Amman: that same day.
    assert by_url["https://events.vtools.ieee.org/m/587642"].registration_deadline == "2026-11-09"
    assert by_url["https://events.vtools.ieee.org/m/589111"].registration_deadline is None


AAU_REPORT = ("The IEEE Student Branch at Amman Arab University (AAU) hosted an interactive exhibition booth during "
              "the IEEE Day celebration at AAU. The booth aimed to engage students.")


@pytest.mark.parametrize("text, report", [
    ("The workshop took place at the Faculty of Engineering.", True),
    ("The meeting was held on campus with 40 students.", True),
    ("أقيمت الفعالية في جامعة اليرموك", True),
    # Announcements: invitations, "hosted by", plain descriptions.
    ("Join us for a workshop hosted by IEEE Yarmouk.", False),
    ("A workshop organized by the student branch.", False),
    ("Last year's event was held in Amman; register now for this year's.", False),
    ("Meeting with the new PES&IAS Committee in Hashemite University", False),
    ("", False),
])
def test_reads_like_report(text, report):
    from hackwatch.scrapers.vtools import reads_like_report
    assert reads_like_report(text) is report


def test_past_tense_report_is_skipped(monkeypatch):
    from hackwatch.scrapers.vtools import reads_like_report
    assert reads_like_report(AAU_REPORT.replace("The booth aimed to engage students.", ""))
    host = {"section_spoids": "R80079", "name": "AAU"}
    item = lambda i, d: {"id": i, "attributes": {"title": "IEEE Booth", "description": d, "primary-host": host,
                                                 "start-time": "2026-11-27T05:51:00Z", "city": "Amman"}}
    scraper = VToolsScraper(section_spoids=["R80079"], delay_seconds=0)
    monkeypatch.setattr(scraper, "_page", lambda page: {"data": [
        item(1, "The Student Branch hosted a booth at the fair."), item(2, "Visit our booth at the fair!")]})
    assert [e.url.rsplit("/", 1)[-1] for e in scraper.fetch()] == ["2"]
