"""The discovery queue: finding candidates, the one issue, and ticking a box."""
from datetime import date

import requests

from hackwatch.discovery import (Candidate, PoliteFetcher, candidate_line, candidates_from_html, merge_body,
                                 not_listed, run, sanitize)
from scripts import candidate_to_pr as tick

TODAY = date(2026, 10, 30)
PAGE = """<html><body>
<script type="application/ld+json">{"@type":"Event","name":"Robotics Cup Jordan","url":"/e/robots",
 "startDate":"2026-11-20T10:00:00+03:00","location":{"@type":"Place","name":"PSUT"}}</script>
<script type="application/ld+json">{"@type":"Event","name":"Old Hackathon","url":"/e/old","startDate":"2025-01-01"}</script>
<div class="card"><a href="/events/jitex">Jordan Information Technology Exhibition (JITEX)</a><span>Monday, January 25, 2027</span></div>
<div class="card"><a href="/events/past">Past Developer Conference in Amman</a><span>March 3, 2024</span></div>
<div class="card"><a href="/events/food">Annual Student Food Festival Fair</a><span>November 25, 2026</span></div>
<div class="card"><a href="/events/farout">Far Future Tech Summit Amman</a><span>November 25, 2028</span></div>
<a href="/about-technology-faculty">About the technology faculty</a>
</body></html>"""


def test_candidates_from_jsonld_and_dated_links():
    found = {c.title: c for c in candidates_from_html(PAGE, "https://u.test/events", "U", TODAY)}
    assert set(found) == {"Robotics Cup Jordan", "Jordan Information Technology Exhibition (JITEX)"}
    assert found["Robotics Cup Jordan"].url == "https://u.test/e/robots"
    assert found["Robotics Cup Jordan"].start == "2026-11-20" and found["Robotics Cup Jordan"].place == "PSUT"
    assert found["Jordan Information Technology Exhibition (JITEX)"].start == "2027-01-25"


def test_not_listed_by_url_and_title():
    listed = [{"title": "DevFest Amman 2026", "url": "https://x/a", "urls": ["https://y/a"]}]
    keep = Candidate("New Hack", "https://z/n", "S")
    assert not_listed([Candidate("Other", "https://www.y/a/", "S"), Candidate("DevFest  amman 2026!", "https://z/d", "S"),
                       keep, Candidate("New Hack", "https://z/n2", "S")], listed) == [keep]


def test_sanitize_blocks_markup_mentions_and_comments():
    line = candidate_line(Candidate("Hack @everyone [x](http://evil) <!--k:zz--> <img src=x>", "https://z/a)b c", "S"))
    assert "@" not in line and "<img" not in line and "<!--k:zz" not in line
    assert "[link](https://z/a%29b%20c)" in line
    assert sanitize("a\n- [x] b") == "a - x b"


def test_merge_keeps_ticks_drops_expired_and_never_repeats():
    new = Candidate("Fresh Hack", "https://z/f", "S", start="2026-12-01")
    body, added = merge_body(None, [new], [("S", "ok", 1)], TODAY)
    assert added == 1 and "- [ ] **Fresh Hack**" in body and "<!--seen:" in body

    ticked = body.replace("- [ ] **Fresh Hack**", "- [x] **Fresh Hack**")
    body2, added2 = merge_body(ticked, [new], [], TODAY)
    assert added2 == 0 and "- [x] **Fresh Hack**" in body2

    # Deleted by hand: stays gone. The key is still in the hidden list.
    without = "\n".join(l for l in body.splitlines() if "Fresh Hack" not in l)
    body3, added3 = merge_body(without, [new], [], TODAY)
    assert added3 == 0 and "Fresh Hack" not in body3

    # Unticked and past: removed; ticked and past: kept.
    later = date(2026, 12, 2)
    assert "Fresh Hack" not in merge_body(body, [], [], later)[0]
    assert "Fresh Hack" in merge_body(ticked, [], [], later)[0]


class FakeIssues:
    def __init__(self, existing=None):
        self.existing, self.written = existing, None

    def find_open(self, title):
        assert title == "Candidate events"
        return self.existing

    def create(self, title, body):
        self.written = ("create", body)

    def update(self, number, body):
        self.written = ("update", number, body)


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url):
        return self.pages.get(url, (None, "HTTP 404"))


