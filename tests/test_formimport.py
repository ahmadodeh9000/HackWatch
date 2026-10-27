"""hackwatch import-form: Google Form CSV -> manual_events.yaml."""
import csv

import pytest
from typer.testing import CliRunner

from hackwatch import cli
from hackwatch.formimport import clock_time, import_csv, tag_ids
from hackwatch.scrapers.manual import load_manual_events

# The question titles from CONTRIBUTING.md, as Google puts them in the CSV header.
HEADER = ["Timestamp", "Event title / اسم الفعالية", "Event link / رابط الفعالية", "Start date / تاريخ البدء",
          "End date / تاريخ الانتهاء", "Start time / وقت البدء", "End time / وقت الانتهاء",
          "Registration deadline / آخر موعد للتسجيل", "Format / طريقة الحضور", "City and venue / المدينة والمكان",
          "Organizer / الجهة المنظمة", "Event type / نوع الفعالية", "Tags / الوسوم", "Description / الوصف",
          "Your email (optional) / بريدك الإلكتروني (اختياري)"]


def row(**kw):
    base = {"Timestamp": "10/27/2026 14:03:11", "Event title": "Robot Sumo Cup", "Event link": "https://sumo.test/cup",
            "Start date": "2026-12-05", "End date": "", "Start time": "6:00:00 PM", "End time": "9:30:00 PM",
            "Registration deadline": "2026-12-01", "Format": "In-person / حضوري",
            "City and venue": "Hijjawi Faculty, Irbid", "Organizer": "IEEE YU", "Event type": "Competition / مسابقة",
            "Tags": "Robotics, Robot sumo, ieee", "Description": "Build a robot.", "Your email (optional)": "a@b.c"}
    base.update(kw)
    return [base[h.split(" / ")[0]] for h in HEADER]


def write_csv(tmp_path, rows):
    path = tmp_path / "responses.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    return path


@pytest.mark.parametrize("raw, clean", [("6:00:00 PM", "18:00"), ("9:30 am", "09:30"), ("18:00", "18:00"),
                                        ("18:00:00", "18:00"), ("noon", "noon")])
def test_clock_time(raw, clean):
    assert clock_time(raw) == clean


def test_tag_labels_and_ids():
    assert tag_ids("AI & ML, Robot sumo, ieee") == "ai, sumo, ieee"


def test_import_adds_valid_rows_and_skips_duplicates(tmp_path):
    yaml_path = tmp_path / "manual_events.yaml"
    yaml_path.write_text("# header comment\n- title: Already here\n  url: https://old.test/e\n  dates: 2026-12-10\n")
    csv_path = write_csv(tmp_path, [
        row(),
        row(**{"Event title": "Same link again", "Event link": "https://sumo.test/cup/?utm_source=wa"}),
        row(**{"Event title": "Old one", "Event link": "http://www.old.test/e"}),
        row(**{"Event title": "Bad date", "Event link": "https://bad.test", "Start date": "12/05/2026"}),
        row(**{"Event title": "Online talk", "Event link": "https://talk.test", "Format": "Online / عن بعد",
               "City and venue": "", "Start time": "", "End time": "", "Tags": "", "Event type": "Meetup / لقاء",
               "Registration deadline": ""}),
    ])
    result = import_csv(csv_path, yaml_path)

    assert result.added == ["Robot Sumo Cup", "Online talk"]
    assert result.duplicates == ["row 3: Same link again", "row 4: Old one"]
    assert result.errors == ["row 5 (Bad date): dates must be an ISO date like 2026-11-01, got '12/05/2026'"]
    text = yaml_path.read_text()
    assert text.startswith("# header comment\n- title: Already here")
    assert "# From the Google Form, submitted 10/27/2026 14:03:11" in text
    assert "a@b.c" not in text  # the submitter's email isn't copied
    events, errors = load_manual_events(yaml_path)
    assert errors == []
    sumo = {e.title: e for e in events}["Robot Sumo Cup"]
    assert (sumo.start_time, sumo.end_time, sumo.registration_deadline) == ("18:00", "21:30", "2026-12-01")
    assert sumo.tags == ["robotics", "sumo", "ieee"] and sumo.type == "competition"


def test_reimporting_the_same_csv_adds_nothing(tmp_path):
    yaml_path = tmp_path / "m.yaml"
    csv_path = write_csv(tmp_path, [row()])
    assert len(import_csv(csv_path, yaml_path).added) == 1
    again = import_csv(csv_path, yaml_path)
    assert again.added == [] and again.duplicates == ["row 2: Robot Sumo Cup"]


def test_cli_dry_run_and_exit_code(tmp_path):
    yaml_path = tmp_path / "m.yaml"
    yaml_path.write_text("")
    csv_path = write_csv(tmp_path, [row(), row(**{"Event link": "https://x.test", "Start time": "25:00"})])
    result = CliRunner().invoke(cli.app, ["import-form", str(csv_path), "--file", str(yaml_path), "--dry-run"])
    assert result.exit_code == 1  # one invalid row
    assert "Would add: Robot Sumo Cup" in result.output and "start_time must be a 24-hour time" in result.output
    assert yaml_path.read_text() == ""  # dry run changes nothing
