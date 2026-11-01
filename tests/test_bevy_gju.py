"""Bevy public pages (GDG, Startup Grind) and the GJU events calendar."""
from datetime import date

import pytest
import requests

from hackwatch.cli import apply_source_defaults
from hackwatch.filters import is_relevant
from hackwatch.scrapers import gju
from hackwatch.scrapers.bevy import parse_event_page, upcoming_event_links
from hackwatch.scrapers.gju import month_keys

CHAPTER = """<html><head><meta property="og:title" content="GDG Amman | Google Developer Groups"></head><body>
<h1>Upcoming events</h1>
<a href="/events/details/google-gdg-amman-presents-devfest-amman-2026/">View</a>
<a href="https://gdg.community.dev/events/details/google-gdg-amman-presents-devfest-amman-2026/">again</a>
<a href="/events/details/google-gdg-amman-presents-build-with-ai/cohost-gdg-amman">cohost</a>
<h1>Past events</h1>
<a href="/events/details/google-gdg-amman-presents-old-meetup/">old</a>
</body></html>"""


def test_only_upcoming_links_without_cohost_suffix_or_duplicates():
    assert upcoming_event_links(CHAPTER, "https://gdg.community.dev/", limit=10) == [
        "https://gdg.community.dev/events/details/google-gdg-amman-presents-devfest-amman-2026/",
        "https://gdg.community.dev/events/details/google-gdg-amman-presents-build-with-ai/",
    ]


def test_event_page_without_json_ld_is_skipped():
    assert parse_event_page("<html><body>no data</body></html>") is None


def test_startupgrind(replay, configured):
    replay("startupgrind")
    scraper = configured("startupgrind")
    (ev,) = scraper.fetch()
    apply_source_defaults(ev, scraper)
    assert ev.title == "Founders Day - Amman"
    assert ev.organizer == "Startup Grind Amman"
    assert (ev.start_date, ev.start_time) == ("2026-11-04", "18:30")
    assert ev.mode == "in-person" and ev.country == "JO"
    assert "startup" in ev.tags and ev.scope == "jordan"
    assert is_relevant(ev)  # no tech-keyword requirement for Startup Grind


def test_gju_month_pages_and_tech_filter(replay, frozen_today, configured):
    replay("gju")
    frozen_today(gju)
    scraper = configured("gju")
    events = {e.title: e for e in scraper.fetch()}
    assert len(events) == 8  # 3 month pages; ICFT spans several days but appears once
    icft = events["The International Conference on Future Technologies 2026 (ICFT 2026)"]
    assert (icft.start_date, icft.end_date) == ("2026-10-18", "2026-10-21")
    assert icft.url.startswith("https://www.gju.edu.jo/content/international-conference-future-technologies-2026")
    kept = sorted(t for t, e in events.items() if is_relevant(e, scraper.require_tech_keywords))
    assert kept == ["GJU Future TECH SUMMIT 2026", "The International Conference on Future Technologies 2026 (ICFT 2026)"]
    assert scraper.delay_seconds == 0  # tests; the real scraper waits 10 s (robots.txt Crawl-delay)


def test_gju_month_keys_wrap_the_year():
    assert month_keys(date(2026, 11, 30), 2) == ["2026-11", "2026-12", "2027-01"]


def test_own_chapter_comes_from_the_event_url():
    from hackwatch.scrapers.bevy import own_chapter
    chapters = ["gdg-aqaba", "gdg-amman"]
    base = "https://gdg.community.dev/events/details/"
    assert own_chapter(base + "google-gdg-aqaba-presents-devfest/", chapters) == "gdg-aqaba"
    assert own_chapter(base + "google-gdg-on-campus-sudan-university-of-science-technology-khartoum-sudan"
                              "-presents-stand-out-amp-connect-the-power-of-personal-branding/", chapters) is None
    assert own_chapter("https://www.startupgrind.com/events/details/startup-grind-amman-presents-x/", ["amman"]) == "amman"
    assert own_chapter(base + "no-host-here/", chapters) is None


def test_foreign_cohosted_events_are_skipped_and_never_requested(replay, configured):
    # GDG Aqaba's page lists two events by GDG on Campus Sudan University (.../cohost-gdg-aqaba).
    replay("gdg")
    events = configured("gdg").fetch()
    titles = {e.title for e in events}
    assert "Stand Out & Connect: the Power of Personal Branding" not in titles
    assert "From Awareness to Impact: Emotional Intelligence is the Key" not in titles
    assert not any("sudan" in e.url for e in events)


def test_organizer_is_the_events_own_chapter_not_the_page_it_was_found_on(monkeypatch):
    from hackwatch.scrapers.bevy import BevyScraper

    class Page:
        def __init__(self, text):
            self.text = text
    base = "https://gdg.community.dev/"
    event = base + "events/details/google-gdg-amman-presents-meetup/"
    pages = {
        base + "gdg-aqaba/": f'<meta property="og:title" content="GDG Aqaba | Google Developer Groups"><a href="{event}cohost-gdg-aqaba"></a>',
        base + "gdg-amman/": '<meta property="og:title" content="GDG Amman | Google Developer Groups">',
        event: '<script type="application/ld+json">{"@type":"Event","name":"Meetup","startDate":"2026-12-01T18:00:00+03:00",'
               '"eventAttendanceMode":"https://schema.org/OnlineEventAttendanceMode"}</script>',
    }
    scraper = BevyScraper(base, ["gdg-aqaba", "gdg-amman"], delay_seconds=0)
    monkeypatch.setattr(scraper, "get", lambda url, **kw: Page(pages[url]))
    (found,) = scraper.fetch()
    assert found.organizer == "GDG Amman"


