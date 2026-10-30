import json
import os
import time
import typer
from typing import Callable, List, NamedTuple, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path
import yaml

from hackwatch import db
from hackwatch.carryover import MIN_PREVIOUS_EVENTS, carry_over, load_json, load_previous
from hackwatch.digest import build_digest, to_markdown, to_text
from hackwatch.feeds import build_feed, build_sitemap, first_seen_dates
from hackwatch.formimport import import_csv
from hackwatch.fromurl import extract_from_url, suggest
from hackwatch.pages import write_calendar_files, write_pages
from hackwatch.health import sync_freshness, STATUS_URL, ZERO_RUNS_FOR_ISSUE, DryRunIssues, GitHubIssues, sync_issues, update_streaks
from hackwatch.ics import build_calendar, calendar_events
from hackwatch.infer import apply_defaults
from hackwatch.models import (
    Event, VALID_EVENT_TYPES, VALID_MODES, VALID_SCOPES,
    validate_event_type, validate_mode, validate_scope,
)
from hackwatch.series import fix_session_ends, merge_series
from hackwatch.tidy import city_of, shown_title
from hackwatch.scrapers import get_available_scrapers
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.manual import load_manual_events, load_manual_yaml, parse_manual_dates, parse_manual_item
from hackwatch.sources import load_sources
from hackwatch.taxonomy import normalize_tags, site_labels

app = typer.Typer(help="HackWatch: Track hackathons and developer events.")


# ─── Shared logic (also used by the interactive dashboard in hackwatch.py) ──

class FetchResult(NamedTuple):
    source: str
    kept: int          # stored after filters
    fetched: int       # returned by the scraper
    error: Optional[str] = None
    removed: int = 0   # stored events this source no longer lists
    note: Optional[str] = None
    seconds: float = 0.0
    requests: tuple = ()   # the scraper's request log (dicts: url, status, seconds, error, hint)

    def summary(self) -> dict:
        """One row of the fetch report: what happened and, if empty, likely why."""
        statuses: dict = {}
        for r in self.requests:
            key = str(r.get("status") or "no response")
            statuses[key] = statuses.get(key, 0) + 1
        return {
            "source": self.source,
            "ok": self.error is None,
            "kept": self.kept, "fetched": self.fetched, "removed": self.removed,
            "seconds": round(self.seconds, 1),
            "requests": len(self.requests),
            "http_status": statuses,
            "slowest_request_s": max((r.get("seconds") or 0 for r in self.requests), default=0),
            "block_hints": sorted({r["hint"] for r in self.requests if r.get("hint")}),
            "request_errors": [r["error"] for r in self.requests if r.get("error")][:3],
            "error": self.error,
            "note": self.note,
        }


# A source that suddenly returns nothing but had at least this many events is
# more likely broken (site redesign) than empty, so its events are kept.
EMPTY_RESULT_GUARD = 3


def run_fetch(
    conn,
    scrapers: List[BaseScraper],
    on_start: Optional[Callable[[str], None]] = None,
    on_result: Optional[Callable[[FetchResult], None]] = None,
) -> Tuple[int, List[FetchResult]]:
    """Run each scraper, store what it lists, then merge duplicates across sources.

    A source that fetched successfully replaces its previous events (so events it
    no longer lists disappear). A failing source is reported and its stored events
    are left untouched; it never stops the others.
    """
    run_id = db.create_fetch_run(conn)
    results: List[FetchResult] = []
    for scraper in scrapers:
        if on_start:
            on_start(scraper.name)
        started = time.monotonic()
        scraper.request_log = []
        try:
            events = scraper.fetch()
            for event in events:
                apply_source_defaults(event, scraper)
            stored = db.count_observations(conn, scraper.name)
            if not events and stored >= EMPTY_RESULT_GUARD:
                result = FetchResult(scraper.name, 0, 0, note=(
                    f"returned nothing; kept its {stored} stored events in case the source is broken"))
            else:
                kept, removed = db.replace_source_events(conn, scraper.name, events, run_id=run_id,
                                                         require_tech=scraper.require_tech_keywords)
                result = FetchResult(scraper.name, kept, len(events), removed=removed)
        except Exception as exc:
            result = FetchResult(scraper.name, 0, 0, error=f"{type(exc).__name__}: {exc}"[:500])
        result = result._replace(seconds=time.monotonic() - started, requests=tuple(scraper.request_log))
        results.append(result)
        if on_result:
            on_result(result)
    db.rebuild_events(conn)
    return run_id, results


