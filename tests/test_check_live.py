import json

import pytest

from scripts import check_live


class Resp:
    def __init__(self, status=200, body=""):
        self.status_code, self.text = status, body

    def json(self):
        return json.loads(self.text)


class Site:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        name = url.split("/")[-1].split("?")[0]
        return self.pages[name]


GOOD = {"events.json": Resp(200, '[{"title": "x"}]'), "events.ics": Resp(200, "BEGIN:VCALENDAR\r\n...")}


def test_healthy_site_and_cache_busting():
    site = Site(GOOD)
    assert check_live.problems("https://x.github.io/HackWatch/", site) == []
    assert all("?check=" in u for u in site.urls)


@pytest.mark.parametrize("pages, problem", [
    ({**GOOD, "events.json": Resp(404, "")}, "events.json: HTTP 404"),
    ({**GOOD, "events.json": Resp(200, "[]")}, "events.json: has 0 events"),
    ({**GOOD, "events.json": Resp(200, "<html>")}, "events.json: not valid JSON"),
    ({**GOOD, "events.ics": Resp(404, "")}, "events.ics: HTTP 404"),
    ({**GOOD, "events.ics": Resp(200, "<html>")}, "events.ics: doesn't start with BEGIN:VCALENDAR"),
])
def test_broken_site(pages, problem):
    assert check_live.problems("https://x.github.io/HackWatch", Site(pages)) == [problem]


def test_main_retries_then_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(check_live, "problems", lambda site: calls.append(site) or ["events.json: HTTP 404"])
    monkeypatch.setattr(check_live.time, "sleep", lambda s: None)
    assert check_live.main(["https://x", "--tries", "3"]) == 1
    assert len(calls) == 3
