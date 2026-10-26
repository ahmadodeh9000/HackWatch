"""iCalendar feed: RFC 5545 basics (CRLF, folding by octets, escaping, all-day dates)."""
from datetime import date

from typer.testing import CliRunner

from hackwatch import cli, db
from hackwatch.ics import build_calendar, calendar_events, escape_text, fold
from hackwatch.models import Event


def unfold(text: str):
    assert "\n" not in text.replace("\r\n", "")  # only CRLF line endings
    return text.replace("\r\n ", "").split("\r\n")


def unescape(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def ev(**kw):
    base = dict(title="Robot Sumo Cup", url="https://example.com/sumo", source="manual",
                start_date="2026-12-05", end_date="2026-12-06", location="Irbid, Jordan",
                scope="jordan", type="competition", tags=["robotics", "sumo"], id="abc123")
    base.update(kw)
    return Event(**base)


def props(calendar: str):
    """{property name: value} for the single event in the calendar."""
    lines = unfold(calendar)
    start, end = lines.index("BEGIN:VEVENT"), lines.index("END:VEVENT")
    result = {}
    for line in lines[start + 1:end]:
        name, value = line.split(":", 1)
        result[name] = value
    return result


def test_all_day_dates_with_exclusive_end():
    p = props(build_calendar([ev()]))
    assert p["DTSTART;VALUE=DATE"] == "20261205"
    assert p["DTEND;VALUE=DATE"] == "20261207"  # last day is the 6th
    one_day = props(build_calendar([ev(end_date=None)]))
    assert one_day["DTEND;VALUE=DATE"] == "20261206"


def test_stable_uid_and_fields():
    p = props(build_calendar([ev()]))
    assert p["UID"] == "abc123@hackwatch.ahmadodeh9000.github.io"
    assert p["URL"] == "https://example.com/sumo"
    assert p["CATEGORIES"] == "competition,robotics,sumo"
    assert p["LOCATION"] == "Irbid\\, Jordan"


def test_escaping_round_trips():
    tricky = 'Line one; with, commas\\backslash\nline two'
    assert unescape(escape_text(tricky)) == tricky
    p = props(build_calendar([ev(title="AI, Data; and \\ more", description="a\nb")]))
    assert unescape(p["SUMMARY"]) == "AI, Data; and \\ more"
    assert unescape(p["DESCRIPTION"]).startswith("a\nb\n")


def test_lines_are_folded_at_75_octets_even_for_arabic():
    long_arabic = "هاكاثون الذكاء الاصطناعي في عمّان " * 6
    text = build_calendar([ev(title=long_arabic, description="x" * 400)])
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert unescape(props(text)["SUMMARY"]) == long_arabic
    assert fold("short") == "short"


def test_calendar_wrapper_and_crlf():
    text = build_calendar([ev()])
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:")
    assert text.endswith("END:VCALENDAR\r\n")


def test_feed_has_jordan_events_and_keeps_recently_ended_ones():
    today = date(2026, 12, 10)
    events = [
        ev(title="Upcoming", start_date="2026-12-20", end_date=None),
        ev(title="Ended last week", start_date="2026-12-01", end_date="2026-12-03"),
        ev(title="Ended long ago", start_date="2026-09-01", end_date="2026-09-02"),
        ev(title="Worldwide CTF", scope="worldwide", start_date="2026-12-20"),
        ev(title="No date", start_date=None, end_date=None),
    ]
    assert [e.title for e in calendar_events(events, today=today)] == ["Upcoming", "Ended last week"]


def test_export_writes_ics(tmp_path):
    conn = db.get_connection(tmp_path / "t.db")
    db.init_db(conn)
    db.upsert_event(conn, ev(id=None, start_date=date.today().isoformat(), end_date=None))
    db.upsert_event(conn, ev(id=None, title="CTF", url="https://ctf.test", scope="worldwide", is_online=True,
                             location="Online", start_date=date.today().isoformat(), end_date=None))
    out = tmp_path / "events.ics"
    result = CliRunner().invoke(cli.app, ["export", "--db", str(tmp_path / "t.db"),
                                          "--out", str(tmp_path / "e.json"), "--ics", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_bytes().decode("utf-8")
    assert text.count("BEGIN:VEVENT") == 1 and "SUMMARY:Robot Sumo Cup" in text
    (merged,) = [e for e in db.get_events(conn, show_all=True) if e.title == "Robot Sumo Cup"]
    assert f"UID:{merged.id}@" in text
