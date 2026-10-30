"""Clubs' calendars: the `ics` source, calendars.yaml and the calendar issue form."""
from datetime import date

import pytest
import yaml

from hackwatch.scrapers.ics import IcsScraper, events_from_ics, load_calendars, parse_ics, validate_calendar

CAL = {"name": "IEEE Example", "url": "https://calendar.google.com/calendar/ical/club%40group.calendar.google.com/public/basic.ics",
       "city": "Irbid"}
TODAY = date(2026, 11, 1)
ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:one@x\r
SUMMARY:Robotics Workshop\\, Part 1\r
DTSTART;TZID=Asia/Amman:20261110T100000\r
DTEND;TZID=Asia/Amman:20261110T140000\r
LOCATION:Hijjawi Faculty\r
DESCRIPTION:Bring a laptop.\\nRegister at https://example.com/robots now\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:utc@x\r
SUMMARY:Online AI Talk\r
DTSTART:20261112T160000Z\r
DTEND:20261112T170000Z\r
LOCATION:https://meet.google.com/abc\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:day@x\r
SUMMARY:Hack Weekend\r
DTSTART;VALUE=DATE:20261120\r
DTEND;VALUE=DATE:20261122\r
LOCATION:Amman\\, Jordan\r
URL:https://example.com/hack\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:past@x\r
SUMMARY:Last Year\r
DTSTART:20251112T160000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:off@x\r
SUMMARY:Cancelled Meetup\r
STATUS:CANCELLED\r
DTSTART:20261113T160000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:week@x\r
SUMMARY:Python Club\r
DTSTART;TZID=Asia/Amman:20261103T180000\r
DTEND;TZID=Asia/Amman:20261103T190000\r
RRULE:FREQ=WEEKLY;COUNT=3\r
EXDATE;TZID=Asia/Amman:20261110T180000\r
END:VEVENT\r
END:VCALENDAR\r
"""


def events():
    return {e.title: e for e in events_from_ics(ICS, CAL, "clubs", TODAY)}


def test_timed_event_in_amman_with_city_and_link_from_text():
    e = events()["Robotics Workshop, Part 1"]
    assert (e.start_date, e.start_time, e.end_time) == ("2026-11-10", "10:00", "14:00")
    assert e.location == "Hijjawi Faculty, Irbid, Jordan" and e.organizer == "IEEE Example" and e.country == "JO"
    assert e.url == "https://example.com/robots" and e.mode == "in-person"


def test_utc_times_and_online_location():
    e = events()["Online AI Talk"]
    assert (e.start_time, e.end_time, e.mode, e.location) == ("19:00", "20:00", "online", "Online")
    assert e.url.startswith("https://calendar.google.com/calendar/embed?src=club%40group.calendar.google.com")


def test_all_day_end_is_exclusive():
    e = events()["Hack Weekend"]
    assert (e.start_date, e.end_date, e.start_time, e.location) == ("2026-11-20", "2026-11-21", None, "Amman, Jordan")
    assert e.url == "https://example.com/hack"


def test_past_and_cancelled_are_left_out():
    assert not {"Last Year", "Cancelled Meetup"} & set(events())


def test_weekly_rule_expands_and_each_session_has_its_own_url():
    sessions = [e for e in events_from_ics(ICS, CAL, "clubs", TODAY) if e.title == "Python Club"]
    assert [s.start_date for s in sessions] == ["2026-11-03", "2026-11-17"]   # 10 Nov excluded
    assert len({s.url for s in sessions}) == 2


def test_folded_lines():
    (ev,) = parse_ics("BEGIN:VEVENT\r\nSUMMARY:Long\r\n  title\r\nEND:VEVENT\r\n")
    assert ev["SUMMARY"][1] == "Long title"


@pytest.mark.parametrize("entry, message", [
    ({"url": "https://x"}, "needs a name"),
    ({"name": "A", "url": "http://x"}, "must start with https"),
    ({"name": "A", "url": "https://x", "color": "red"}, "unknown key"),
])
def test_bad_calendar_entries(entry, message):
    with pytest.raises(ValueError, match=message):
        validate_calendar(entry)


def test_repo_calendars_file_is_valid():
    assert load_calendars("calendars.yaml") == []


def test_no_calendars_is_fine(tmp_path):
    assert IcsScraper(calendars_path=str(tmp_path / "none.yaml")).fetch() == []


FORM = """### Club or organization / النادي أو الجهة

IEEE Example

### Calendar link / رابط التقويم

{url}

### City / المدينة

Irbid

### Public page / الصفحة العامة

_No response_
"""


class Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def submit(tmp_path, monkeypatch, body, text=ICS):
    import scripts.issue_to_event as script
    monkeypatch.setattr(script.requests, "get", lambda *a, **k: Resp(text))
    monkeypatch.setenv("ISSUE_NUMBER", "12")
    monkeypatch.setenv("ISSUE_BODY", body)
    cal = tmp_path / "calendars.yaml"
    code = script.main(["--calendars", str(cal), "--yaml", str(tmp_path / "m.yaml"), "--out-dir", str(tmp_path / "o")])
    return code, cal


def test_issue_form_adds_calendar(tmp_path, monkeypatch):
    code, cal = submit(tmp_path, monkeypatch, FORM.format(url=CAL["url"]))
    assert code == 0
    assert yaml.safe_load(cal.read_text()) == [{"name": "IEEE Example", "url": CAL["url"], "city": "Irbid"}]
    assert "Closes #12" in (tmp_path / "o" / "pr-body.md").read_text()
    code, _ = submit(tmp_path, monkeypatch, FORM.format(url=CAL["url"]))   # again: duplicate
    assert code == 1 and "already connected" in (tmp_path / "o" / "errors.md").read_text()


def test_issue_form_rejects_a_page_that_is_not_a_calendar(tmp_path, monkeypatch):
    code, cal = submit(tmp_path, monkeypatch, FORM.format(url="https://example.com/"), text="<html>hello</html>")
    assert code == 1 and not cal.exists()
    assert "isn't an iCal" in (tmp_path / "o" / "errors.md").read_text()
    code, _ = submit(tmp_path, monkeypatch, FORM.format(url="http://example.com/a.ics"))
    assert code == 1 and "https://" in (tmp_path / "o" / "errors.md").read_text()
