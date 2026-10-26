"""Type/tag inference from taxonomy.yaml, checked against real fixture titles."""
import pytest

from hackwatch.cli import apply_source_defaults
from hackwatch.infer import apply_defaults, infer_tags, infer_type, keyword_pattern
from hackwatch.models import VALID_EVENT_TYPES, Event
from hackwatch.scrapers import gdg, josa
from hackwatch.taxonomy import load_taxonomy


def ev(title, description=None, labels=(), **kw):
    return Event(title=title, url="https://x", source="test", description=description,
                 source_labels=list(labels), **kw)


@pytest.fixture
def fetched(replay, frozen_today, configured):
    """fetched("gdg") -> {title: event} after the same defaults/inference as a real fetch."""
    frozen_today(gdg, josa)

    def run(source):
        replay(source)
        scraper = configured(source)
        events = scraper.fetch()
        for e in events:
            apply_source_defaults(e, scraper)
        return {e.title: e for e in events}

    return run


# Real titles from tests/fixtures (recorded 2026-10-26).
@pytest.mark.parametrize("source, title, type_, tags", [
    ("devpost", "Nebius x NVIDIA Global AI Hackathon", "hackathon", ["ai"]),
    ("devpost", "OpenCV AI Competition 2026, powered by AWS", "competition", ["ai", "cloud", "iot"]),
    ("devpost", "Meta VR Start Developer Competition 2026", "competition", ["ai", "web", "ar-vr"]),
    # "Summit" would be a conference, but Devpost only allows hackathon/competition.
    ("devpost", "Syntax Summit", "hackathon", ["ai", "cloud"]),
    ("devpost", "DSH Hacks V2 ($100k+ in prizes!)", "hackathon", []),
    ("eventbrite", "AI & Digital Transformation Conference 2026  Range Event Managment", "conference", ["ai"]),
    ("eventbrite", "Cybersecurity & Data Protection Forum 2027 Range Event Management", "conference", ["security"]),
    ("eventbrite", "Pocket Gamer Connects Jordan 2026", "conference", ["game-dev"]),
    ("eventbrite", "IE Masterclass: Globalization trends. From trade wars to AI opportunities", "workshop", ["ai"]),
    # GDG: title first, then GDG's own event tags.
    ("gdg", "DevFest Amman 2026", "conference", ["ai", "web", "mobile", "cloud", "gdg"]),
    ("gdg", "🚀 Flutter Bootcamp: Learn App Development", "workshop", ["mobile", "gdg"]),
    ("gdg", "Mastering Research Papers: How to Read Them Effectively", "workshop", ["ai", "gdg"]),
    ("josa", "JOSA Workshop | Introduction to PCB Design", "workshop", ["embedded", "josa", "open-source"]),
    ("josa", "JOSA Treasure Hunt v2.0", "competition", ["josa", "open-source"]),
    ("josa", "Reclaim hackathon information session", "meetup", ["josa", "open-source"]),
    ("josa", "Hacktoberfest 2026 Amman", None, ["open-source", "josa"]),
])
def test_real_titles(fetched, source, title, type_, tags):
    event = fetched(source)[title]
    assert event.type == type_
    assert event.tags == tags


def test_gdg_mode_comes_from_audience_type(fetched):
    events = fetched("gdg")
    assert events["Mastering Research Papers: How to Read Them Effectively"].mode == "online"
    assert events["DevFest Amman 2026"].mode == "in-person"


def test_gdg_labels_decide_when_title_has_no_keyword():
    labels = ["Workshop / hands-on session"]
    assert infer_type(ev("Mastering Research Papers", labels=labels)) == "workshop"
    assert infer_type(ev("Mastering Research Papers", labels=["Conference", "Networking"])) == "conference"


def test_title_beats_labels_beats_description():
    assert infer_type(ev("Flutter Workshop", labels=["Conference"], description="a hackathon")) == "workshop"
    assert infer_type(ev("Flutter Day", labels=["Conference"], description="a hackathon")) == "conference"
    assert infer_type(ev("Flutter Day", description="come to our hackathon")) == "hackathon"


@pytest.mark.parametrize("title, type_, tags", [
    ("ورشة عمل في الذكاء الاصطناعي", "workshop", ["ai"]),
    ("هاكاثون الأمن السيبراني", "hackathon", ["security"]),
    ("مسابقة الروبوتات - سومو وتتبع الخط", "competition", ["robotics", "sumo", "line-follower"]),
    ("مؤتمر ريادة الأعمال", "conference", ["startup"]),
    ("محاضرة عن إنترنت الأشياء", "meetup", ["iot"]),
])
def test_arabic(title, type_, tags):
    event = ev(title)
    assert infer_type(event) == type_
    assert infer_tags(event) == tags


@pytest.mark.parametrize("title, type_, tags", [
    ("IEEE Robot Sumo Cup", "competition", ["robotics", "sumo", "ieee"]),
    ("Line Follower Challenge", "competition", ["line-follower"]),
    ("Codeforces Round #999 (Div. 2)", None, ["cp"]),
    ("PSUT CTF 2026", "competition", ["ctf"]),
    ("Intro to Arduino and ESP32", None, ["embedded"]),
])
def test_engineering_titles(title, type_, tags):
    event = ev(title)
    assert infer_type(event) == type_
    assert infer_tags(event) == tags


@pytest.mark.parametrize("text, keyword, hit", [
    ("DSH Hacks V2", "hack", True),
    ("Lifehacks", "hack", False),
    ("Fair trade", "ai", False),
    ("Build with AI", "ai", True),
    ("A hack-day in Amman", "hack day", True),
    ("الورشة الأولى", "ورشة", True),
])
def test_keyword_matching(text, keyword, hit):
    assert bool(keyword_pattern([keyword]).search(text)) is hit


def test_explicit_values_always_win():
    event = ev("Robot Sumo Hackathon", type="workshop", tags=["web"], scope="worldwide")
    apply_defaults(event, default_type="meetup", default_tags=["gdg"], default_scope="jordan")
    assert (event.type, event.tags, event.scope) == ("workshop", ["web", "gdg"], "worldwide")


def test_inferred_beats_source_default_and_default_fills_gaps():
    assert apply_defaults(ev("OpenCV Competition"), default_type="hackathon").type == "competition"
    assert apply_defaults(ev("Learn AR with SPECS"), default_type="hackathon").type == "hackathon"
    assert apply_defaults(ev("Something"), default_type=None).type is None  # stored as "other"


def test_allowed_types_restrict_inference():
    assert infer_type(ev("Syntax Summit"), allowed=["hackathon", "competition"]) is None
    assert infer_type(ev("Syntax Summit")) == "conference"


def test_taxonomy_rules_only_use_known_types_and_tags():
    taxonomy = load_taxonomy()
    assert {r["type"] for r in taxonomy["types"]} <= set(VALID_EVENT_TYPES)
    for tag, info in taxonomy["tags"].items():
        assert tag == tag.lower() and " " not in tag
        assert info.get("label"), f"{tag} needs a label"
