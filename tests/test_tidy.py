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