def fetch_report_markdown(rows: List[dict]) -> str:
    """The fetch report as a Markdown table (readable in the log and the job summary)."""
    lines = ["| Source | Result | Kept / fetched | Requests | HTTP status | Time | Problem |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        result = "OK" if r["ok"] else "ERROR"
        if r["ok"] and r["note"]:
            result = "KEPT OLD"
        statuses = ", ".join(f"{code}×{n}" for code, n in sorted(r["http_status"].items())) or "-"
        problem = r["error"] or r["note"] or "; ".join(r["block_hints"] + r["request_errors"]) or ""
        lines.append(f"| {r['source']} | {result} | {r['kept']} / {r['fetched']} | {r['requests']} | "
                     f"{statuses} | {r['seconds']} s | {problem.replace('|', '/')[:300]} |")
    return "\n".join(lines)


def apply_source_defaults(event: Event, scraper: BaseScraper) -> None:
    """Fill fields the event left unset: inferred type/tags, then the source's defaults."""
    apply_defaults(event, scraper.default_type, scraper.default_tags,
                   scraper.default_scope, scraper.allowed_types, scraper.infer_tags)


def make_manual_entry(title, url, dates, location, organizer, event_type,
                      mode=None, tags=None, scope=None, start_time=None, end_time=None,
                      registration_deadline=None, description=None, cost=None, certificate=None,
                      open_to=None) -> dict:
    """Build a manual_events.yaml entry, raising ValueError on bad input.

    Optional fields are only written when given, to keep the YAML short. The entry is
    checked with the same rules as `validate` before it's returned.
    """
    if not (title or "").strip() or not (url or "").strip():
        raise ValueError("title and url are required")
    dates = (dates or "").strip() or None
    parse_manual_dates(dates)  # raises on non-ISO dates
    entry = {
        "title": title.strip(),
        "url": url.strip(),
        "dates": dates,
        "location": (location or "").strip() or "Online",
        "organizer": (organizer or "").strip() or None,
        "type": validate_event_type(event_type, strict=True),
    }
    if (mode or "").strip():
        entry["mode"] = validate_mode(mode)
    tag_list = normalize_tags(tags, strict=True)
    if tag_list:
        entry["tags"] = tag_list
    if (scope or "").strip():
        entry["scope"] = validate_scope(scope)
    for key, value in (("start_time", start_time), ("end_time", end_time),
                       ("registration_deadline", registration_deadline)):
        if (value or "").strip():
            entry[key] = value.strip()
    if (description or "").strip():
        entry["description"] = " ".join(description.split())
    if (cost or "").strip():
        entry["cost"] = cost.strip().lower()
    if certificate is not None:
        entry["certificate"] = bool(certificate)
    if (open_to or "").strip():
        entry["open_to"] = open_to.strip().lower()
    parse_manual_item(entry)  # same checks as the import (times, deadline vs. dates...)
    return entry


def _check_choice(value: Optional[str], validator) -> Optional[str]:
    """Validate an optional CLI value, exiting with a readable error."""
    if value is None:
        return None
    try:
        return validator(value)
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)


def save_manual_entry(entry: dict, yaml_file: Path) -> bool:
    """Insert entry into the YAML file, replacing one with the same URL. Returns True if replaced."""
    existing_events = load_manual_yaml(yaml_file) if yaml_file.exists() else []
    if isinstance(existing_events, dict):
        existing_events = existing_events.get("events", [])
    existing_events = existing_events or []

    updated = False
    norm_url = entry["url"].rstrip("/").lower()
    for idx, item in enumerate(existing_events):
        if isinstance(item, dict) and str(item.get("url", "")).rstrip("/").lower() == norm_url:
            existing_events[idx] = entry
            updated = True
            break
    if not updated:
        existing_events.append(entry)

    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing_events, f, sort_keys=False, allow_unicode=True)
    return updated


