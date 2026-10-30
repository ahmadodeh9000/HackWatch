"""Junk location parts and ALL-CAPS titles (display only)."""
from datetime import date, timedelta

import pytest

from hackwatch import db
from hackwatch.models import Event
from hackwatch.tidy import clean_location, display_title


@pytest.mark.parametrize("raw, clean", [
    ("E, Amman, Jordan", "Amman, Jordan"),                         # vTools building letter
    ("B2, Irbid", "Irbid"),
    ("TBA, King Hussein Business Park, Amman", "King Hussein Business Park, Amman"),
    ("Jordan, Yarmouk University , Irbid, Jordan, Jordan, 21110", "Yarmouk University, Irbid, Jordan"),
    ("The University of Jordan – Aqaba, Aqaba, Jordan", "The University of Jordan – Aqaba, Aqaba, Jordan"),
    ("Online", "Online"),
    ("عمّان", "عمّان"),
    ("E", "E"),   # nothing better to fall back to
])
def test_clean_location(raw, clean):
    assert clean_location(raw) == clean


@pytest.mark.parametrize("raw, shown", [
    ("MCC ROBOTICS ON PROESTHICS WORKSHOP", "MCC Robotics on Proesthics Workshop"),
    ("IEEE DAY 2026 – YARMOUK UNIVERSITY", "IEEE Day 2026 – Yarmouk University"),
    ("IEEE PES&IAS MEETING", "IEEE PES&IAS Meeting"),
    # Left alone: names, mixed case, Arabic.
    ("PINK+ CTF 2026", "PINK+ CTF 2026"),
    ("HKCERT CTF 2026 (Qualifying Round)", "HKCERT CTF 2026 (Qualifying Round)"),
    ("IEEE Day UJ-Aq", "IEEE Day UJ-Aq"),
    ("هاكاثون الذكاء الاصطناعي", "هاكاثون الذكاء الاصطناعي"),
])
def test_display_title(raw, shown):
    assert display_title(raw) == shown


def test_location_is_cleaned_when_stored(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="MCC ROBOTICS ON PROESTHICS WORKSHOP", url="https://x/1", source="ieee",
                                start_date=(date.today() + timedelta(days=30)).isoformat(), location="E, Amman, Jordan", mode="in-person"))
    (ev,) = db.get_events(conn, show_all=True)
    assert ev.location == "Amman, Jordan"
    assert ev.title == "MCC ROBOTICS ON PROESTHICS WORKSHOP"   # stored as the source wrote it


@pytest.mark.parametrize("location, mode, city", [
    ("Princess Sumaya University for Technology, Amman, Jordan", "in-person", "amman"),
    ("AlHussein Technical University (Soft Area), عمّان, Jordan", "in-person", "amman"),
    ("Az Zarqa, Jordan", "in-person", "zarqa"),
    ("The University of Jordan – Aqaba, Aqaba, Jordan", "in-person", "aqaba"),
    ("Al-Balqa Applied University, Salt, Jordan", "hybrid", "salt"),
    ("إربد", "in-person", "irbid"),
    ("Mafraq, Jordan", "in-person", None),
    ("Online", "online", None),
])
def test_city_of(location, mode, city):
    from hackwatch.tidy import city_of
    assert city_of(Event(title="x", url="https://x", source="manual", location=location, mode=mode,
                         scope="jordan")) == city


@pytest.mark.parametrize("raw, shown", [
    ("GDG on Campus Al-Zaytoonah University of Jordan - Amman , Jordan", "GDG on Campus Al-Zaytoonah University of Jordan"),
    ("GDG on Campus Al-Balqa' Applied University - Salt, Jordan", "GDG on Campus Al-Balqa' Applied University"),
    ("GDG Amman", "GDG Amman"),
    ("Amman Arab University - Jordan,PE31", "Amman Arab University - Jordan,PE31"),
    ("The University of Jordan-Aqaba", "The University of Jordan-Aqaba"),
    ("University - Dubai, UAE", "University - Dubai, UAE"),
])
def test_shown_organizer(raw, shown):
    from hackwatch.tidy import shown_organizer
    event = Event(title="x", url="https://x", source="gdg", organizer=raw)
    assert shown_organizer(event) == shown and event.organizer == raw


def test_export_keeps_stored_organizer_and_adds_display_one(tmp_path):
    import json
    from typer.testing import CliRunner
    from hackwatch import cli
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="Talk", url="https://x/1", source="gdg", location="Online", mode="online",
                                start_date=(date.today() + timedelta(days=9)).isoformat(),
                                organizer="GDG on Campus X University - Amman , Jordan"))
    out = tmp_path / "e.json"
    assert CliRunner().invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"), "--out", str(out)]).exit_code == 0
    (rec,) = json.loads(out.read_text())
    assert rec["organizer"] == "GDG on Campus X University - Amman , Jordan"
    assert rec["display_organizer"] == "GDG on Campus X University"


def test_devpost_deadline_says_submissions_on_page_and_calendar():
    from hackwatch.ics import event_lines
    from hackwatch.pages import render_page
    dev = Event(title="Hack", url="https://d/1", source="devpost", start_date="2026-11-01", end_date="2026-11-20",
                registration_deadline="2026-11-20", location="Online", mode="online")
    assert "Submissions close Fri 20 Nov 2026" in render_page(dev)
    assert "Submissions close: 2026-11-20" in "".join(event_lines(dev))
    ieee = Event(title="T", url="https://i/1", source="ieee", start_date="2026-11-21", registration_deadline="2026-11-20")
    assert "Registration closes Fri 20 Nov 2026" in render_page(ieee)
