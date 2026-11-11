"""The organizer census: page signals and the class suggested from two probes."""
from datetime import date
from pathlib import Path

import yaml

from hackwatch.census import CLASSES, dates_in, page_state, signals, social_links, suggest

TODAY = date(2026, 11, 11)


def test_dates_in_english_arabic_and_digits():
    text = "Workshop on 14 November 2026, then Dec 3, 2026. المؤتمر يوم ٢٤ تشرين الثاني 2026 و 5 كانون الأول 2026. Past: 03/02/2025, 2027-01-09"
    assert dates_in(text) == [date(2027, 1, 9), date(2025, 2, 3), date(2026, 11, 14), date(2026, 12, 3),
                              date(2026, 11, 24), date(2026, 12, 5)]
    assert dates_in("31/02/2026 and 2026-13-01") == []


def test_signals_feeds_events_and_platform():
    html = ('<html><head><meta name="generator" content="WordPress 6.5">'
            '<link rel="alternate" type="application/rss+xml" href="https://x.test/feed/">'
            '<script type="application/ld+json">{"@graph":[{"@type":"EducationEvent","name":"A"},{"@type":["Event"]}]}</script>'
            '</head><body class="tribe-events"><a href="/events/?ical=1">Export</a>'
            '<a href="/calendar">الفعاليات</a><p>Hackathon on 20 November 2026 and one on 1 January 2020.</p>'
            '<a href="https://www.instagram.com/club.jo/">ig</a><a href="https://www.facebook.com/sharer.php?u=x">share</a>'
            '</body></html>')
    s = signals(html, TODAY)
    assert s["rss"] == ["https://x.test/feed/"] and s["ical"] == ["/events/?ical=1"]
    assert s["jsonld_events"] == 2 and (s["dates"], s["future_dates"]) == (2, 1)
    assert s["platform"] == "WordPress 6.5 + The Events Calendar"
    assert s["social"] == {"instagram": "https://www.instagram.com/club.jo"}
    assert ("/calendar", "الفعاليات") in s["event_links"]


def test_app_shell_and_block_page():
    shell = signals('<html><body><div id="root"></div><script src="/app.js"></script></body></html>', TODAY)
    assert shell["app_shell"]
    waf = signals("<html><body>Request Rejected. Your support ID is 1</body></html>", TODAY)
    assert waf["block_words"] == ["request rejected"]
    assert page_state({"status": 200, **waf}) == "blocked"       # a block page served with HTTP 200
    assert page_state({"status": 403}) == "blocked" and page_state({"status": 404}) == "missing"
    assert page_state({"status": None, "robots": "disallowed"}) == "robots"
    assert page_state({"status": None, "error": "ConnectionError"}) == "down"
    # A long real page that merely mentions a captcha isn't a block page.
    assert page_state({"status": 200, "block_words": ["captcha"], "text_chars": 6000}) == "ok"


def test_social_links_skip_share_buttons():
    html = '<a href="https://twitter.com/intent/tweet">t</a><a href="https://x.com/jo_osa">x</a>'
    assert social_links(html) == {"x": "https://x.com/jo_osa"}


def test_suggest_from_home_and_runner():
    ok = {"status": 200, "text_chars": 5000}
    assert suggest([], []) == "social_only"
    assert suggest([{**ok, "future_dates": 3}], [{"status": 403}]) == "runner_blocked"
    assert suggest([{"status": 200, "block_words": ["request rejected"], "text_chars": 118}], [{"status": 403}]) == "blocked"
    assert suggest([{**ok, "ical": ["/x.ics"]}], [{**ok, "ical": ["/x.ics"]}]) == "api_feed"
    assert suggest([{**ok, "future_dates": 2}], [{**ok, "future_dates": 2}]) == "clean_html"
    assert suggest([{"status": 200, "app_shell": True, "text_chars": 30}], [{"status": 200, "app_shell": True}]) == "js_no_endpoint"
    assert suggest([ok], [ok]) == "no_listing"
    assert suggest([{"status": None}], [{"status": None}]) == "dead"


def test_organizers_yaml_is_well_formed():
    orgs = yaml.safe_load((Path(__file__).parent.parent / "organizers.yaml").read_text(encoding="utf-8"))["organizers"]
    names = [o["name"] for o in orgs]
    assert len(names) == len(set(names)) and len(orgs) >= 100
    kinds = {"university", "faculty", "student_group", "community", "ecosystem", "platform", "annual_event"}
    for o in orgs:
        assert o["kind"] in kinds, o["name"]
        assert o.get("class", CLASSES[0]) in CLASSES, o["name"]
        for url in [o.get("website"), *(o.get("pages") or [])]:
            assert url is None or url.startswith(("https://", "http://")), o["name"]
