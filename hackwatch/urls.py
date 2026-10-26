"""URL clean-up and normalisation, used to recognise the same event across sources."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track where a click came from.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl",
    "aff", "affiliate", "ref", "ref_src", "referrer", "si", "trk", "cmp", "s_cid", "spm",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_")


def _is_tracking(param: str) -> bool:
    p = param.lower()
    return p in TRACKING_PARAMS or p.startswith(TRACKING_PREFIXES)


def clean_url(url: str) -> str:
    """The URL to show and link to: tracking params and #fragment removed, otherwise unchanged."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def normalize_url(url: str) -> str:
    """A comparison key: two URLs for the same page should give the same key.

    Ignores http/https, "www.", letter case of the host, a trailing slash,
    default ports, tracking params, the fragment and the order of query params.
    """
    url = clean_url(url)
    parts = urlsplit(url)
    if not parts.netloc:
        return url.lower().rstrip("/")
    host = parts.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return f"{host}{path}" + (f"?{query}" if query else "")