def test_time_of_an_event_listed_in_another_zone_is_amman_time():
    from hackwatch.timeutil import local_date, local_time
    # The Sudan event's own page: 23:00–00:45 at +02:00 is 00:00–01:45 in Amman the next day.
    assert (local_date("2027-03-24T23:00:00+02:00"), local_time("2027-03-24T23:00:00+02:00")) == ("2027-03-25", "00:00")
    assert local_time("2027-03-25T00:45:00+02:00") == "01:45"


DEAD = "gdg-on-campus-al-hussein-technical-university-amman-jordan"


def test_one_chapter_404_is_skipped_and_the_others_kept(replay):
    # gdg_404: GDG Amman's real pages, and the chapter removed on GDG's side, recorded as a 404.
    from hackwatch.scrapers.bevy import BevyScraper
    replay("gdg_404")
    scraper = BevyScraper("https://gdg.community.dev", [DEAD, "gdg-amman"], delay_seconds=0)
    events = scraper.fetch()
    assert [e.title for e in events] == ["DevFest Amman 2026"] and events[0].organizer == "GDG Amman"
    assert [f["part"] for f in scraper.partial_failures] == [DEAD]
    assert "404" in scraper.partial_failures[0]["error"]


def test_all_chapters_failing_is_still_an_error(replay):
    from hackwatch.scrapers.bevy import BevyScraper
    replay("gdg_404")
    with pytest.raises(RuntimeError, match="all 1 chapter pages failed"):
        BevyScraper("https://gdg.community.dev", [DEAD], delay_seconds=0).fetch()


def test_partial_failure_reaches_the_report_and_keeps_the_source_ok(replay, tmp_path):
    from hackwatch import cli, db
    from hackwatch.scrapers.bevy import BevyScraper
    replay("gdg_404")
    scraper = BevyScraper("https://gdg.community.dev", [DEAD, "gdg-amman"], delay_seconds=0)
    scraper.name, scraper.default_scope = "gdg", "jordan"
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    _, (result,) = cli.run_fetch(conn, [scraper])
    row = result.summary()
    assert row["ok"] and row["kept"] == 1 and row["partial_failures"][0]["part"] == DEAD
    assert f"skipped {DEAD}" in cli.fetch_report_markdown([row])


def test_a_bad_event_page_only_loses_that_event(monkeypatch):
    from hackwatch.scrapers.bevy import BevyScraper
    base = "https://gdg.community.dev/"
    good = base + "events/details/google-gdg-amman-presents-good/"
    bad = base + "events/details/google-gdg-amman-presents-bad/"

    class Page:
        def __init__(self, text):
            self.text = text

    def get(url, **kw):
        if url == bad:
            raise requests.HTTPError("500")
        return Page({base + "gdg-amman/": f'<a href="{good}"></a><a href="{bad}"></a>',
                     good: '<script type="application/ld+json">{"@type":"Event","name":"Good","startDate":"2026-12-01T18:00:00+03:00"}</script>'}[url])
    scraper = BevyScraper(base, ["gdg-amman"], delay_seconds=0)
    monkeypatch.setattr(scraper, "get", get)
    assert [e.title for e in scraper.fetch()] == ["Good"]
    assert scraper.partial_failures[0]["part"] == "gdg-amman"


def test_gju_failed_month_is_skipped_and_all_failing_is_an_error(monkeypatch):
    scraper = gju.GJUScraper(delay_seconds=0)

    class Page:
        text = "<html></html>"

    def one_bad(url, **kw):
        if url.endswith("2026-12"):
            raise requests.HTTPError("500")
        return Page
    monkeypatch.setattr(scraper, "get", one_bad)
    assert scraper.fetch(date(2026, 11, 1)) == []
    assert [f["part"] for f in scraper.partial_failures] == ["2026-12"]

    scraper.partial_failures = []
    monkeypatch.setattr(scraper, "get", lambda url, **kw: (_ for _ in ()).throw(requests.HTTPError("500")))
    with pytest.raises(RuntimeError, match="all 3 months failed"):
        scraper.fetch(date(2026, 11, 1))


def test_gju_unreachable_site_fails_at_once(monkeypatch):
    calls = []

    def timeout(url, **kw):
        calls.append(url)
        raise requests.ConnectTimeout("no route")
    scraper = gju.GJUScraper(delay_seconds=0)
    monkeypatch.setattr(scraper, "get", timeout)
    with pytest.raises(requests.ConnectTimeout):
        scraper.fetch(date(2026, 11, 1))
    assert len(calls) == 1