def test_run_updates_one_issue_and_skips_google_without_secrets(monkeypatch):
    import hackwatch.discovery as d
    monkeypatch.setattr(d, "google_candidates", lambda *a: (_ for _ in ()).throw(AssertionError("no secrets")))
    api = FakeIssues()
    pages = [{"name": "U", "url": "https://u.test/events"}, {"name": "Gone", "url": "https://g.test/"}]
    added = run(pages, [{"title": "Robotics Cup Jordan", "url": "https://other"}], api,
                FakeFetcher({"https://u.test/events": (PAGE, "ok")}), TODAY, env={}, log=lambda m: None)
    assert added == 1 and api.written[0] == "create"
    assert "JITEX" in api.written[1] and "Robotics Cup" not in api.written[1] and "HTTP 404" in api.written[1]

    api2 = FakeIssues({"number": 7, "body": api.written[1]})
    assert run(pages, [], api2, FakeFetcher({}), TODAY, env={}, log=lambda m: None) == 0
    assert api2.written[:2] == ("update", 7) and "JITEX" in api2.written[2]


def test_run_uses_google_when_secrets_exist(monkeypatch):
    import hackwatch.discovery as d
    monkeypatch.setattr(d, "google_candidates", lambda k, e: [Candidate("Hack Amman", "https://g/h", "Google search")])
    api = FakeIssues()
    assert run([], [], api, FakeFetcher({}), TODAY, env={"GOOGLE_CSE_KEY": "k", "GOOGLE_CSE_ID": "e"}, log=lambda m: None) == 1
    assert "Google search" in api.written[1]


class Resp:
    def __init__(self, text="", status=200, url="https://u.test/events"):
        self.text, self.status_code, self.url = text, status, url


class Session:
    def __init__(self, robots, page=None):
        self.robots, self.page, self.calls = robots, page or Resp("<html>"), []

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            if isinstance(self.robots, Exception):
                raise self.robots
            return self.robots
        return self.page


def fetcher(session):
    return PoliteFetcher(session, sleep=lambda s: None)


def test_fetcher_respects_robots():
    s = Session(Resp("User-agent: *\nDisallow: /events"))
    assert fetcher(s).fetch("https://u.test/events") == (None, "disallowed by robots.txt")
    assert s.calls == ["https://u.test/robots.txt"]  # the page itself is never requested


def test_fetcher_stays_away_when_robots_is_unavailable():
    for robots in (Resp("", 503), requests.ConnectionError("x")):
        s = Session(robots)
        html, note = fetcher(s).fetch("https://u.test/events")
        assert html is None and "skipped" in note and len(s.calls) == 1


def test_fetcher_skips_redirects_elsewhere_and_uses_crawl_delay():
    s = Session(Resp("", 404), Resp("x", url="https://u.test/discover"))
    assert fetcher(s).fetch("https://u.test/amman") == (None, "redirects to /discover, skipped")
    waits = []
    s = Session(Resp("User-agent: *\nCrawl-delay: 30"), Resp("ok"))
    html, note = PoliteFetcher(s, sleep=waits.append).fetch("https://u.test/events")
    assert (html, note, waits) == ("ok", "ok", [30])


BODY = """intro
- [x] **JITEX** · 2027-01-25 · place unknown · [link](https://i.test/jitex) · int@j <!--k:aaa-->
- [ ] **Other** · 2027-01-25 · place unknown · [link](https://i.test/other) · int@j <!--k:bbb-->
- [x] **Done** · 2027-01-25 · x · [link](https://i.test/done) · int@j · PR #4 <!--k:ccc-->
"""


def test_only_newly_ticked_lines_count():
    assert [(k, u) for k, u, _ in tick.ticked_lines(BODY)] == [("aaa", "https://i.test/jitex")]


def test_mark_keeps_the_key_at_the_end():
    (_, _, raw), = tick.ticked_lines(BODY)
    marked = tick.mark(BODY, raw, "PR #9")
    assert "int@j · PR #9 <!--k:aaa-->" in marked and tick.ticked_lines(marked) == []


class Done:
    def __init__(self, code=0, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


def test_open_pr_adds_then_opens_a_pr():
    calls = []

    def sh(cmd):
        calls.append(cmd)
        if "add" in cmd and "--from-url" in cmd:
            return Done(out="Found...\nSaved event 'JITEX' in manual_events.yaml\n")
        if cmd[:3] == ["gh", "pr", "create"]:
            return Done(out="https://github.com/o/r/pull/12\n")
        return Done()
    assert tick.open_pr("aaa", "https://i.test/jitex", "5", sh) == "PR #12"
    assert ["git", "checkout", "-B", "candidate/aaa", "origin/main"] in calls
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert not any("merge" in c for c in calls)   # never publishes


def test_open_pr_reports_when_the_page_has_no_date():
    def sh(cmd):
        return Done(1, "Error: no title or date found on the page") if "--from-url" in cmd else Done()
    note = tick.open_pr("aaa", "https://i.test/x", "5", sh)
    assert note.startswith("couldn't add:") and "no title or date" in note
    assert tick.DONE_RE.search(note)
