"""Shared test helpers: replay recorded HTTP responses and freeze "today".

Fixtures live in tests/fixtures/<source>/ and are produced by
scripts/record_fixtures.py. Each directory has a manifest.json mapping the
full request URL to a saved response body.
"""
import json
from datetime import date, datetime
from pathlib import Path

import pytest
import requests

from hackwatch.scrapers.base import BaseScraper

FIXTURES = Path(__file__).parent / "fixtures"

# The day the fixtures were recorded. Scrapers that compare against "today"
# are pinned to this so the tests don't rot as real time passes.
RECORDED_ON = date(2026, 10, 26)


class FakeResponse:
    def __init__(self, url, body: bytes, status: int):
        self.url = url
        self.content = body
        self.status_code = status
        self.text = body.decode("utf-8")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url}", response=self)


@pytest.fixture
def replay(monkeypatch):
    """replay("gdg") makes every scraper request return the recorded response.

    A request that isn't in the manifest fails the test instead of hitting the network.
    """
    def activate(source: str):
        folder = FIXTURES / source
        manifest = json.loads((folder / "manifest.json").read_text())
        by_url = {(m["method"], m["url"]): m for m in manifest}

        def fake_request(self, method, url, **kwargs):
            key = requests.Request(method, url, params=kwargs.get("params")).prepare().url
            entry = by_url.get((method, key))
            if entry is None:
                raise AssertionError(f"No recorded response for {method} {key}")
            body = (folder / entry["file"]).read_bytes() if entry["file"] else b""
            resp = FakeResponse(key, body, entry["status"])
            resp.raise_for_status()
            return resp

        monkeypatch.setattr(BaseScraper, "request", fake_request)
        return manifest

    return activate


@pytest.fixture
def frozen_today(monkeypatch):
    """Pin date.today()/datetime.now() inside the given modules to RECORDED_ON."""
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return RECORDED_ON

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(RECORDED_ON.year, RECORDED_ON.month, RECORDED_ON.day, 12, 0, tzinfo=tz)

    def activate(*modules):
        for mod in modules:
            if hasattr(mod, "date"):
                monkeypatch.setattr(mod, "date", FrozenDate)
            if hasattr(mod, "datetime"):
                monkeypatch.setattr(mod, "datetime", FrozenDatetime)

    return activate


@pytest.fixture
def configured():
    """configured("gdg") builds that source's scraper from the real sources.yaml, without delays."""
    from hackwatch.sources import build_scraper, load_sources

    def build(name: str):
        (config,) = [c for c in load_sources() if c.name == name]
        scraper = build_scraper(config)
        scraper.delay_seconds = 0
        return scraper

    return build
