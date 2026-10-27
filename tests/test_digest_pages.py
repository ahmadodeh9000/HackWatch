"""Weekly digest and per-event share pages."""
import html
import re
from datetime import date

from typer.testing import CliRunner

from hackwatch import cli, db
from hackwatch.digest import build_digest, event_page_url, to_markdown, to_text
from hackwatch.models import Event
from hackwatch.pages import render_page, summary_line, write_pages

TODAY = date(2026, 10, 27)


def ev(title, start, **kw):
    base = dict(url=f"https://x.test/{abs(hash(title))}", source="manual", scope="jordan", mode="in-person",
                location="Hijjawi Faculty, Irbid, Jordan", type="meetup", id=f"id{abs(hash(title)) % 10**8}")
    base.update(kw)
    return Event(title=title, start_date=start, **base)


EVENTS = [
    ev("IEEE Day 2026", "2026-11-01", start_time="10:00"),
    ev("Flutter Bootcamp", "2026-10-31", start_time="09:00", type="workshop"),
    ev("Officers Kickoff", "2026-10-29", low_signal=True),               # club life: left out
    ev("Codeforces Round", "2026-10-30", scope="worldwide", mode="online"),  # not Jordan
    ev("DevFest Amman 2026", "2026-11-28", registration_deadline="2026-11-02", type="conference"),
    ev("Next month", "2026-11-20"),
    ev("Already over", "2026-10-20"),
]


def test_digest_picks_this_week_and_closing_deadlines():
    d = build_digest(EVENTS, today=TODAY)
    assert (d.start, d.end) == (date(2026, 10, 27), date(2026, 11, 2))
    assert [e.title for e in d.this_week] == ["Flutter Bootcamp", "IEEE Day 2026"]
    assert [e.title for e in d.closing] == ["DevFest Amman 2026"]


def test_text_digest_is_short_lines_one_link_per_event():
    text = to_text(build_digest(EVENTS, today=TODAY))
    assert text.startswith("📅 This week in Jordan tech\nهذا الأسبوع في فعاليات التقنية بالأردن\n27 Oct – 2 Nov\n")
    assert "  Sat 31 Oct, 09:00 · Hijjawi Faculty, Irbid · workshop\n" in text
    assert "⏳ Registration closing soon" in text and "DevFest Amman 2026 (closes Mon 2 Nov)" in text
    event_links = [l for l in text.splitlines() if "/e/" in l]
    assert len(event_links) == 3  # 2 this week + 1 closing
    assert max(len(l) for l in text.splitlines() if "http" not in l) <= 80
    assert "Officers Kickoff" not in text and "Codeforces" not in text


def test_markdown_digest_and_empty_week():
    md = to_markdown(build_digest(EVENTS, today=TODAY))
    assert md.startswith("# This week in Jordan tech")
    assert "- **[IEEE Day 2026](https://ahmadodeh9000.github.io/HackWatch/e/" in md
    empty = to_text(build_digest([], today=TODAY))
    assert "No events listed for this week yet." in empty and "Add yours" in empty


def test_event_page_open_graph_and_escaping():
    e = ev('AI & "Data" <Night>', "2026-11-28", end_date="2026-11-29", start_time="11:00",
           description="Talks & demos.", registration_deadline="2026-11-20", organizer="GDG Amman")
    page = render_page(e)
    meta = dict(re.findall(r'<meta property="(og:[a-z_:]+)" content="([^"]*)"', page))
    assert html.unescape(meta["og:title"]) == 'AI & "Data" <Night>'
    assert html.unescape(meta["og:description"]) == \
        "Sat 28 Nov 2026 – Sun 29 Nov, 11:00 · Hijjawi Faculty, Irbid · Meetup. Talks & demos."
    assert meta["og:url"] == event_page_url(e) and meta["og:image"].endswith("/og.png")
    assert "<Night>" not in page  # escaped in the body too
    assert 'href="https://x.test/' in page and "Registration closes Fri 20 Nov 2026" in page


def test_online_summary_and_bad_url_falls_back_to_site():
    e = ev("Webinar", "2026-11-05", mode="online", type="other", url="javascript:alert(1)")
    assert summary_line(e) == "Thu 5 Nov 2026 · Online · Event"
    assert 'href="javascript:' not in render_page(e)


def test_write_pages_replaces_old_ones_and_ids_are_stable(tmp_path):
    out = tmp_path / "e"
    out.mkdir()
    (out / "gone.html").write_text("old")
    assert write_pages(EVENTS[:2], out) == 2
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{e.id}.html" for e in EVENTS[:2])
    # The merged-event id depends only on the URL, so a page keeps its address across runs.
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="A", url="https://a.test/e?utm_source=x", source="manual",
                                location="Amman, Jordan", start_date="2099-01-01"))
    first = db.get_events(conn, show_all=True)[0].id
    db.upsert_event(conn, Event(title="A (renamed)", url="https://www.a.test/e/", source="manual",
                                location="Amman, Jordan", start_date="2099-01-01"))
    assert db.get_events(conn, show_all=True)[0].id == first


def test_cli_digest_and_export_options(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="Soon", url="https://s.test", source="manual", location="Amman, Jordan",
                                start_date=date.today().isoformat(), start_time="18:00"))
    runner = CliRunner()
    result = runner.invoke(cli.app, ["digest", "--db", str(tmp_path / "t.db"), "--format", "markdown"])
    assert result.exit_code == 0 and "[Soon](" in result.output
    assert runner.invoke(cli.app, ["digest", "--db", str(tmp_path / "t.db"), "-f", "pdf"]).exit_code == 1
    result = runner.invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"), "--out", str(tmp_path / "e.json"),
                                     "--digest", str(tmp_path / "digest.txt"), "--pages", str(tmp_path / "e")])
    assert result.exit_code == 0, result.output
    assert "• Soon" in (tmp_path / "digest.txt").read_text()
    assert len(list((tmp_path / "e").glob("*.html"))) == 1
