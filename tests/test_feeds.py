"""Event JSON-LD on share pages, sitemap.xml and the Atom feed."""
import json
import re
from datetime import date
from xml.etree import ElementTree as ET

from typer.testing import CliRunner

from hackwatch.feeds import build_feed, build_sitemap, event_jsonld, first_seen_dates
from hackwatch.models import Event
from hackwatch.pages import render_page

ATOM = "{http://www.w3.org/2005/Atom}"


def ev(title="DevFest Amman", url="https://x.test/d", **kw):
    kw.setdefault("start_date", "2026-11-28")
    kw.setdefault("scope", "jordan")
    kw.setdefault("location", "King Hussein Business Park, Amman, Jordan")
    return Event(title=title, url=url, source="gdg", **kw)


def test_jsonld_in_person_with_times():
    data = event_jsonld(ev(start_time="11:00", end_time="19:00", organizer="GDG Amman", cost="free", mode="in-person"))
    assert data["@type"] == "Event" and data["startDate"] == "2026-11-28T11:00:00+03:00"
    assert data["endDate"] == "2026-11-28T19:00:00+03:00" and data["isAccessibleForFree"] is True
    assert data["location"]["name"] == "King Hussein Business Park"
    assert data["eventAttendanceMode"].endswith("OfflineEventAttendanceMode")
    assert data["organizer"]["name"] == "GDG Amman"


def test_jsonld_online_and_all_day():
    data = event_jsonld(ev(mode="online", location="Online"))
    assert data["location"]["@type"] == "VirtualLocation" and data["startDate"] == "2026-11-28"


def test_page_jsonld_parses_and_cannot_break_out_of_the_script():
    page = render_page(ev(title="Hack</script><script>alert(1)</script>", description="a<b"))
    (body,) = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert json.loads(body)["name"].startswith("Hack</script>")
    assert "alert(1)</script>" not in page.split("</title>")[1].split("<style>")[0]


def test_sitemap():
    root = ET.fromstring(build_sitemap([ev()], site="https://s.test/H/"))
    locs = [u[0].text for u in root]
    assert locs[0] == "https://s.test/H/" and locs[1].startswith("https://s.test/H/e/") and locs[1].endswith(".html")


def test_feed_new_first_jordan_only_stable_dates():
    old, new = ev(title="Old", url="https://x.test/o"), ev(title="New", url="https://x.test/n")
    club = ev(title="Inauguration", url="https://x.test/c", low_signal=True)
    world = ev(title="World CTF", url="https://x.test/w", scope="worldwide", mode="online", location="Online")
    xml = build_feed([old, new, club, world], {old.id: "2026-10-01"}, today=date(2026, 10, 30))
    entries = ET.fromstring(xml).findall(ATOM + "entry")
    assert [e.find(ATOM + "title").text for e in entries] == ["New", "Old"]
    assert entries[1].find(ATOM + "published").text == "2026-10-01T00:00:00Z"
    assert entries[0].find(ATOM + "published").text == "2026-10-30T00:00:00Z"
    # Same input the next day: an event already listed keeps its date.
    assert build_feed([old], {old.id: "2026-10-01"}, today=date(2026, 11, 5)) == build_feed([old], {old.id: "2026-10-01"}, today=date(2026, 11, 9))


def test_first_seen_covers_series_sessions():
    seen = first_seen_dates([{"id": "a", "first_seen": "2026-10-01", "sessions": [{"id": "a"}, {"id": "b"}]},
                             {"id": "c"}])
    assert seen == {"a": "2026-10-01", "b": "2026-10-01"}


def test_export_writes_and_carries_first_seen(tmp_path):
    from hackwatch import cli, db
    from datetime import timedelta
    day = (date.today() + timedelta(days=20)).isoformat()
    db_path = tmp_path / "t.db"
    conn = db.get_connection(db_path)
    db.init_db(conn)
    db.upsert_event(conn, ev(start_date=day))
    (stored,) = db.get_events(conn, show_all=True)
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps([{"id": stored.id, "first_seen": "2026-01-02"}]))
    out = tmp_path / "events.json"
    result = CliRunner().invoke(cli.app, ["export", "--db", str(db_path), "--out", str(out), "--previous", str(prev),
                                          "--sitemap", str(tmp_path / "s.xml"), "--feed", str(tmp_path / "f.xml")])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())[0]["first_seen"] == "2026-01-02"
    assert "2026-01-02" in (tmp_path / "f.xml").read_text() and stored.id in (tmp_path / "s.xml").read_text()
