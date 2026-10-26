import json
import typer
from typing import Callable, List, NamedTuple, Optional, Tuple
from pathlib import Path
import yaml

from hackwatch import db
from hackwatch.infer import apply_defaults
from hackwatch.models import (
    Event, VALID_EVENT_TYPES, VALID_MODES, VALID_SCOPES,
    validate_event_type, validate_mode, validate_scope,
)
from hackwatch.scrapers import get_available_scrapers
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.manual import load_manual_events, load_manual_yaml, parse_manual_dates
from hackwatch.taxonomy import load_taxonomy, normalize_tags

app = typer.Typer(help="HackWatch: Track hackathons and developer events.")


# ─── Shared logic (also used by the interactive dashboard in hackwatch.py) ──

class FetchResult(NamedTuple):
    source: str
    kept: int          # stored after filters
    fetched: int       # returned by the scraper
    error: Optional[str] = None
    removed: int = 0   # stored events this source no longer lists
    note: Optional[str] = None


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
            result = FetchResult(scraper.name, 0, 0, error=str(exc))
        results.append(result)
        if on_result:
            on_result(result)
    db.rebuild_events(conn)
    return run_id, results


def apply_source_defaults(event: Event, scraper: BaseScraper) -> None:
    """Fill fields the event left unset: inferred type/tags, then the source's defaults."""
    apply_defaults(event, scraper.default_type, scraper.default_tags,
                   scraper.default_scope, scraper.allowed_types, scraper.infer_tags)


def make_manual_entry(title, url, dates, location, organizer, event_type,
                      mode=None, tags=None, scope=None) -> dict:
    """Build a manual_events.yaml entry, raising ValueError on bad input.

    mode, tags and scope are only written when given, to keep the YAML short.
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


@app.command()
def fetch(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Only this source from sources.yaml (runs even if disabled)"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database")
):
    """Fetch events from scrapers and update the database."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

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

    run_id, _ = run_fetch(
        conn, scrapers,
        on_start=lambda name: typer.echo(f"Fetching from {name}..."),
        on_result=report,
    )
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
    yaml_file: Path = typer.Option(Path("manual_events.yaml"), "--file", help="Path to manual YAML file"),
):
    """Add a manual event to manual_events.yaml (prompts if options omitted)."""
    if not title:
        title = typer.prompt("Title")
    if not url:
        url = typer.prompt("URL")
    if not dates:
        dates = typer.prompt("Dates (e.g. 2026-11-01 to 2026-11-03)", default="")
    if not location:
        location = typer.prompt("Location", default="Online")
    if not organizer:
        organizer = typer.prompt("Organizer", default="")
    if not event_type:
        event_type = typer.prompt(f"Type ({', '.join(VALID_EVENT_TYPES)})", default="other")

    try:
        entry = make_manual_entry(title, url, dates, location, organizer, event_type, mode, tags, scope)
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)

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
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
):
    """Export upcoming events to a JSON file."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    events = db.get_events(conn, show_all=False)

    records = [
        {
            "id": ev.id,
            "title": ev.title,
            "url": ev.url,
            "source": ev.source,
            "type": ev.type,
            "start_date": ev.start_date,
            "end_date": ev.end_date,
            "location": ev.location,
            "organizer": ev.organizer,
            "prize": ev.prize,
            "description": ev.description,
            "mode": ev.mode,
            "tags": ev.tags,
            "scope": ev.scope,
            "sources": ev.sources,
            "urls": ev.urls,
            "is_online": ev.is_online,  # legacy, = mode != "in-person"; kept for the current site
        }
        for ev in events
    ]

    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    typer.echo(f"Exported {len(records)} events to {out}")

    if labels:
        taxonomy = load_taxonomy()
        with open(labels, "w", encoding="utf-8") as f:
            json.dump({
                "types": list(VALID_EVENT_TYPES),
                "tags": {tag: (info or {}).get("label", tag) for tag, info in (taxonomy.get("tags") or {}).items()},
            }, f, indent=2, ensure_ascii=False)
        typer.echo(f"Wrote labels to {labels}")


if __name__ == "__main__":
    app()
