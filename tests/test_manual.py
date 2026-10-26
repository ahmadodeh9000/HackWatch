"""Invalid manual_events.yaml entries: skipped by the daily fetch, rejected by `validate`."""
import textwrap

import pytest
from typer.testing import CliRunner

from hackwatch import cli
from hackwatch.scrapers.manual import ManualScraper

runner = CliRunner()

GOOD = """\
- title: Good
  url: https://example.com/good
  dates: 2026-11-01
"""


def yaml_with(tmp_path, broken_entry: str):
    path = tmp_path / "manual_events.yaml"
    path.write_text(GOOD + textwrap.dedent(broken_entry))
    return path


BROKEN = [
    ("bad date", "- title: Broken\n  url: https://example.com/b\n  dates: 11/01/2026\n",
     "entry #2 (Broken): dates must be an ISO date"),
    ("impossible date", "- title: Broken\n  url: https://example.com/b\n  start_date: 2026-02-30\n",
     "entry #2 (Broken): start_date must be an ISO date"),
    ("end before start", "- title: Broken\n  url: https://example.com/b\n  dates: 2026-11-05 to 2026-11-01\n",
     "entry #2 (Broken): end date 2026-11-01 is before start date"),
    ("unknown tag", "- title: Broken\n  url: https://example.com/b\n  tags: [ai, juggling]\n",
     "entry #2 (Broken): unknown tag(s) 'juggling'"),
    ("unknown type", "- title: Broken\n  url: https://example.com/b\n  type: party\n",
     "entry #2 (Broken): type must be one of"),
    ("bad mode", "- title: Broken\n  url: https://example.com/b\n  mode: maybe\n",
     "entry #2 (Broken): mode must be one of"),
    ("missing url", "- title: Broken\n", "entry #2 (Broken): title and url are required"),
    ("missing title", "- url: https://example.com/b\n", "entry #2 (untitled): title and url are required"),
    ("not a mapping", "- just a string\n", "entry #2: expected a mapping, got str"),
    ("duplicate url", "- title: Again\n  url: https://EXAMPLE.com/good/\n",
     "entry #2 (Again): duplicate url, same as entry #1"),
]


@pytest.mark.parametrize("name, entry, message", BROKEN, ids=[b[0] for b in BROKEN])
def test_fetch_skips_invalid_entry_loudly(tmp_path, capsys, monkeypatch, name, entry, message):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    scraper = ManualScraper(yaml_path=yaml_with(tmp_path, entry))

    events = scraper.fetch()

    assert [e.title for e in events] == ["Good"]  # the valid entry still imports
    assert len(scraper.errors) == 1 and message in scraper.errors[0]
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("name, entry, message", BROKEN, ids=[b[0] for b in BROKEN])
def test_validate_fails_on_invalid_entry(tmp_path, name, entry, message):
    result = runner.invoke(cli.app, ["validate", "--file", str(yaml_with(tmp_path, entry))])
    assert result.exit_code == 1
    assert message in result.output
    assert "1 invalid, 1 valid entries" in result.output


def test_fetch_uses_github_annotation_in_ci(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    path = yaml_with(tmp_path, "- title: Broken\n")
    ManualScraper(yaml_path=path).fetch()
    assert capsys.readouterr().err.startswith(f"::error file={path}::entry #2 (Broken)")


def test_validate_passes_on_valid_file(tmp_path):
    path = tmp_path / "manual_events.yaml"
    path.write_text(GOOD)
    result = runner.invoke(cli.app, ["validate", "--file", str(path)])
    assert result.exit_code == 0
    assert "all 1 entries are valid" in result.output


def test_validate_reports_yaml_syntax_error(tmp_path):
    path = tmp_path / "manual_events.yaml"
    path.write_text("- title: [unclosed\n")
    result = runner.invoke(cli.app, ["validate", "--file", str(path)])
    assert result.exit_code == 1 and "not valid YAML" in result.output


def test_validate_missing_file(tmp_path):
    result = runner.invoke(cli.app, ["validate", "--file", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1 and "does not exist" in result.output


def test_repo_manual_events_file_is_valid():
    result = runner.invoke(cli.app, ["validate"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("flags, message", [
    (["-d", "Nov 1", "--type", "hackathon"], "dates must be an ISO date"),
    (["-d", "2026-11-01", "--type", "party"], "type must be one of"),
    (["-d", "2026-11-01", "--type", "hackathon", "--tags", "juggling"], "unknown tag"),
])
def test_cli_add_stays_strict(tmp_path, flags, message):
    path = tmp_path / "m.yaml"
    result = runner.invoke(cli.app, ["add", "--file", str(path), "-t", "X", "-u", "https://x",
                                     "-l", "Online", "-o", "me", *flags])
    assert result.exit_code == 1 and message in result.output
    assert not path.exists()  # nothing written
