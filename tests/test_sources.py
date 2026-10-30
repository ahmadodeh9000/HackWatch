"""sources.yaml loading, validation and scraper registry."""
import textwrap

import pytest

from hackwatch.scrapers import SCRAPERS, get_available_scrapers
from hackwatch.scrapers.bevy import BevyScraper
from hackwatch.sources import build_scraper, build_scrapers, load_sources, parse_source


def write(tmp_path, body):
    path = tmp_path / "sources.yaml"
    path.write_text(textwrap.dedent(body))
    return path


def test_registry_has_all_scrapers():
    assert set(SCRAPERS) >= {"devpost", "eventbrite", "bevy", "gju", "josa", "manual", "vtools", "ctftime", "codeforces"}
    assert SCRAPERS["bevy"] is BevyScraper


def test_repo_sources_yaml_builds_every_source():
    scrapers = {s.name: s for s in get_available_scrapers(include_disabled=True)}
    assert set(scrapers) == {"devpost", "eventbrite", "gdg", "startupgrind", "josa", "gju", "ieee", "ctftime",
                             "codeforces", "manual"}
    assert scrapers["ieee"].section_spoids == {"R80079"}
    assert scrapers["devpost"].default_scope == "worldwide" and scrapers["devpost"].default_type == "hackathon"
    assert scrapers["gdg"].default_tags == ["gdg"] and len(scrapers["gdg"].chapters) == 12
    assert scrapers["startupgrind"].chapters == ["amman"]
    assert sorted(n for n, s in scrapers.items() if s.require_tech_keywords) == ["eventbrite", "gju"]
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
          - {name: gdg-amman, scraper: bevy, scope: jordan, default_tags: [gdg],
             options: {base_url: "https://gdg.community.dev", chapters: [gdg-amman]}}
          - {name: sg, scraper: bevy, scope: jordan, options: {base_url: "https://www.startupgrind.com", chapters: [amman]}}
    """)
    a, b = build_scrapers(path)
    assert (a.name, a.chapters, b.name, b.chapters) == ("gdg-amman", ["gdg-amman"], "sg", ["amman"])
    assert BevyScraper.default_tags == []  # instance defaults don't leak into the class


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
    config = parse_source({"name": "gdg", "scraper": "bevy", "scope": "jordan",
                           "options": {"base_url": "https://gdg.community.dev", "chapter": ["gdg-amman"]}})
    with pytest.raises(ValueError, match=r"unknown option\(s\) chapter .*accepted: .*chapters"):
        build_scraper(config)


def test_missing_required_option():
    with pytest.raises(ValueError, match="source 'gdg': bevy needs chapters"):
        build_scraper(parse_source({"name": "gdg", "scraper": "bevy", "scope": "jordan",
                                    "options": {"base_url": "https://gdg.community.dev", "chapters": []}}))


def test_duplicate_names(tmp_path):
    path = write(tmp_path, """\
        sources:
          - {name: josa, scope: jordan}
          - {name: josa, scope: jordan}
    """)
    with pytest.raises(ValueError, match="duplicate source name"):
        load_sources(path)
