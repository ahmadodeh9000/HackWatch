"""After a deploy, check the live site really serves the data files.

Usage:  python scripts/check_live.py https://ahmadodeh9000.github.io/HackWatch/ [--tries 12 --wait 10]

Fails (exit 1) unless events.json is 200 with at least one event and events.ics is
200 and looks like a calendar. Pages can take a few seconds to serve a new
deploy, so failed checks are retried.
"""
import argparse
import sys
import time
from typing import List, Optional

import requests

USER_AGENT = "HackWatch-CI (+https://github.com/ahmadodeh9000/HackWatch)"


def problems(site: str, session=requests) -> List[str]:
    """Everything wrong with the live site right now (empty list = fine)."""
    found = []
    bust = f"?check={int(time.time())}"  # skip the CDN cache
    headers = {"User-Agent": USER_AGENT, "Cache-Control": "no-cache"}

    def get(name: str) -> Optional[requests.Response]:
        try:
            resp = session.get(site.rstrip("/") + "/" + name + bust, headers=headers, timeout=30)
        except requests.RequestException as exc:
            found.append(f"{name}: {type(exc).__name__}: {exc}")
            return None
        if resp.status_code != 200:
            found.append(f"{name}: HTTP {resp.status_code}")
            return None
        return resp

    events = get("events.json")
    if events is not None:
        try:
            data = events.json()
        except ValueError:
            found.append("events.json: not valid JSON")
        else:
            if not isinstance(data, list) or not data:
                found.append("events.json: has 0 events")
    ics = get("events.ics")
    if ics is not None and not ics.text.startswith("BEGIN:VCALENDAR"):
        found.append("events.ics: doesn't start with BEGIN:VCALENDAR")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("site")
    parser.add_argument("--tries", type=int, default=12)
    parser.add_argument("--wait", type=float, default=10.0)
    args = parser.parse_args(argv)
    for attempt in range(1, args.tries + 1):
        found = problems(args.site)
        if not found:
            print(f"Live site OK (attempt {attempt}): events.json and events.ics are served.")
            return 0
        print(f"Attempt {attempt}/{args.tries}: " + "; ".join(found))
        if attempt < args.tries:
            time.sleep(args.wait)
    print(f"::error title=Live site check failed::{'; '.join(found)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
