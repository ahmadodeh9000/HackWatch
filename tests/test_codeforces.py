import pytest

from hackwatch.cli import apply_source_defaults
from hackwatch.scrapers import codeforces
from hackwatch.scrapers.codeforces import CodeforcesScraper


def test_codeforces_upcoming_rated_rounds(replay, frozen_today, configured):
    replay("codeforces")
    frozen_today(codeforces)
    scraper = configured("codeforces")
    events = scraper.fetch()
    for e in events:
        apply_source_defaults(e, scraper)

    assert [(e.title, e.start_date) for e in sorted(events, key=lambda e: (e.start_date, e.url))] == [
        ("Codeforces Round 1131 (Div. 3)", "2026-10-31"),
        ("Educational Codeforces Round 196 (Rated for Div. 2)", "2026-11-04"),
        ("Codeforces Round (Div. 2)", "2026-11-06"),
        ("Codeforces Round (Div. 1)", "2026-11-07"),
        ("Codeforces Round (Div. 2)", "2026-11-07"),
        ("Codeforces Round (Div. 2)", "2026-11-15"),
    ]
    div3 = next(e for e in events if "Div. 3" in e.title)
    assert div3.url == "https://codeforces.com/contests/2278"
    assert (div3.type, div3.tags, div3.mode, div3.scope) == ("competition", ["cp"], "online", "worldwide")
    assert div3.description == "2h 15m Codeforces contest (ICPC rules)."


def test_codeforces_include_is_configurable(replay, frozen_today):
    replay("codeforces")
    frozen_today(codeforces)
    everything = CodeforcesScraper(include=[], delay_seconds=0).fetch()
    names = {e.title for e in everything}
    assert "Kotlin Heroes: Episode 15" not in names  # starts after the 30-day window
    assert "ICPC 2026 Online Challenge 2 powered by Huawei" in names


def test_codeforces_api_error_raises(monkeypatch):
    scraper = CodeforcesScraper(delay_seconds=0)

    class Resp:
        def json(self):
            return {"status": "FAILED", "comment": "Call limit exceeded"}

    monkeypatch.setattr(scraper, "get", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="Call limit exceeded"):
        scraper.fetch()
