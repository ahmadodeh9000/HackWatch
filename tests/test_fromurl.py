"""`hackwatch add --from-url`: what is read from real event pages (slimmed, recorded 2026-10-28)."""
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hackwatch import cli, fromurl
from hackwatch.fromurl import dates_in_text, extract, suggest

FIXTURES = Path(__file__).parent / "fixtures" / "fromurl"
PAGES = {
    "gdg": ("gdg_devfest.html", "https://gdg.community.dev/events/details/google-gdg-amman-presents-devfest-amman-2026/"),
    "ieee": ("ieee_588430.html", "https://events.vtools.ieee.org/m/588430"),
    "eventbrite": ("eventbrite_pgc.html", "https://www.eventbrite.co.uk/e/pocket-gamer-connects-jordan-2026-tickets-1992137032491"),
    "luma": ("luma_pitch.html", "https://luma.com/xvyh6z2t"),
    "form": ("google_form.html", "https://forms.gle/hsm5rgNSBV9TZqty6"),
}


def page(name):
    file, url = PAGES[name]
    return extract((FIXTURES / file).read_text(encoding="utf-8"), url)


def test_gdg_jsonld_with_chapter_from_url():
    x = page("gdg")
    v = x.values
    assert (v["title"], v["start_date"], v["start_time"], v["end_time"]) == ("DevFest Amman 2026", "2026-11-28", "11:00", "19:00")
    assert v["location"] == "King Hussein Business Park, Amman, Jordan"   # "TBA" venue part dropped
    assert v["organizer"] == "GDG Amman" and x.found_by["organizer"] == "bevy-url"
    s = suggest(x)
    assert s["type"] == "conference" and {"ai", "gdg"} <= set(s["tags"].split(","))


def test_ieee_from_google_calendar_link():
    x = page("ieee")
    v = x.values
    assert x.found_by["start_date"] == "gcal-link"
    # dates=20261101T070000Z/20261101T123000Z -> Amman (UTC+3)
    assert (v["start_date"], v["start_time"], v["end_time"]) == ("2026-11-01", "10:00", "15:30")
    assert v["location"] == "Yarmouk University, Irbid"
    assert "end_date" not in v


def test_eventbrite_business_event():
    v = page("eventbrite").values
    assert v["title"] == "Pocket Gamer Connects Jordan 2026"
    assert (v["start_date"], v["end_date"], v["mode"]) == ("2026-11-07", "2026-11-08", "in-person")
    assert v["location"].endswith("Amman, Amman Governorate, Jordan")
    assert v["organizer"].startswith("Steel Media")


def test_luma_time_converted_to_amman_and_abroad_warning():
    x = page("luma")
    # startDate 2026-11-05T19:00+04:00 (Dubai) is 18:00 in Amman
    assert (x.values["start_date"], x.values["start_time"]) == ("2026-11-05", "18:00")
    suggest(x)
    assert any("outside Jordan" in w for w in x.warnings)


def test_google_form_title_and_description_without_dates():
    x = page("form")
    assert x.values["title"].startswith("Climate Change Hackathon 2022")
    assert x.found_by["description"] == "google-form"
    assert "start_date" not in x.values
    assert any("Google Form" in w for w in x.warnings) and any("No date" in w for w in x.warnings)
    assert suggest(x)["type"] == "hackathon"


def test_dates_in_text_and_deadline():
    found = dates_in_text("Apply by 3 November 2026. The hackathon runs Nov 14, 2026 to 2026-11-15.")
    assert found == [("2026-11-03", True), ("2026-11-14", False), ("2026-11-15", False)]
    x = extract('<meta property="og:title" content="Hack"><meta property="og:description" '
                'content="Deadline: 3 November 2026. Hackathon on 14 November 2026.">', "https://example.com")
    assert (x.values["start_date"], x.values["registration_deadline"]) == ("2026-11-14", "2026-11-03")


def test_naive_timestamps_are_taken_as_written():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"Meetup",'
            '"startDate":"2026-12-01T18:30","endDate":"2026-12-01T20:00"}</script>')
    v = extract(html, "https://example.com").values
    assert (v["start_date"], v["start_time"], v["end_time"]) == ("2026-12-01", "18:30", "20:00")


def test_cli_add_from_url_saves_validated_entry(tmp_path, monkeypatch):
    file, url = PAGES["gdg"]
    monkeypatch.setattr(fromurl, "fetch_html", lambda u, timeout=30.0: (u, (FIXTURES / file).read_text(encoding="utf-8")))
    path = tmp_path / "manual.yaml"
    result = CliRunner().invoke(cli.app, ["add", "--from-url", url, "--yes", "--file", str(path)])
    assert result.exit_code == 0, result.output
    (entry,) = yaml.safe_load(path.read_text())
    assert entry["title"] == "DevFest Amman 2026" and entry["dates"] == "2026-11-28"
    assert entry["organizer"] == "GDG Amman" and entry["start_time"] == "11:00" and "gdg" in entry["tags"]
    assert entry["url"] == url and entry["description"].startswith("GDG Amman hosts")


def test_cli_flags_override_and_prompts_prefill(tmp_path, monkeypatch):
    file, url = PAGES["ieee"]
    monkeypatch.setattr(fromurl, "fetch_html", lambda u, timeout=30.0: (u, (FIXTURES / file).read_text(encoding="utf-8")))
    path = tmp_path / "manual.yaml"
    # Enter on every prompt accepts the pre-filled value; --type is given, so it isn't asked.
    result = CliRunner().invoke(cli.app, ["add", "--from-url", url, "--type", "meetup", "--file", str(path)],
                                input="\n" * 12)
    assert result.exit_code == 0, result.output
    (entry,) = yaml.safe_load(path.read_text())
    assert entry["type"] == "meetup" and entry["dates"] == "2026-11-01" and entry["start_time"] == "10:00"


def test_cli_without_a_date_fails_with_yes(tmp_path, monkeypatch):
    file, url = PAGES["form"]
    monkeypatch.setattr(fromurl, "fetch_html", lambda u, timeout=30.0: (u, (FIXTURES / file).read_text(encoding="utf-8")))
    result = CliRunner().invoke(cli.app, ["add", "--from-url", url, "--yes", "--dry-run", "--file", str(tmp_path / "m.yaml")])
    assert result.exit_code == 1 and "No date found" in result.output and "run without --yes" in result.output


def test_fetch_errors_are_readable(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(ValueError, match="couldn't fetch"):
        fromurl.fetch_html("https://example.com")


def test_jordanian_place_beats_a_wrong_country():
    html = ('<script type="application/ld+json">{"@type":"Event","name":"GDG Aqaba DevFest","startDate":"2026-12-26",'
            '"location":{"@type":"Place","name":"iPARK Aqaba","address":{"streetAddress":"pr.Haya street",'
            '"addressLocality":"Aqaba","addressCountry":"US"}}}</script>')
    assert extract(html, "https://x.test/e").values["location"] == "iPARK Aqaba, pr.Haya street, Jordan"


def test_add_keeps_the_comments_in_the_yaml(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("# Community-submitted events\n# keep me\n")
    result = CliRunner().invoke(cli.app, ["add", "--file", str(path), "-t", "Hack", "-u", "https://x.test/h",
                                          "-d", "2026-12-05", "-l", "Amman, Jordan", "-o", "Club", "--type", "hackathon"])
    assert result.exit_code == 0, result.output
    text = path.read_text()
    assert "# keep me" in text and yaml.safe_load(text)[0]["title"] == "Hack"
