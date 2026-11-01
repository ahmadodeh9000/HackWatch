"""IEEE RAS UJ: sitemap + prerendered /e/ pages (recorded 2026-11-01)."""
from datetime import date

from hackwatch.cli import apply_source_defaults
from hackwatch.scrapers.rasuj import RasUjScraper, page_record, upcoming_pages

ARDUINO = "https://ras-uj.site/e/2026-11-12-arduino-fundamentals-applied-robotics"


def fetched(replay, configured):
    replay("rasuj")
    scraper = configured("rasuj")
    scraper.today = date(2026, 11, 1)
    events = scraper.fetch()
    for e in events:
        apply_source_defaults(e, scraper)
    return {e.url: e for e in events}


def test_arduino_workshop(replay, configured):
    e = fetched(replay, configured)[ARDUINO]
    assert e.title == "اساسيات الاردوينو والروبوتات التطبيقية"     # as written
    assert e.organizer == "IEEE RAS UJ" and e.scope == "jordan" and e.open_to == "students"
    assert {"robotics", "ieee"} <= set(e.tags) and e.type == "workshop"
    # starts_at 09:30 UTC is 12:30 in Amman.
    assert (e.start_date, e.end_date, e.start_time, e.end_time) == ("2026-11-12", "2026-11-12", "12:30", None)
    assert e.location == "Fikr AI Hub & Study House, Amman, Jordan" and e.country == "JO" and e.mode == "in-person"
    assert e.registration_url == "https://ras-uj.site/f/arduino-fundamentals-applied-robotics"
    assert not e.low_signal


def test_only_upcoming_arabic_pages_are_read():
    sitemap = ("<url><loc>https://ras-uj.site/</loc></url>"
               "<url><loc>https://ras-uj.site/e/2026-11-12-a</loc></url>"
               "<url><loc>https://ras-uj.site/en/e/2026-11-12-a</loc></url>"
               "<url><loc>https://ras-uj.site/e/2026-04-09-old</loc></url>"
               "<url><loc>https://ras-uj.site/f/2026-11-12-a</loc></url>")
    assert upcoming_pages(sitemap, date(2026, 11, 1)) == ["https://ras-uj.site/e/2026-11-12-a"]
    assert upcoming_pages(sitemap, date(2026, 11, 12)) == ["https://ras-uj.site/e/2026-11-12-a"]
    assert upcoming_pages(sitemap, date(2026, 11, 13)) == []


def build(**record):
    base = {"title_ar": "ورشة", "title_en": "A session", "kind": "workshop", "starts_at": "2026-12-01T09:00:00+00:00",
            "published": True}
    return RasUjScraper()._event("https://ras-uj.site/e/x", {**base, **record})


def test_kinds():
    assert build(kind="competition").type == "competition"
    assert build(kind="talk").type == "meetup" and build(kind="محاضرة").type == "meetup"
    assert build(kind="ورشة").type == "workshop" and build(kind="مسابقة").type == "competition"
    assert build(kind="something-new").type is None


def test_general_club_events_are_club_life_unless_technical():
    assert build(kind="event", title_ar="إفطار الأيتام", title_en="Iftar with orphans").low_signal is True
    assert build(kind="event", title_ar="يوم", title_en="Robotics open day").low_signal is None


def test_online_venue_and_end_time():
    e = build(venue="Online", ends_at="2026-12-01T10:30:00+00:00")
    assert (e.mode, e.location, e.country, e.end_time) == ("online", "Online", None, "13:30")


def test_no_venue_falls_back_to_the_city_and_no_link_means_no_registration():
    e = build()
    assert e.location == "Amman, Jordan" and e.registration_url is None


def test_unpublished_or_unreadable_pages_are_skipped(monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text
    pages = {RasUjScraper.sitemap_url: "<loc>https://ras-uj.site/e/2026-12-01-a</loc><loc>https://ras-uj.site/e/2026-12-02-b</loc>",
             "https://ras-uj.site/e/2026-12-01-a": '<script id="ev-data">{"event":{"title_ar":"x","starts_at":"2026-12-01T09:00:00+00:00","published":false}}</script>',
             "https://ras-uj.site/e/2026-12-02-b": "<html>no data</html>"}
    scraper = RasUjScraper(delay_seconds=0)
    scraper.today = date(2026, 11, 1)
    monkeypatch.setattr(scraper, "get", lambda url, **kw: Page(pages[url]))
    assert scraper.fetch() == []
    assert page_record("<html></html>") is None


def test_registration_url_reaches_the_export_and_share_page(tmp_path):
    from datetime import timedelta
    import json
    from typer.testing import CliRunner
    from hackwatch import cli, db
    from hackwatch.models import Event
    from hackwatch.pages import render_page
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    day = (date.today() + timedelta(days=9)).isoformat()
    event = Event(title="W", url="https://ras-uj.site/e/w", source="rasuj", start_date=day, location="Amman, Jordan",
                  registration_url="https://ras-uj.site/f/w", scope="jordan")
    db.upsert_event(conn, event)
    out = tmp_path / "e.json"
    assert CliRunner().invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"), "--out", str(out)]).exit_code == 0
    assert json.loads(out.read_text())[0]["registration_url"] == "https://ras-uj.site/f/w"
    assert 'href="https://ras-uj.site/f/w"' in render_page(event)
    assert "Register" not in render_page(Event(title="W", url="https://x/w", source="gdg", registration_url="javascript:alert(1)"))
