"""scripts/issue_to_event.py: issue form -> manual_events.yaml entry -> validate."""
import pytest
import yaml

from hackwatch.scrapers.manual import load_manual_events
from scripts.issue_to_event import append_entry, build_entry, main, parse_issue_form

# What GitHub puts in the issue body for the form in .github/ISSUE_TEMPLATE/event.yml.
BODY = """### Event title / اسم الفعالية

IEEE Robot Sumo Cup 2026

### Event link / رابط الفعالية

https://example.com/sumo?utm_source=insta

### Start date / تاريخ البدء

2026-12-05

### End date / تاريخ الانتهاء

2026-12-06

### Format / طريقة الحضور

In-person / حضوري

### City and venue / المدينة والمكان

Hijjawi Faculty, Irbid

### Organizer / الجهة المنظمة

IEEE YU Student Branch

### Event type / نوع الفعالية

Competition / مسابقة

### Tags / الوسوم

robotics, Sumo, IEEE

### Description / الوصف

Build a robot,
push the other one out. $(rm -rf /) `whoami`
"""


def body(**changes):
    """BODY with some field values replaced (by English label)."""
    text = BODY
    for label, value in changes.items():
        start = text.index(f"### {label}")
        value_start = text.index("\n\n", start) + 2
        value_end = text.find("\n\n###", value_start)
        value_end = len(text) if value_end == -1 else value_end
        text = text[:value_start] + value + text[value_end:]
    return text


def test_parse_issue_form():
    fields = parse_issue_form(BODY)
    assert fields["title"] == "IEEE Robot Sumo Cup 2026"
    assert fields["mode"] == "In-person / حضوري"
    assert fields["description"].startswith("Build a robot,\npush")


def test_build_entry():
    entry = build_entry(parse_issue_form(BODY))
    assert entry == {
        "title": "IEEE Robot Sumo Cup 2026",
        "url": "https://example.com/sumo",  # tracking param removed
        "dates": "2026-12-05 to 2026-12-06",
        "location": "Hijjawi Faculty, Irbid",
        "organizer": "IEEE YU Student Branch",
        "type": "competition",
        "mode": "in-person",
        "tags": ["robotics", "sumo", "ieee"],
        # shell syntax is just text here; it's never run
        "description": "Build a robot, push the other one out. $(rm -rf /) `whoami`",
    }


def test_no_response_and_online_defaults():
    entry = build_entry(parse_issue_form(body(**{
        "End date": "_No response_", "Format": "Online / عن بعد", "City and venue": "_No response_",
        "Tags": "_No response_", "Description": "_No response_"})))
    assert entry["dates"] == "2026-12-05" and entry["location"] == "Online" and entry["mode"] == "online"
    assert "tags" not in entry and "description" not in entry


@pytest.mark.parametrize("changes, message", [
    ({"Start date": "5/12/2026"}, "ISO date"),
    ({"Event type": "Party"}, "type must be one of"),
    ({"Tags": "robotics, juggling"}, "unknown tag"),
    ({"City and venue": "_No response_"}, "city and venue are required"),
    ({"Event link": "javascript:alert(1)"}, "must start with http"),
    ({"Event title": "x" * 300}, "title is too long"),
])
def test_invalid_submissions(changes, message):
    with pytest.raises(ValueError, match=message):
        build_entry(parse_issue_form(body(**changes)))


def test_append_keeps_existing_text(tmp_path):
    path = tmp_path / "manual_events.yaml"
    path.write_text("# Club events, newest last\n- title: Old\n  url: https://old.test\n  dates: 2026-11-01")
    append_entry(path, {"title": "New", "url": "https://new.test", "dates": "2026-12-01"}, "42")
    text = path.read_text()
    assert text.startswith("# Club events, newest last\n- title: Old\n")
    assert "# Submitted in issue #42\n- title: New\n" in text
    assert [e["title"] for e in yaml.safe_load(text)] == ["Old", "New"]


def run(tmp_path, monkeypatch, issue_body, existing=""):
    path = tmp_path / "manual_events.yaml"
    path.write_text(existing)
    monkeypatch.setenv("ISSUE_NUMBER", "7")
    monkeypatch.setenv("ISSUE_BODY", issue_body)
    monkeypatch.setenv("GITHUB_REPOSITORY", "ahmadodeh9000/HackWatch")
    code = main(["--yaml", str(path), "--out-dir", str(tmp_path / "out")])
    return code, path, tmp_path / "out"


def test_main_valid_submission_writes_pr_files(tmp_path, monkeypatch):
    code, path, out = run(tmp_path, monkeypatch, BODY)
    assert code == 0
    events, errors = load_manual_events(path)
    assert errors == [] and events[0].title == "IEEE Robot Sumo Cup 2026"
    assert (out / "pr-title.txt").read_text() == "Add event: IEEE Robot Sumo Cup 2026"
    assert "Closes #7" in (out / "pr-body.md").read_text()


def test_main_invalid_submission_writes_errors(tmp_path, monkeypatch):
    code, path, out = run(tmp_path, monkeypatch, body(**{"Start date": "next friday"}))
    assert code == 1
    assert "ISO date" in (out / "errors.md").read_text()
    assert path.read_text() == ""  # nothing added


def test_main_duplicate_url_is_caught_by_validate(tmp_path, monkeypatch):
    existing = "- title: Already here\n  url: https://example.com/sumo\n  dates: 2026-12-05\n"
    code, path, out = run(tmp_path, monkeypatch, BODY, existing)
    assert code == 1
    assert "duplicate url" in (out / "errors.md").read_text()
