"""Optional facts: cost (free/paid), certificate (yes/no), open_to (anyone/students/members)."""
import pytest

from hackwatch import db
from hackwatch.models import Event
from hackwatch.scrapers.manual import parse_manual_item
from hackwatch.submissions import build_entry, parse_issue_form

ITEM = {"title": "Robot Sumo Cup", "url": "https://x/sumo", "dates": "2026-12-05", "location": "Irbid, Jordan"}


def test_manual_yaml_fields():
    e = parse_manual_item({**ITEM, "cost": "Free", "certificate": True, "open_to": "students"})
    assert (e.cost, e.certificate, e.open_to) == ("free", True, "students")
    e = parse_manual_item(ITEM)
    assert (e.cost, e.certificate, e.open_to) == (None, None, None)


@pytest.mark.parametrize("extra, message", [
    ({"cost": "cheap"}, "cost must be one of"),
    ({"open_to": "everyone"}, "open_to must be one of"),
    ({"certificate": "maybe"}, "certificate must be true or false"),
])
def test_manual_yaml_rejects_bad_values(extra, message):
    with pytest.raises(ValueError, match=message):
        parse_manual_item({**ITEM, **extra})


def form(cost, certificate, open_to):
    return ("### Event title / اسم الفعالية\n\nSumo\n\n### Event link / رابط الفعالية\n\nhttps://x/s\n\n"
            "### Start date / تاريخ البدء\n\n2026-12-05\n\n### Format / طريقة الحضور\n\nIn-person / حضوري\n\n"
            "### City and venue / المدينة والمكان\n\nIrbid\n\n### Organizer / الجهة المنظمة\n\nIEEE\n\n"
            "### Event type / نوع الفعالية\n\nCompetition / مسابقة\n\n"
            f"### Cost / التكلفة\n\n{cost}\n\n### Certificate / شهادة\n\n{certificate}\n\n"
            f"### Open to / الفعالية مفتوحة لـ\n\n{open_to}\n")


def test_issue_form_answers():
    entry = build_entry(parse_issue_form(form("Paid / مدفوع", "Yes / نعم", "Members / الأعضاء")))
    assert (entry["cost"], entry["certificate"], entry["open_to"]) == ("paid", True, "members")
    entry = build_entry(parse_issue_form(form("Not sure / غير متأكد", "No / لا", "_No response_")))
    assert "cost" not in entry and entry["certificate"] is False and "open_to" not in entry


def test_stored_and_merged(tmp_path):
    from datetime import date, timedelta
    day = (date.today() + timedelta(days=20)).isoformat()
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="Sumo", url="https://x/s", source="manual", start_date=day, certificate=False,
                                location="Irbid, Jordan"))
    db.upsert_event(conn, Event(title="Sumo", url="https://x/s", source="gdg", start_date=day, cost="free",
                                open_to="students", location="Irbid, Jordan"))
    (e,) = db.get_events(conn, show_all=True)
    assert (e.cost, e.certificate, e.open_to) == ("free", False, "students")


def test_bevy_price_gives_cost():
    from hackwatch.scrapers.bevy import _cost
    assert (_cost(0), _cost("15.00"), _cost(None), _cost("n/a")) == ("free", "paid", None, None)
