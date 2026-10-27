"""Check candidate sources from wherever this runs (meant for the GitHub runner).

Eventbrite worked from a home connection but returns 405 + captcha to GitHub's
runners, so candidates are tested from the runner before a scraper is built.
Results are printed as a Markdown table; with GITHUB_TOKEN/GITHUB_REPOSITORY set,
they're also posted as a comment on an issue titled "Runner probe" (public, so the
results can be read without signing in to Actions).
"""
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hackwatch.health import GitHubIssues  # noqa: E402
from hackwatch.scrapers.base import DEFAULT_USER_AGENT, block_hint  # noqa: E402

# (name, url, text that should be in a useful response, seconds to wait afterwards)
CANDIDATES = [
    ("GDG chapter page", "https://gdg.community.dev/gdg-amman/", "/events/details/", 2),
    ("GDG event page", "https://gdg.community.dev/events/details/google-gdg-amman-presents-devfest-amman-2026/",
     "application/ld+json", 2),
    ("Startup Grind chapter page", "https://www.startupgrind.com/amman/", "/events/details/", 2),
    ("Startup Grind event page",
     "https://www.startupgrind.com/events/details/startup-grind-amman-presents-founders-day-amman/",
     "application/ld+json", 2),
    ("GJU events calendar", "https://www.gju.edu.jo/gju-event", "-2026", 10),
    ("Shamal Start events API", "https://www.shamalstart.com/wp-json/tribe/events/v1/events", '"events"', 2),
    ("JUST calendar", "https://www.just.edu.jo/calendar", "calendar", 2),
    ("Luma Amman", "https://luma.com/amman", "__NEXT_DATA__", 2),
    ("IEEE vTools API", "https://events.vtools.ieee.org/RST/events/api/public/v8/events/list?limit=1", '"data"', 2),
    ("Eventbrite Jordan (known blocked)", "https://www.eventbrite.com/d/jordan/tech/", "application/ld+json", 2),
]


def probe(session=requests):
    rows = []
    for name, url, marker, wait in CANDIDATES:
        started = time.monotonic()
        try:
            resp = session.get(url, headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=60)
            text = resp.text or ""
            rows.append({"name": name, "url": url, "status": resp.status_code,
                         "kb": round(len(resp.content or b"") / 1024), "seconds": round(time.monotonic() - started, 1),
                         "has_data": marker in text, "hint": block_hint(resp) or ""})
        except requests.RequestException as exc:
            rows.append({"name": name, "url": url, "status": None, "kb": 0,
                         "seconds": round(time.monotonic() - started, 1), "has_data": False,
                         "hint": f"{type(exc).__name__}: {str(exc)[:120]}"})
        time.sleep(wait)
    return rows


def markdown(rows) -> str:
    lines = ["| Candidate | HTTP | Size | Time | Data found | Notes |", "|---|---|---|---|---|---|"]
    for r in rows:
        ok = "✅" if r["status"] == 200 and r["has_data"] else "❌"
        lines.append(f"| [{r['name']}]({r['url']}) | {r['status'] or '-'} | {r['kb']} KB | {r['seconds']} s | "
                     f"{ok} | {r['hint'].replace('|', '/')} |")
    return "\n".join(lines)


def main() -> int:
    table = markdown(probe())
    print(table)
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo:
        api = GitHubIssues(repo, token)
        title = "Runner probe"
        issue = api.find_open(title) or api.create(title, "Candidate sources fetched from a GitHub Actions runner. "
                                                          "Each run of `.github/workflows/probe.yml` adds a comment.")
        api.comment(issue["number"], f"Run {os.environ.get('GITHUB_RUN_ID', '')}:\n\n{table}")
        print(f"Posted to issue #{issue['number']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