def _render_digest_png(built, path: Path) -> None:
    from hackwatch.digestimage import render
    for warning in render(built, path):
        typer.echo(f"Warning: {warning}", err=True)
    typer.echo(f"Wrote the digest image ({len(built.this_week)} events this week) to {path}")


@app.command()
def fetch(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Only this source from sources.yaml (runs even if disabled)"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
    report_path: Optional[Path] = typer.Option(None, "--report", help="Write a per-source JSON report (HTTP codes, timings, errors)"),
):
    """Fetch events from scrapers and update the database."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    report_rows = []
    # Naming a source runs it even if it's disabled in sources.yaml.
    all_scrapers = get_available_scrapers(include_disabled=bool(source))
    if source:
        scrapers = [s for s in all_scrapers if s.name.lower() == source.lower()]
        if not scrapers:
            typer.echo(f"Unknown or unavailable source: {source}")
            raise typer.Exit(code=1)
    else:
        scrapers = all_scrapers

    if not scrapers:
        typer.echo("No scrapers registered.")
        return

    def report(r: FetchResult):
        if r.error:
            typer.echo(f"[{r.source}] ERROR: {r.error} (stored events left unchanged)")
        elif r.note:
            typer.echo(f"[{r.source}] WARNING: {r.note}")
        else:
            removed = f", removed {r.removed} no longer listed" if r.removed else ""
            typer.echo(f"[{r.source}] OK: kept {r.kept} of {r.fetched} events{removed}.")

    run_id, results = run_fetch(
        conn, scrapers,
        on_start=lambda name: typer.echo(f"Fetching from {name}..."),
        on_result=report,
    )
    report_rows = [r.summary() for r in results]
    table = fetch_report_markdown(report_rows)
    typer.echo("\n" + table)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("## Fetch report\n\n" + table + "\n")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "sources": report_rows}, f, indent=2, ensure_ascii=False)
    typer.echo(f"Fetch completed. Stored/updated events (fetch run #{run_id}).")


@app.command()
def add(
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Event title"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Event URL"),
    dates: Optional[str] = typer.Option(None, "--dates", "-d", help="Event dates (e.g. 2026-11-01 to 2026-11-03)"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Event location"),
    organizer: Optional[str] = typer.Option(None, "--organizer", "-o", help="Event organizer"),
    event_type: Optional[str] = typer.Option(None, "--type", help=f"Event type ({', '.join(VALID_EVENT_TYPES)}); default: other"),
    mode: Optional[str] = typer.Option(None, "--mode", help=f"{' | '.join(VALID_MODES)} (default: from location)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags from taxonomy.yaml, e.g. 'ai,web'"),
    scope: Optional[str] = typer.Option(None, "--scope", help=f"{' | '.join(VALID_SCOPES)} (default: jordan)"),
    start_time: Optional[str] = typer.Option(None, "--start-time", help="Start time in Amman, 24 h (e.g. 18:00)"),
    end_time: Optional[str] = typer.Option(None, "--end-time", help="End time in Amman, 24 h"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Registration deadline (YYYY-MM-DD)"),
    description: Optional[str] = typer.Option(None, "--description", help="A few sentences about the event"),
    cost: Optional[str] = typer.Option(None, "--cost", help="free | paid"),
    certificate: Optional[bool] = typer.Option(None, "--certificate/--no-certificate", help="Attendees get a certificate"),
    open_to: Optional[str] = typer.Option(None, "--open-to", help="anyone | students | members"),
    from_url: Optional[str] = typer.Option(None, "--from-url", help="Pre-fill from the event page (JSON-LD, calendar link, Open Graph, Google Form)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="With --from-url: don't prompt, use what was found"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the entry instead of saving it"),
    yaml_file: Path = typer.Option(Path("manual_events.yaml"), "--file", help="Path to manual YAML file"),
):
    """Add a manual event to manual_events.yaml (prompts if options omitted)."""
    if from_url:
        try:
            found = extract_from_url(from_url)
        except ValueError as exc:
            typer.echo(f"Error: {exc}")
            raise typer.Exit(code=1)
        guess = suggest(found)
        typer.echo(f"Found on {from_url}:")
        for key in ("title", "dates", "start_time", "end_time", "location", "mode", "organizer", "deadline", "type", "tags"):
            if key in guess:
                how = found.found_by.get({"dates": "start_date", "deadline": "registration_deadline"}.get(key, key), "inferred")
                typer.echo(f"  {key:11} {guess[key]}  [{how}]")
        for warning in found.warnings:
            typer.echo(f"  ! {warning}")
        given = {"title": title, "dates": dates, "location": location, "organizer": organizer, "type": event_type,
                 "mode": mode, "tags": tags, "start_time": start_time, "end_time": end_time, "deadline": deadline}
        labels = {"title": "Title", "dates": "Dates (e.g. 2026-11-01 to 2026-11-03)", "location": "Location",
                  "organizer": "Organizer", "type": f"Type ({', '.join(VALID_EVENT_TYPES)})", "mode": "Mode",
                  "tags": "Tags (comma-separated)", "start_time": "Start time (HH:MM)", "end_time": "End time (HH:MM)",
                  "deadline": "Registration deadline (YYYY-MM-DD)"}
        for key, value in given.items():
            if value is None:
                given[key] = guess.get(key) if yes else typer.prompt(labels[key], default=guess.get(key, ""), show_default=True)
        title, dates, location, organizer, event_type, mode, tags, start_time, end_time, deadline = given.values()
        url = url or from_url
        description = description or guess.get("description")
        if yes:
            if not (title and dates):
                typer.echo("Error: no title or date found on the page; run without --yes to enter them.")
                raise typer.Exit(code=1)
            if not location:
                typer.echo("  ! No location found; saving it as Online. Edit manual_events.yaml if it's in person.")
            location, organizer, event_type = location or "Online", organizer or "", event_type or "other"
    if not title:
        title = typer.prompt("Title")
    if not url:
        url = typer.prompt("URL")
    if not dates:
        dates = typer.prompt("Dates (e.g. 2026-11-01 to 2026-11-03)", default="")
    if not location:
        location = typer.prompt("Location", default="Online")
    if organizer is None:  # "" = asked already (or --from-url --yes found none)
        organizer = typer.prompt("Organizer", default="")
    if not event_type:
        event_type = typer.prompt(f"Type ({', '.join(VALID_EVENT_TYPES)})", default="other")

    try:
        entry = make_manual_entry(title, url, dates, location, organizer, event_type, mode, tags, scope,
                                  start_time, end_time, deadline, description, cost, certificate, open_to)
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)
    if dry_run:
        typer.echo(yaml.safe_dump([entry], sort_keys=False, allow_unicode=True), nl=False)
        return

    updated = save_manual_entry(entry, yaml_file)
    action = "Updated" if updated else "Saved"
    typer.echo(f"{action} event '{title.strip()}' in {yaml_file}")


@app.command()
def validate(
    yaml_file: Path = typer.Option(Path("manual_events.yaml"), "--file", help="Path to manual YAML file"),
):
    """Strictly check manual_events.yaml; exit 1 if any entry is invalid."""
    if not yaml_file.exists():
        typer.echo(f"Error: {yaml_file} does not exist")
        raise typer.Exit(code=1)
    try:
        events, errors = load_manual_events(yaml_file)
    except yaml.YAMLError as exc:
        typer.echo(f"Error: {yaml_file} is not valid YAML:\n{exc}")
        raise typer.Exit(code=1)
    for message in errors:
        typer.echo(f"Error: {message}")
    if errors:
        typer.echo(f"{yaml_file}: {len(errors)} invalid, {len(events)} valid entries.")
        raise typer.Exit(code=1)
    typer.echo(f"{yaml_file}: all {len(events)} entries are valid.")


@app.command(name="carry-over")
def carry_over_command(
    previous: str = typer.Option(..., "--previous", help="URL or path of the previously deployed events.json"),
    min_events: int = typer.Option(MIN_PREVIOUS_EVENTS, "--min-events", help="Only for sources that had at least this many events"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
):
    """Keep the last deployed events of sources that returned nothing this run (marked stale)."""
    conn = db.get_connection(db_path)
    db.init_db(conn)
    old = load_previous(previous)
    if old is None:
        typer.echo(f"Could not read the previous export at {previous}; nothing carried over.")
        return
    sources = [s.name for s in get_available_scrapers()]
    restored = carry_over(conn, old, sources, min_events=min_events)
    lines = []
    for source, n in restored.items():
        had = sum(1 for r in old if r.get("source") == source)
        kept = (f"kept {n} upcoming events from the last deploy, marked stale." if n else
                "its kept events are over 7 days stale or already over, so none were kept.")
        lines.append(f"{source} returned no events this run (it had {had} in the last deploy); {kept}")
    for line in lines:
        typer.echo(f"::warning title=Source returned nothing::{line}")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file and lines:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("## ⚠️ Deploy guard\n\n" + "\n".join(f"- {line}" for line in lines) +
                    "\n\nCheck the fetch report above for the HTTP status and error.\n")
    if not lines:
        typer.echo("Every source that had events in the last deploy returned some; nothing carried over.")


@app.command()
def health(
    status_path: Path = typer.Option(Path("docs/status.json"), "--status", help="This run's fetch report (updated in place)"),
    previous: str = typer.Option(STATUS_URL, "--previous", help="URL or path of the previously deployed status.json"),
    threshold: int = typer.Option(ZERO_RUNS_FOR_ISSUE, "--threshold", help="Empty runs in a row before an issue is opened"),
):
    """Track sources that keep returning nothing; open/close "Source down" issues.

    Needs GITHUB_TOKEN and GITHUB_REPOSITORY (set in GitHub Actions); without them it
    only prints what it would do.
    """
    current = json.loads(status_path.read_text(encoding="utf-8"))
    prior = load_json(previous)
    exempt = [c.name for c in load_sources() if c.may_be_empty]
    update_streaks(current, prior, exempt)
    status_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in current["sources"]:
        if row["zero_streak"]:
            typer.echo(f"{row['source']}: empty {row['zero_streak']} run(s) in a row")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    run_url = None
    if repo and os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    api = GitHubIssues(repo, token) if token and repo else DryRunIssues(typer.echo)
    actions = sync_issues(current, api, threshold=threshold, run_url=run_url, log=typer.echo)
    if not actions:
        typer.echo("No source issues to open or close.")


@app.command()
def freshness(
    status_url: str = typer.Option(STATUS_URL, "--status", help="URL or path of the deployed status.json"),
):
    """Open/update a "Site not updating" issue if the last deploy is over 36 hours old."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    api = GitHubIssues(repo, token) if token and repo else DryRunIssues(typer.echo)
    sync_freshness(load_json(status_url), api, log=typer.echo)


