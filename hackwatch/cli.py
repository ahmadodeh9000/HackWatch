import json
import typer
from typing import Callable, List, Optional, Tuple
from pathlib import Path
import yaml

from hackwatch import db
from hackwatch.models import Event, VALID_EVENT_TYPES, validate_event_type
from hackwatch.scrapers import get_available_scrapers
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.manual import load_manual_yaml, parse_manual_dates

app = typer.Typer(help="HackWatch: Track hackathons and developer events.")


# ─── Shared logic (also used by the interactive dashboard in hackwatch.py) ──

FetchResult = Tuple[str, int, int, Optional[str]]  # (source, kept, fetched, error)


def run_fetch(
    conn,
    scrapers: List[BaseScraper],
    on_start: Optional[Callable[[str], None]] = None,
    on_result: Optional[Callable[[str, int, int, Optional[str]], None]] = None,
) -> Tuple[int, List[FetchResult]]:
    """Run each scraper and store relevant events under a new fetch run.

    A failing scraper is reported and skipped, never stops the others.
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
            kept = sum(1 for event in events if db.upsert_event(conn, event, run_id=run_id))
            result = (scraper.name, kept, len(events), None)
        except Exception as exc:
            result = (scraper.name, 0, 0, str(exc))
        results.append(result)
        if on_result:
            on_result(*result)
    return run_id, results


def apply_source_defaults(event: Event, scraper: BaseScraper) -> None:
    """Fill fields the event left unset with the scraper's defaults."""
    if event.type is None:
        event.type = scraper.default_type


def make_manual_entry(title, url, dates, location, organizer, event_type) -> dict:
    """Build a manual_events.yaml entry, raising ValueError on bad input."""
    if not (title or "").strip() or not (url or "").strip():
        raise ValueError("title and url are required")
    dates = (dates or "").strip() or None
    parse_manual_dates(dates)  # raises on non-ISO dates
    return {
        "title": title.strip(),
        "url": url.strip(),
        "dates": dates,
        "location": (location or "").strip() or "Online",
        "organizer": (organizer or "").strip() or None,
        "type": validate_event_type(event_type),
    }


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
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter scraper by name (e.g. devpost, manual)"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database")
):
    """Fetch events from scrapers and update the database."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    all_scrapers = get_available_scrapers()
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

    def report(name, kept, total, error):
        if error:
            typer.echo(f"[{name}] ERROR: {error}")
        else:
            typer.echo(f"[{name}] OK: kept {kept} of {total} events.")

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
        entry = make_manual_entry(title, url, dates, location, organizer, event_type)
    except ValueError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(code=1)
    if entry["type"] == "other" and (event_type or "").strip().lower() not in ("", "other"):
        typer.echo(f"Warning: unknown type '{event_type}', using 'other'.")

    updated = save_manual_entry(entry, yaml_file)
    action = "Updated" if updated else "Saved"
    typer.echo(f"{action} event '{title.strip()}' in {yaml_file}")


@app.command(name="list")
def list_events(
    new: bool = typer.Option(False, "--new", help="Show only events first seen in the last fetch"),
    show_all: bool = typer.Option(False, "--all", help="Show all events, including past events"),
    event_type: Optional[str] = typer.Option(None, "--type", help=f"Filter by event type ({', '.join(VALID_EVENT_TYPES)})"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database")
):
    """List tracked events."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    events = db.get_events(
        conn,
        only_new=new,
        show_all=show_all,
        event_type=event_type,
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
        typer.echo(f"  Type: {ev.type} | Dates: {date_str} | Loc: {loc}")
        typer.echo(f"  URL: {ev.url}")


@app.command()
def export(
    out: Path = typer.Option(Path("events.json"), "--out", "-o", help="Output JSON file path"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database"),
):
    """Export upcoming events to a JSON file."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    events = db.get_events(conn, show_all=False)

    records = [
        {
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
            "is_online": ev.is_online,  # legacy, = mode != "in-person"; kept for the current site
        }
        for ev in events
    ]

    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    typer.echo(f"Exported {len(records)} events to {out}")


if __name__ == "__main__":
    app()
