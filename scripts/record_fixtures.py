"""Run each scraper live, save every HTTP response under tests/fixtures/<source>/,
and print raw vs. kept counts after filters.is_relevant.

Usage:  python scripts/record_fixtures.py [source ...]

Re-run this when a site changes its markup so the offline tests stay realistic.
"""
import json
import sys
import traceback
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from hackwatch.filters import is_relevant
from hackwatch.scrapers import get_available_scrapers
from hackwatch.scrapers.base import BaseScraper

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def slim_html(body: bytes) -> bytes:
    """Keep only the JSON-LD <script> blocks of an HTML page.

    Eventbrite search pages are ~700 KB, but the scraper only reads JSON-LD,
    so this keeps fixtures small while staying real response data.
    """
    soup = BeautifulSoup(body, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")
    return ("<html><body>\n" + "\n".join(str(s) for s in scripts) + "\n</body></html>\n").encode()


# How to shrink each source's responses before saving them as fixtures.
SLIMMERS = {"eventbrite": slim_html}


def full_url(method, url, params=None):
    return requests.Request(method, url, params=params).prepare().url


def record(scraper):
    """Wrap scraper.request so each response is written to disk with a manifest entry."""
    out_dir = FIXTURES / scraper.name
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    original = BaseScraper.request

    def recording_request(self, method, url, **kwargs):
        key = full_url(method, url, kwargs.get("params"))
        try:
            resp = original(self, method, url, **kwargs)
        except requests.HTTPError as exc:
            resp = exc.response
            manifest.append({"method": method, "url": key, "status": resp.status_code, "file": None})
            raise
        ext = "json" if "json" in resp.headers.get("Content-Type", "") else "html"
        name = f"{len(manifest):03d}.{ext}"
        slim = SLIMMERS.get(scraper.name)
        body = slim(resp.content) if slim else resp.content
        (out_dir / name).write_bytes(body)
        manifest.append({"method": method, "url": key, "status": resp.status_code, "file": name})
        return resp

    scraper.request = recording_request.__get__(scraper)
    return out_dir, manifest


def main(selected):
    report = {}
    for scraper in get_available_scrapers():
        if selected and scraper.name not in selected:
            continue
        print(f"== {scraper.name}", flush=True)
        out_dir, manifest = record(scraper)
        entry = {"raw": 0, "kept": [], "dropped": [], "error": None}
        try:
            events = scraper.fetch()
            entry["raw"] = len(events)
            for ev in events:
                bucket = "kept" if is_relevant(ev, scraper.require_tech_keywords) else "dropped"
                entry[bucket].append({
                    "title": ev.title, "start": ev.start_date, "online": ev.is_online,
                    "location": ev.location, "country": ev.country,
                })
        except Exception:
            entry["error"] = traceback.format_exc(limit=3)
        if scraper.name != "manual":
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        entry["requests"] = len(manifest)
        report[scraper.name] = entry
        print(f"   requests={len(manifest)} raw={entry['raw']} kept={len(entry['kept'])} "
              f"dropped={len(entry['dropped'])} error={'yes' if entry['error'] else 'no'}", flush=True)
    return report


if __name__ == "__main__":
    # --report PATH writes the full kept/dropped lists as JSON
    args = sys.argv[1:]
    report_path = None
    if "--report" in args:
        i = args.index("--report")
        report_path = args[i + 1]
        del args[i:i + 2]
    result = main(args)
    if report_path:
        Path(report_path).write_text(json.dumps(result, indent=2, ensure_ascii=False))