@app.command()
def discover(
    pages_file: Path = typer.Option(Path("discovery.yaml"), "--pages", help="Pages to look at"),
    listed: str = typer.Option("https://ahmadodeh9000.github.io/HackWatch/events.json", "--listed", help="URL or path of events.json, to skip what's listed"),
):
    """Look for Jordan tech events we don't list and update the "Candidate events" issue. Publishes nothing."""
    from hackwatch.discovery import run
    pages = (yaml.safe_load(pages_file.read_text(encoding="utf-8")) or {}).get("pages") or []
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    api = GitHubIssues(repo, token) if token and repo else DryRunIssues(typer.echo)
    run(pages, load_json(listed) or [], api, log=typer.echo)


@app.command(name="import-form")
def import_form(
    csv_path: Path = typer.Argument(..., help="Google Form responses exported as CSV"),
    yaml_file: Path = typer.Option(Path("manual_events.yaml"), "--file", help="Path to manual YAML file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Check the rows without changing the YAML"),
):
    """Add Google Form submissions to manual_events.yaml (validated; duplicates skipped).

    Review the diff before committing: the form is open to anyone.
    """
    if not csv_path.exists():
        typer.echo(f"Error: {csv_path} does not exist")
        raise typer.Exit(code=1)
    result = import_csv(csv_path, yaml_file, dry_run=dry_run)
    verb = "Would add" if dry_run else "Added"
    for title in result.added:
        typer.echo(f"{verb}: {title}")
    for line in result.duplicates:
        typer.echo(f"Skipped duplicate: {line}")
    for line in result.errors:
        typer.echo(f"Error: {line}")
    typer.echo(f"{verb} {len(result.added)}, skipped {len(result.duplicates)} duplicate(s), "
               f"{len(result.errors)} invalid.")
    if result.errors:
        raise typer.Exit(code=1)


