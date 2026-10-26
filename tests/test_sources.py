"""sources.yaml loading, validation and scraper registry."""
import textwrap

import pytest

from hackwatch.scrapers import SCRAPERS, get_available_scrapers
from hackwatch.scrapers.gdg import GDGScraper
from hackwatch.sources import build_scraper, build_scrapers, load_sources, parse_source


def write(tmp_path, body):
    path = tmp_path / "sources.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_registry_has_all_scrapers():
    assert set(SCRAPERS) >= {"devpost", "eventbrite", "gdg", "josa", "manual", "ctftime", "codeforces"}
    assert SCRAPERS["gdg"] is GDGScraper


def test_repo_sources_yaml_builds_every_source():
    scrapers = {s.name: s for s in get_available_scrapers(include_disabled=True)}
    assert set(scrapers) == {"devpost", "eventbrite", "gdg", "josa", "ctftime", "codeforces", "manual"}
    assert [n for n, s in scrapers.items() if s.require_tech_keywords] == ["eventbrite"]
    assert scrapers["devpost"].default_scope == "worldwide" and scrapers["devpost"].default_type == "hackathon"
    assert scrapers["gdg"].default_tags == ["gdg"] and len(scrapers["gdg"].chapter_ids) == 8
    worldwide = {n for n, s in scrapers.items() if s.default_scope == "worldwide"}
    assert worldwide == {"devpost", "ctftime", "codeforces"}
    assert all("/d/jordan/" in u for u in scrapers["eventbrite"].search_urls)


def test_disabled_sources_are_skipped(tmp_path):
    path = write(tmp_path, """\
        sources:
          - {name: josa, scope: jordan, enabled: false}
          - {name: devpost, scope: worldwide}
    """)
    assert [s.name for s in build_scrapers(path)] == ["devpost"]
    assert [s.name for s in build_scrapers(path, include_disabled=True)] == ["josa", "devpost"]


def test_same_scraper_twice_under_different_names(tmp_path):
    path = write(tmp_path, """\
        sources:
          - {name: gdg-amman, scraper: gdg, scope: jordan, default_tags: [gdg], options: {chapter_ids: [558]}}
          - {name: gdg-zarqa, scraper: gdg, scope: jordan, options: {chapter_ids: [2643]}}
    """)
    a, b = build_scrapers(path)
    assert (a.name, a.chapter_ids, b.name, b.chapter_ids) == ("gdg-amman", [558], "gdg-zarqa", [2643])
    assert GDGScraper.default_tags == []  # instance defaults don't leak into the class


@pytest.mark.parametrize("raw, message", [
    ({"scope": "jordan"}, "each source needs a name"),
    ({"name": "x", "scope": "jordan"}, "no scraper called 'x'"),
    ({"name": "josa"}, "scope is required"),
    ({"name": "josa", "scope": "mars"}, "scope must be one of"),
    ({"name": "josa", "scope": "jordan", "default_type": "party"}, "type must be one of"),
    ({"name": "josa", "scope": "jordan", "default_tags": ["juggling"]}, "unknown tag"),
    ({"name": "josa", "scope": "jordan", "colour": "red"}, "unknown key(s) colour"),
])
def test_invalid_entries(raw, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_source(raw)


def test_unknown_option_names_the_accepted_ones():
    config = parse_source({"name": "gdg", "scope": "jordan", "options": {"chapter_id": [1]}})
    with pytest.raises(ValueError, match=r"unknown option\(s\) chapter_id .*accepted: .*chapter_ids"):
        build_scraper(config)


def test_missing_required_option():
    with pytest.raises(ValueError, match="source 'gdg': gdg needs chapter_ids"):
        build_scraper(parse_source({"name": "gdg", "scope": "jordan"}))


def test_duplicate_names(tmp_path):
    path = write(tmp_path, """\
        sources:
          - {name: josa, scope: jordan}
          - {name: josa, scope: jordan}
    """)
    with pytest.raises(ValueError, match="duplicate source name"):
        load_sources(path)
