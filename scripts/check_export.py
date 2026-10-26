"""Fail the deploy if a fresh export looks broken.

Usage:  python scripts/check_export.py docs/events.json --previous URL [--min-ratio 0.5]

Exits non-zero when the new export has no events, or far fewer than the
currently deployed one (e.g. a scraper broke). If the previous export can't
be fetched (first deploy, site down), only the zero check applies.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import requests

USER_AGENT = "HackWatch-CI (+https://github.com/ahmadodeh9000/HackWatch)"


def check(new_count: int, previous_count: Optional[int], min_ratio: float) -> Optional[str]:
    """Return an error message, or None if the export looks fine."""
    if new_count == 0:
        return "export has 0 events"
    if previous_count and new_count < previous_count * min_ratio:
        return (f"export has {new_count} events, less than {min_ratio:.0%} "
                f"of the {previous_count} currently deployed")
    return None


def fetch_previous_count(url: str) -> Optional[int]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        return len(resp.json())
    except (requests.RequestException, ValueError) as exc:
        print(f"Could not read previous export ({exc}); skipping the comparison.")
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("export", type=Path)
    parser.add_argument("--previous", help="URL of the currently deployed events.json")
    parser.add_argument("--min-ratio", type=float, default=0.5)
    args = parser.parse_args(argv)

    new_count = len(json.loads(args.export.read_text(encoding="utf-8")))
    previous_count = fetch_previous_count(args.previous) if args.previous else None
    print(f"New export: {new_count} events. Deployed: {previous_count if previous_count is not None else 'unknown'}.")

    error = check(new_count, previous_count, args.min_ratio)
    if error:
        print(f"::error::Refusing to deploy: {error}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