@app.command()
def digest(
    week: bool = typer.Option(True, "--week/--no-week", help="The next 7 days (the only period for now)"),
    fmt: str = typer.Option("text", "--format", "-f", help="text (WhatsApp/Telegram) or markdown"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Write to a file instead of printing"),
    png: Optional[Path] = typer.Option(None, "--png", help="Also render a 1080x1350 image of it here (needs Pillow)"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
):
    """'This week in Jordan tech': events in the next 7 days and registrations closing soon."""
    if fmt not in ("text", "markdown"):
        typer.echo("Error: --format must be text or markdown")
        raise typer.Exit(code=1)
    conn = db.get_connection(db_path)
    db.init_db(conn)
    built = build_digest(db.get_events(conn, show_all=False))
    text = to_text(built) if fmt == "text" else to_markdown(built)
    if png:
        _render_digest_png(built, png)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {len(built.this_week)} events this week ({len(built.closing)} closing soon) to {out}")
    else:
        typer.echo(text, nl=False)


@app.command(name="list")
def list_events(
    new: bool = typer.Option(False, "--new", help="Show only events first seen in the last fetch"),
    show_all: bool = typer.Option(False, "--all", help="Show all events, including past events"),
    event_type: Optional[str] = typer.Option(None, "--type", help=f"Filter by event type ({', '.join(VALID_EVENT_TYPES)})"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Filter by tag (repeat to require several)"),
    mode: Optional[str] = typer.Option(None, "--mode", help=f"Filter by mode ({', '.join(VALID_MODES)})"),
    scope: Optional[str] = typer.Option(None, "--scope", help=f"Filter by scope ({', '.join(VALID_SCOPES)})"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database")
):
    """List tracked events."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    events = db.get_events(
        conn,
        only_new=new,
        show_all=show_all,
        event_type=_check_choice(event_type, validate_event_type),
        tags=_check_choice(tag, lambda t: normalize_tags(t, strict=True)),
        mode=_check_choice(mode, validate_mode),
        scope=_check_choice(scope, validate_scope),
    )
    if not events:
        typer.echo("No events found.")
        return

    for ev in events:
        loc = "Online" if ev.mode == "online" else (ev.location or "TBD")
        if ev.mode == "hybrid":
            loc += " + online (hybrid)"
        date_str = ev.start_date or ev.registration_deadline or "TBD"
        if ev.end_date and ev.end_date != ev.start_date:
            date_str += f" -> {ev.end_date}"
        extra = []
        if ev.organizer:
            extra.append(f"by {ev.organizer}")
        prize_display = ev.prize if (ev.prize and ev.prize != "$0") else "N/A"
        extra.append(f"Prize: {prize_display}")
        extra_str = f" ({', '.join(extra)})" if extra else ""

        typer.echo(f"- [{ev.source}] {ev.title}{extra_str}")
        typer.echo(f"  Type: {ev.type} | Mode: {ev.mode} | Scope: {ev.scope} | Dates: {date_str} | Loc: {loc}")
        if ev.tags:
            typer.echo(f"  Tags: {', '.join(ev.tags)}")
        typer.echo(f"  URL: {ev.url}")


@app.command()
def export(
    out: Path = typer.Option(Path("events.json"), "--out", "-o", help="Output JSON file path"),
    labels: Optional[Path] = typer.Option(None, "--labels", help="Also write tag/type labels (for the site) to this JSON file"),
    ics: Optional[Path] = typer.Option(None, "--ics", help="Also write an iCalendar feed of Jordan events to this file"),
    digest_path: Optional[Path] = typer.Option(None, "--digest", help="Also write this week's digest (WhatsApp/Telegram text) here"),
    digest_png: Optional[Path] = typer.Option(None, "--digest-png", help="Also render this week's digest as a 1080x1350 PNG here"),
    sitemap: Optional[Path] = typer.Option(None, "--sitemap", help="Also write sitemap.xml (site + share pages) here"),
    feed_path: Optional[Path] = typer.Option(None, "--feed", help="Also write an Atom feed of new Jordan events here"),
    previous: Optional[str] = typer.Option(None, "--previous", help="URL or path of the last deployed events.json, to keep each event's first_seen date"),
    pages_dir: Optional[Path] = typer.Option(None, "--pages", help="Also write one shareable HTML page per event into this folder"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
):
    """Export upcoming events to a JSON file."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    today = datetime.now().date()
    # Weekly series listed with run-long end dates become one-day sessions (series.py);
    # sessions that are over by now drop out.
    events = [e for e in fix_session_ends(db.get_events(conn, show_all=False))
              if (e.end_date or e.start_date or "9999")[:10] >= today.isoformat()]

    items = merge_series(events, today)
    # CI starts from an empty database, so "new" is only known by comparing with the last deploy.
    first_seen = first_seen_dates(load_json(previous)) if previous else {}
    records = [
        {
            "id": ev.id,
            "title": ev.title,
            # Display version of ALL-CAPS titles (tidy.py); only when it differs.
            **({"display_title": shown_title(ev)} if shown_title(ev) != ev.title else {}),
            "url": ev.url,
            "source": ev.source,
            "type": ev.type,
            "start_date": ev.start_date,
            "end_date": ev.end_date,
            "start_time": ev.start_time,
            "end_time": ev.end_time,
            "registration_deadline": ev.registration_deadline,
            "location": ev.location,
            "city": city_of(ev),   # for the site's city filter (tidy.py)
            "organizer": ev.organizer,
            "prize": ev.prize,
            "description": ev.description,
            "mode": ev.mode,
            "tags": ev.tags,
            "scope": ev.scope,
            "sources": ev.sources,
            "urls": ev.urls,
            "stale": ev.stale,
            "low_signal": bool(ev.low_signal),
            "first_seen": first_seen.get(ev.id, today.isoformat()),
            # Optional facts (None = unknown; the site shows nothing then).
            "cost": ev.cost,
            "certificate": ev.certificate,
            "open_to": ev.open_to,
            "stale_since": ev.stale_since,
            "is_online": ev.is_online,  # legacy, = mode != "in-person"; kept for the current site
            # Weekly series (series.py): this record is the next session; all upcoming ones here.
            **({"recurrence": "weekly", "sessions": item["sessions"], "series_until": item["until"]}
               if item["sessions"] else {}),
        }
        for item in items
        for ev in [item["event"]]
    ]

    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    typer.echo(f"Exported {len(records)} events to {out}")

    if labels:
        with open(labels, "w", encoding="utf-8") as f:
            json.dump(site_labels(), f, indent=2, ensure_ascii=False)
        typer.echo(f"Wrote labels to {labels}")

    if ics:
        # Includes events that ended recently, so subscribers' calendars keep them.
        feed = calendar_events(fix_session_ends(db.get_events(conn, show_all=True)), scope="jordan")
        with open(ics, "w", encoding="utf-8", newline="") as f:
            f.write(build_calendar(feed))
        typer.echo(f"Wrote {len(feed)} Jordan events to {ics}")

    if digest_path:
        digest_path.write_text(to_text(build_digest(events)), encoding="utf-8")
        typer.echo(f"Wrote this week's digest to {digest_path}")
    if digest_png:
        _render_digest_png(build_digest(events), digest_png)

    if sitemap:
        sitemap.write_text(build_sitemap([item["event"] for item in items]), encoding="utf-8")
        typer.echo(f"Wrote the sitemap to {sitemap}")
    if feed_path:
        feed_path.write_text(build_feed([item["event"] for item in items], first_seen), encoding="utf-8")
        typer.echo(f"Wrote the feed to {feed_path}")

    if pages_dir:
        typer.echo(f"Wrote {write_pages(events, pages_dir)} event pages to {pages_dir}/")
        typer.echo(f"Wrote {write_calendar_files(items, pages_dir)} calendar files to {pages_dir}/")


if __name__ == "__main__":
    app()
