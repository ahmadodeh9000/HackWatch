import pytest

from hackwatch.models import Event
from hackwatch.urls import clean_url, normalize_url


@pytest.mark.parametrize("a, b", [
    ("https://devfest.gdg.dev/amman/", "http://www.devfest.gdg.dev/amman"),
    ("https://example.com/e?id=5&utm_source=x&utm_medium=y", "https://EXAMPLE.com/e?id=5"),
    ("https://example.com/e?b=2&a=1", "https://example.com/e?a=1&b=2"),
    ("https://example.com/e#register", "https://example.com/e"),
    ("https://www.eventbrite.com/e/ai-summit-123?aff=ebdssbdestsearch", "https://eventbrite.com/e/ai-summit-123"),
    ("https://example.com:443/e", "https://example.com/e"),
])
def test_same_page_same_key(a, b):
    assert normalize_url(a) == normalize_url(b)


@pytest.mark.parametrize("a, b", [
    ("https://example.com/e?id=5", "https://example.com/e?id=6"),  # real params are kept
    ("https://example.com/events/1", "https://example.com/events/12"),
    ("https://a.devpost.com/", "https://b.devpost.com/"),
])
def test_different_pages_differ(a, b):
    assert normalize_url(a) != normalize_url(b)


def test_clean_url_keeps_scheme_host_and_real_params():
    assert clean_url("https://www.Example.com/e/?id=5&utm_campaign=z&fbclid=abc#top") == \
        "https://www.Example.com/e/?id=5"
    assert clean_url("not a url") == "not a url"


def test_event_url_is_cleaned_and_id_ignores_url_noise():
    a = Event(title="t", url="https://example.com/e/?utm_source=x", source="gdg")
    b = Event(title="t", url="http://www.example.com/e", source="gdg")
    assert a.url == "https://example.com/e/"
    assert a.id == b.id
