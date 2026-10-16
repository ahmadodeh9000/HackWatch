import typer
from typing import Optional
from pathlib import Path
import yaml

from hackwatch import db
from hackwatch.models import Event

app = typer.Typer(help="HackWatch: Track hackathons and developer events.")


def get_available_scrapers():
    scrapers = []
    try:
        from hackwatch.scrapers.devpost import DevpostScraper
        scrapers.append(DevpostScraper())
    except ImportError:
        pass
    try:
        from hackwatch.scrapers.manual import ManualScraper
        scrapers.append(ManualScraper())
    except ImportError:
        pass
    return scrapers


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

    run_id = db.create_fetch_run(conn)
    total_fetched = 0

    for scraper in scrapers:
        typer.echo(f"Fetching from {scraper.name}...")
        try:
            events = scraper.fetch()
            for event in events:
                db.upsert_event(conn, event, run_id=run_id)
            total_fetched += len(events)
            typer.echo(f"[{scraper.name}] OK: fetched {len(events)} events.")
        except Exception as exc:
            typer.echo(f"[{scraper.name}] ERROR: {exc}")

    typer.echo(f"Fetch completed. Stored/updated events (fetch run #{run_id}).")


@app.command()
def add(
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Event title"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Event URL"),
    dates: Optional[str] = typer.Option(None, "--dates", "-d", help="Event dates (e.g. 2026-11-01 to 2026-11-03)"),
    location: Optional[str] = typer.Option(None, "--location", "-l", help="Event location"),
    organizer: Optional[str] = typer.Option(None, "--organizer", "-o", help="Event organizer"),
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

    existing_events = []
    if yaml_file.exists():
        with open(yaml_file, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            if isinstance(content, list):
                existing_events = content
            elif isinstance(content, dict) and "events" in content:
                existing_events = content["events"]

    new_entry = {
        "title": title.strip(),
        "url": url.strip(),
        "dates": dates.strip() if dates else None,
        "location": location.strip() if location else "Online",
        "organizer": organizer.strip() if organizer else None,
    }

    # Upsert in YAML by URL
    updated = False
    norm_url = new_entry["url"].rstrip("/").lower()
    for idx, item in enumerate(existing_events):
        if str(item.get("url", "")).rstrip("/").lower() == norm_url:
            existing_events[idx] = new_entry
            updated = True
            break
    if not updated:
        existing_events.append(new_entry)

    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing_events, f, sort_keys=False, allow_unicode=True)

    action = "Updated" if updated else "Saved"
    typer.echo(f"{action} event '{title.strip()}' in {yaml_file}")


@app.command(name="list")
def list_events(
    new: bool = typer.Option(False, "--new", help="Show only events first seen in the last fetch"),
    show_all: bool = typer.Option(False, "--all", help="Show all events, including past events"),
    db_path: Path = typer.Option(db.DEFAULT_DB_PATH, "--db", help="Path to SQLite database")
):
    """List tracked events."""
    conn = db.get_connection(db_path)
    db.init_db(conn)

    events = db.get_events(conn, only_new=new, show_all=show_all)
    if not events:
        typer.echo("No events found.")
        return

    for ev in events:
        loc = "Online" if ev.is_online else (ev.location or "TBD")
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
        typer.echo(f"  Dates: {date_str} | Loc: {loc}")
        typer.echo(f"  URL: {ev.url}")


if __name__ == "__main__":
    app()
