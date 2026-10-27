"""Registration deadlines and Amman start/end times: sources, manual YAML, form, ICS."""
import json
import textwrap

import pytest
from typer.testing import CliRunner

from hackwatch import cli
from hackwatch.ics import build_calendar
from hackwatch.models import Event, validate_time
from hackwatch.scrapers import ctftime, codeforces, josa
from hackwatch.scrapers.manual import load_manual_events
from scripts.issue_to_event import build_entry, parse_issue_form
from tests.test_issue_to_event import body


def fetched(replay, frozen_today, configured, source, *modules):
    replay(source)
    frozen_today(*modules)
    return {e.title: e for e in configured(source).fetch()}


def test_ctftime_and_codeforces_times_are_amman(replay, frozen_today, configured):
    sudo = fetched(replay, frozen_today, configured, "ctftime", ctftime)["Sudocrypt v16.0"]
    # 03:30 -> 15:30 UTC the next day = 06:30 -> 18:30 in Amman (UTC+3)
    assert (sudo.start_date, sudo.start_time, sudo.end_date, sudo.end_time) == ("2026-10-27", "06:30", "2026-10-28", "18:30")
    div3 = fetched(replay, frozen_today, configured, "codeforces", codeforces)["Codeforces Round 1131 (Div. 3)"]
    assert (div3.start_time, div3.end_time) == ("17:35", "19:50")


def test_gdg_and_josa_times(replay, frozen_today, configured):
    devfest = fetched(replay, frozen_today, configured, "gdg")["DevFest Amman 2026"]
    assert (devfest.start_time, devfest.end_time) == ("11:00", "19:00")
    assert devfest.registration_deadline is None  # no longer faked from the start date
    pcb = fetched(replay, frozen_today, configured, "josa", josa)["JOSA Workshop | Introduction to PCB Design"]
    assert (pcb.start_time, pcb.end_time, pcb.registration_deadline) == ("11:00", "17:00", None)


def test_ieee_times_in_amman_even_if_event_tz_differs(replay, configured):
    replay("ieee")
    gju = {e.url: e for e in configured("ieee").fetch()}["https://events.vtools.ieee.org/m/589111"]
    assert (gju.start_time, gju.end_time) == ("10:00", "13:00")  # 07:00-10:00 UTC, set as Europe/Istanbul


def test_devpost_deadline_is_the_submission_end(replay, configured):
    replay("devpost")
    nebius = {e.title: e for e in configured("devpost").fetch()}["Nebius x NVIDIA Global AI Hackathon"]
    assert nebius.registration_deadline == "2026-10-30" and nebius.start_time is None


@pytest.mark.parametrize("raw, clean", [("9:30", "09:30"), ("18:00", "18:00"), (" 07:05 ", "07:05")])
def test_validate_time(raw, clean):
    assert validate_time(raw) == clean


@pytest.mark.parametrize("raw", ["24:00", "6pm", "18.30", "18:7", ""])
def test_validate_time_rejects(raw):
    with pytest.raises(ValueError, match="24-hour time"):
        validate_time(raw)


def manual(tmp_path, extra):
    path = tmp_path / "m.yaml"
    path.write_text("- title: Talk\n  url: https://t\n  dates: 2026-11-10\n" + textwrap.indent(extra, "  "))
    return load_manual_events(path)


def test_manual_times_and_deadline(tmp_path):
    (ev,), errors = manual(tmp_path, "start_time: 18:00\nend_time: '21:00'\nregistration_deadline: 2026-11-08\n")
    assert errors == [] and (ev.start_time, ev.end_time, ev.registration_deadline) == ("18:00", "21:00", "2026-11-08")


@pytest.mark.parametrize("extra, message", [
    ("start_time: 6pm\n", "start_time must be a 24-hour time"),
    ("registration_deadline: 2026-11-12\n", "registration_deadline 2026-11-12 is after the event ends"),
    ("start_time: '18:00'\nend_time: '17:00'\n", "end_time 17:00 is not after start_time 18:00"),
])
def test_manual_rejects_bad_times(tmp_path, extra, message):
    events, errors = manual(tmp_path, extra)
    assert events == [] and message in errors[0]


def test_issue_form_times_and_deadline():
    text = body(**{"Start date": "2026-12-05"}) + (
        "\n\n### Start time / وقت البدء\n\n10:00\n\n### End time / وقت الانتهاء\n\n16:30"
        "\n\n### Registration deadline / آخر موعد للتسجيل\n\n2026-12-01")
    entry = build_entry(parse_issue_form(text))
    assert (entry["start_time"], entry["end_time"], entry["registration_deadline"]) == ("10:00", "16:30", "2026-12-01")


def test_cli_add_rejects_bad_time(tmp_path):
    result = CliRunner().invoke(cli.app, ["add", "--file", str(tmp_path / "m.yaml"), "-t", "X", "-u", "https://x",
                                          "-d", "2026-12-05", "-l", "Online", "-o", "me", "--type", "meetup",
                                          "--start-time", "7pm"])
    assert result.exit_code == 1 and "24-hour time" in result.output


def ics_props(event):
    lines = build_calendar([event]).replace("\r\n ", "").split("\r\n")
    return {l.split(":", 1)[0]: l.split(":", 1)[1] for l in lines[lines.index("BEGIN:VEVENT") + 1:lines.index("END:VEVENT")]}


def test_ics_timed_event_in_utc_and_deadline_in_description():
    p = ics_props(Event(title="CTF", url="https://c", source="manual", scope="jordan", id="x", start_date="2026-12-05",
                        end_date="2026-12-06", start_time="18:00", end_time="09:30", registration_deadline="2026-12-01"))
    assert p["DTSTART"] == "20261205T150000Z" and p["DTEND"] == "20261206T063000Z"
    assert "Registration closes: 2026-12-01" in p["DESCRIPTION"]


def test_ics_start_time_without_end_lasts_two_hours():
    p = ics_props(Event(title="Talk", url="https://t", source="manual", scope="jordan", id="y",
                        start_date="2026-12-05", start_time="18:00"))
    assert (p["DTSTART"], p["DTEND"]) == ("20261205T150000Z", "20261205T170000Z")


def test_export_has_times_and_deadline(tmp_path):
    from hackwatch import db
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, Event(title="Talk", url="https://t", source="manual", location="Amman, Jordan",
                                start_date="2099-01-01", start_time="18:00", registration_deadline="2098-12-30"))
    out = tmp_path / "e.json"
    CliRunner().invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"), "--out", str(out)])
    (rec,) = json.loads(out.read_text())
    assert (rec["start_time"], rec["end_time"], rec["registration_deadline"]) == ("18:00", None, "2098-12-30")


def test_low_signal_from_manual_yaml_and_kept_off_the_calendar(tmp_path):
    from hackwatch.ics import calendar_events
    (ev,), errors = manual(tmp_path, "low_signal: true\n")
    assert errors == [] and ev.low_signal is True
    _, errors = manual(tmp_path, "low_signal: maybe\n")
    assert "low_signal must be true or false" in errors[0]
    keep = Event(title="DevFest", url="https://d", source="gdg", scope="jordan", start_date="2099-01-01")
    club = Event(title="Kickoff", url="https://k", source="gdg", scope="jordan", start_date="2099-01-01", low_signal=True)
    assert [e.title for e in calendar_events([keep, club])] == ["DevFest"]
