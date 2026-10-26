"""Per-source fetch diagnostics: request log, block hints, report table/JSON."""
import json

import pytest
import requests
from typer.testing import CliRunner

from hackwatch import cli
from hackwatch.scrapers.base import BaseScraper, block_hint
from hackwatch.scrapers.eventbrite import EventbriteScraper


class Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self.content = status, body
        self.headers = headers or {"Content-Type": "text/html"}
        self.text = body.decode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


@pytest.mark.parametrize("resp, hint", [
    (Resp(200, b"<html>events</html>"), None),
    (Resp(200, b'{"captcha": 1}', {"Content-Type": "application/json"}), None),  # JSON isn't scanned
    (Resp(403, b"<h1>Access Denied</h1>"), "HTTP 403; page mentions 'access denied'"),
    (Resp(429, b"slow down", {"Retry-After": "60", "Content-Type": "text/plain"}), "HTTP 429; Retry-After: 60"),
    (Resp(200, b"<title>Attention Required! | Cloudflare</title>",
          {"Content-Type": "text/html", "cf-mitigated": "challenge"}),
     "cf-mitigated: challenge; page mentions 'attention required'"),
])
def test_block_hint(resp, hint):
    assert block_hint(resp) == hint


class Logged(BaseScraper):
    def __init__(self, responses):
        super().__init__(delay_seconds=0)
        self.responses = list(responses)
        self.name = "site"

    def fetch(self):
        for _ in range(len(self.responses)):
            try:
                self.get("https://site.test/page")
            except requests.RequestException:
                pass
        return []


def test_request_log_records_status_hint_and_errors(monkeypatch):
    scraper = Logged([Resp(200, b"ok"), Resp(403, b"Request Rejected"), requests.Timeout("read timed out")])

    def fake(method, url, **kwargs):
        r = scraper.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(scraper.session, "request", fake)
    scraper.fetch()
    statuses = [(e["status"], e.get("hint"), e.get("error")) for e in scraper.request_log]
    assert statuses == [
        (200, None, None),
        (403, "HTTP 403; page mentions 'request rejected'", None),
        (None, None, "Timeout: read timed out"),
    ]


def test_eventbrite_all_pages_failing_is_an_error(monkeypatch):
    scraper = EventbriteScraper(search_terms=["tech", "ai"], delay_seconds=0)
    monkeypatch.setattr(scraper.session, "request", lambda *a, **k: Resp(403, b"<h1>Access Denied</h1>"))
    with pytest.raises(RuntimeError, match="all 2 Eventbrite search pages failed"):
        scraper.fetch()


def test_eventbrite_one_failing_page_is_tolerated(monkeypatch):
    scraper = EventbriteScraper(search_terms=["tech", "ai"], delay_seconds=0)
    pages = [Resp(403, b"no"), Resp(200, b"<html></html>")]
    monkeypatch.setattr(scraper.session, "request", lambda *a, **k: pages.pop(0))
    assert scraper.fetch() == []


def test_report_rows_and_markdown(tmp_path, monkeypatch):
    blocked = Logged([Resp(403, b"Access Denied")])
    monkeypatch.setattr(blocked.session, "request", lambda *a, **k: blocked.responses.pop(0))
    conn = cli.db.get_connection(tmp_path / "t.db")
    cli.db.init_db(conn)
    _, (result,) = cli.run_fetch(conn, [blocked])
    row = result.summary()
    assert row["ok"] and row["fetched"] == 0 and row["requests"] == 1
    assert row["http_status"] == {"403": 1}
    assert row["block_hints"] == ["HTTP 403; page mentions 'access denied'"]
    table = cli.fetch_report_markdown([row])
    assert "| site | OK | 0 / 0 | 1 | 403×1 |" in table and "access denied" in table


def test_fetch_writes_report_and_job_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cli, "get_available_scrapers", lambda include_disabled=False: [Logged([])])
    report = tmp_path / "status.json"
    result = CliRunner().invoke(cli.app, ["fetch", "--db", str(tmp_path / "t.db"), "--report", str(report)])
    assert result.exit_code == 0, result.output
    data = json.loads(report.read_text())
    assert data["sources"][0]["source"] == "site" and "generated_at" in data
    assert summary.read_text().startswith("## Fetch report")
    assert "| Source | Result |" in result.output
