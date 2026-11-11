"""Fetch every page named in organizers.yaml once and record what it offers.

Run from a home connection and from a GitHub runner (.github/workflows/census.yml); the
two results are compared in the census. Polite: honest User-Agent, robots.txt obeyed
(a disallowed page is recorded, not fetched), one host at a time with its Crawl-delay
(at least 2 s) between requests. Instagram, Facebook, LinkedIn, X, YouTube and Telegram
links are never fetched.

    PYTHONPATH=. python scripts/census_probe.py --out census/probe-home.json
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch.census import signals  # noqa: E402
from hackwatch.scrapers.base import DEFAULT_USER_AGENT  # noqa: E402

NEVER = ("instagram.com", "facebook.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "t.me",
         "telegram.org", "tiktok.com", "whatsapp.com")
HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en,ar;q=0.8"}
TIMEOUT = 30


def urls_of(org: dict):
    for key in ("website", "events_url"):
        if org.get(key):
            yield org[key]
    for url in org.get("pages") or []:
        yield url
    for url in org.get("feeds") or []:
        yield url


def curl_fallback(url: str, raw: bool = False) -> dict:
    """Some servers send an incomplete certificate chain: Python refuses it, curl with the
    system's trust store may complete it. Verification stays on; the row says how it was read."""
    try:
        done = subprocess.run(["curl", "-sL", "-m", str(TIMEOUT), "-A", DEFAULT_USER_AGENT, "-w", "\n%{http_code}", url],
                              capture_output=True, timeout=TIMEOUT + 5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if done.returncode != 0:
        return {"tls": "certificate not accepted by Python or curl"}
    body, _, code = done.stdout.decode("utf-8", "ignore").rpartition("\n")
    if raw:
        return {"status": int(code or 0) or None, "body": body}
    row = {"status": int(code or 0) or None, "tls": "incomplete certificate chain: read with curl, Python requests refuses it",
           "kb": round(len(body) / 1024)}
    row.update(signals(body))
    return row


def fetch_host(host: str, urls: list) -> dict:
    out = {}
    session = requests.Session()
    session.headers.update(HEADERS)
    rules, delay, robots_note = None, 2.0, ""
    scheme = urlsplit(urls[0]).scheme
    try:
        resp = session.get(f"{scheme}://{host}/robots.txt", timeout=TIMEOUT)
        if resp.status_code == 200 and "<html" not in resp.text[:300].lower():
            rules = robotparser.RobotFileParser()
            rules.parse(resp.text.splitlines())
            delay = max(delay, float(rules.crawl_delay(DEFAULT_USER_AGENT) or 0))
        else:
            robots_note = f"robots.txt: HTTP {resp.status_code}"
    except requests.exceptions.SSLError:
        got = curl_fallback(f"{scheme}://{host}/robots.txt", raw=True)
        if got.get("status") == 200 and "<html" not in got["body"][:300].lower():
            rules = robotparser.RobotFileParser()
            rules.parse(got["body"].splitlines())
            delay = max(delay, float(rules.crawl_delay(DEFAULT_USER_AGENT) or 0))
        robots_note = "robots.txt: read with curl (certificate chain)" if got.get("status") else "robots.txt: SSLError"
    except requests.RequestException as exc:
        robots_note = f"robots.txt: {type(exc).__name__}"
    delay = min(delay, 30.0)
    extra_done = False
    queue = list(urls)
    while queue:
        url = queue.pop(0)
        if url in out:
            continue
        row = {"url": url, "robots_note": robots_note}
        if rules is not None and not rules.can_fetch(DEFAULT_USER_AGENT, url):
            row.update(robots="disallowed", status=None)
            out[url] = row
            continue
        time.sleep(delay)
        started = time.monotonic()
        try:
            resp = session.get(url, timeout=TIMEOUT)
            body = resp.text or ""
            row.update(status=resp.status_code, final_url=resp.url, kb=round(len(resp.content or b"") / 1024),
                       seconds=round(time.monotonic() - started, 1),
                       content_type=resp.headers.get("content-type", "")[:40],
                       server=resp.headers.get("server", "")[:30])
            ctype = row["content_type"]
            if "json" in ctype:
                try:
                    data = resp.json()
                    row["json_keys"] = sorted(data)[:8] if isinstance(data, dict) else f"list[{len(data)}]"
                    if isinstance(data, dict) and "events" in data:
                        row["tribe_events"] = len(data["events"])
                except ValueError:
                    pass
            elif "calendar" in ctype or body.lstrip().startswith("BEGIN:VCALENDAR"):
                row["ics_events"] = body.count("BEGIN:VEVENT")
            elif "xml" in ctype or body.lstrip().startswith("<?xml"):
                row["feed_items"] = body.count("<item") + body.count("<entry")
                row["feed_sample"] = [t[:80] for t in __import__("re").findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", body)[1:6]]
            else:
                row.update(signals(body))
                # A WordPress site may have The Events Calendar's API and feed: ask once per host.
                if not extra_done and resp.status_code == 200 and "wordpress" in row.get("platform", "").lower():
                    extra_done = True
                    base = f"{scheme}://{host}"
                    queue += [u for u in (base + "/wp-json/tribe/events/v1/events", base + "/feed/") if u not in out]
        except requests.exceptions.SSLError as exc:
            row.update(status=None, error=f"SSLError: {str(exc)[-110:]}")
            row.update(curl_fallback(url))
        except requests.RequestException as exc:
            row.update(status=None, error=f"{type(exc).__name__}: {str(exc)[:140]}",
                       seconds=round(time.monotonic() - started, 1))
        out[url] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="organizers.yaml")
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", help="only organizers whose name contains this")
    parser.add_argument("--merge", action="store_true", help="keep results already in --out for other URLs")
    args = parser.parse_args()
    orgs = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))["organizers"]
    by_host = {}
    for org in orgs:
        if args.only and args.only.lower() not in org["name"].lower():
            continue
        for url in urls_of(org):
            host = urlsplit(url).netloc
            if any(host == n or host.endswith("." + n) for n in NEVER):
                continue
            if url not in by_host.setdefault(host, []):
                by_host[host].append(url)
    results = {}
    out_path = Path(args.out)
    if args.merge and out_path.exists():
        results = json.loads(out_path.read_text())["pages"]
    with ThreadPoolExecutor(max_workers=16) as pool:
        for found in pool.map(lambda item: fetch_host(*item), by_host.items()):
            results.update(found)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "user_agent": DEFAULT_USER_AGENT, "pages": results},
                                   ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    ok = sum(1 for r in results.values() if r.get("status") == 200)
    print(f"{len(results)} pages on {len(by_host)} hosts; {ok} answered 200. Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
