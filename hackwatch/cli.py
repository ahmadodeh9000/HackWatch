import typer
from typing import Optional
from pathlib import Path
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
    return scrapers


@app.command()
def fetch(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter scraper by name (e.g. devpost)"),
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
            # Wrap each scraper in try/except: log error in one line and continue
            typer.echo(f"[{scraper.name}] ERROR: {exc}")

    typer.echo(f"Fetch completed. Stored/updated events (fetch run #{run_id}).")


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
        if ev.prize:
            extra.append(f"Prize: {ev.prize}")
        extra_str = f" ({', '.join(extra)})" if extra else ""

        typer.echo(f"- [{ev.source}] {ev.title}{extra_str}")
        typer.echo(f"  Dates: {date_str} | Loc: {loc}")
        typer.echo(f"  URL: {ev.url}")


if __name__ == "__main__":
    app()
