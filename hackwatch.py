#!/usr/bin/env python3
"""
HackWatch — Interactive Terminal Dashboard
Launch with:  python3 hackwatch.py
"""

import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.columns import Columns
from rich.align import Align
from rich import box

from hackwatch import db
from hackwatch.cli import make_manual_entry, run_fetch, save_manual_entry
from hackwatch.models import Event, VALID_EVENT_TYPES, VALID_MODES
from hackwatch.scrapers import get_available_scrapers

console = Console()

# ─── Constants ──────────────────────────────────────────────────────────────
DB_PATH = Path("hackwatch.db")

LOGO = r"""
 ██╗  ██╗ █████╗  ██████╗██╗  ██╗██╗    ██╗ █████╗ ████████╗ ██████╗██╗  ██╗
 ██║  ██║██╔══██╗██╔════╝██║ ██╔╝██║    ██║██╔══██╗╚══██╔══╝██╔════╝██║  ██║
 ███████║███████║██║     █████╔╝ ██║ █╗ ██║███████║   ██║   ██║     ███████║
 ██╔══██║██╔══██║██║     ██╔═██╗ ██║███╗██║██╔══██║   ██║   ██║     ██╔══██║
 ██║  ██║██║  ██║╚██████╗██║  ██╗╚███╔███╔╝██║  ██║   ██║   ╚██████╗██║  ██║
 ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝
"""

SOURCE_COLORS = {
    "devpost": "bright_cyan",
    "eventbrite": "bright_red",
    "gdg": "bright_green",
    "josa": "bright_yellow",
    "manual": "bright_magenta",
}


# ─── Helpers ────────────────────────────────────────────────────────────────

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def get_connection():
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    return conn


def format_date_range(ev: Event) -> str:
    """Pretty-format a date range for display."""
    start = ev.start_date
    end = ev.end_date
    deadline = ev.registration_deadline

    if start and end and start != end:
        return f"{start}  →  {end}"
    if start:
        return start
    if deadline:
        return f"Deadline: {deadline}"
    return "TBD"


def format_location(ev: Event) -> str:
    if ev.mode == "online":
        return "🌐 Online"
    loc = ev.location or "TBD"
    return f"🔀 Hybrid: {loc} + online" if ev.mode == "hybrid" else loc


def days_until(date_str: str | None) -> int | None:
    """Return days from today until date_str (ISO), or None."""
    if not date_str:
        return None
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (target - date.today()).days
    except ValueError:
        return None


def urgency_style(days: int | None) -> str:
    """Return a rich color style based on how soon an event is."""
    if days is None:
        return "dim"
    if days < 0:
        return "dim strike"
    if days <= 3:
        return "bold bright_red"
    if days <= 7:
        return "bold yellow"
    if days <= 30:
        return "bright_green"
    return "white"


# ─── Display Functions ──────────────────────────────────────────────────────

def show_header():
    console.print(
        Panel(
            Align.center(Text(LOGO, style="bold bright_cyan")),
            subtitle="[dim]Track hackathons & developer events[/dim]",
            border_style="bright_blue",
            padding=(0, 2),
        )
    )


def show_menu():
    menu_items = [
        ("1", "📋  Browse Events",     "View all tracked events"),
        ("2", "🔄  Fetch New Events",   "Scrape fresh data from all sources"),
        ("3", "🆕  Show New Events",    "Events discovered in the last fetch"),
        ("4", "📊  Dashboard",          "Quick stats overview"),
        ("5", "➕  Add Manual Event",   "Add an event to manual_events.yaml"),
        ("6", "🔍  Search Events",      "Search events by keyword"),
        ("0", "🚪  Exit",               "Quit HackWatch"),
    ]
    table = Table(
        show_header=False, box=box.SIMPLE_HEAVY, border_style="bright_blue",
        pad_edge=True, expand=False,
    )
    table.add_column("Key", style="bold bright_cyan", width=3)
    table.add_column("Action", style="bold white", min_width=22)
    table.add_column("Description", style="dim")

    for key, action, desc in menu_items:
        table.add_row(key, action, desc)

    console.print(Panel(table, title="[bold bright_white]  Main Menu  [/]", border_style="bright_blue", expand=False))


def display_events_table(events: list[Event], title: str = "Events"):
    """Render events as a rich table with color-coded sources and urgency."""
    if not events:
        console.print(Panel("[yellow]No events found.[/yellow]", border_style="yellow"))
        return

    table = Table(
        title=f"[bold bright_white]{title}[/] [dim]({len(events)} events)[/]",
        box=box.ROUNDED,
        border_style="bright_blue",
        show_lines=True,
        expand=True,
        title_justify="left",
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Source", width=11, justify="center")
    table.add_column("Title", min_width=25, max_width=45, no_wrap=False)
    table.add_column("Dates", min_width=14, no_wrap=False)
    table.add_column("Location", min_width=12, max_width=25, no_wrap=False)
    table.add_column("Prize", min_width=8, max_width=18, no_wrap=False)
    table.add_column("Organizer", min_width=10, max_width=22, no_wrap=False)

    for idx, ev in enumerate(events, 1):
        src_color = SOURCE_COLORS.get(ev.source, "white")
        source_text = Text(ev.source.upper(), style=f"bold {src_color}")

        date_str = format_date_range(ev)
        days = days_until(ev.start_date or ev.registration_deadline)
        left = days_until(ev.end_date)
        if days is not None and days < 0 and left is not None and left >= 0:
            date_text = Text(date_str, style="bright_cyan")
            date_text.append(f"\n(ongoing, {left}d left)", style="dim italic")
        else:
            date_text = Text(date_str, style=urgency_style(days))
            if days is not None and days >= 0:
                date_text.append(f"\n({days}d away)", style="dim italic")
            elif days is not None and days < 0:
                date_text.append("\n(passed)", style="dim italic")

        loc = format_location(ev)

        prize = ev.prize if (ev.prize and ev.prize != "N/A") else "—"
        prize_style = "bold bright_green" if prize != "—" else "dim"

        organizer = ev.organizer or "—"

        table.add_row(
            str(idx),
            source_text,
            f"[bold]{ev.title}[/bold]",
            date_text,
            loc,
            Text(prize, style=prize_style),
            organizer,
        )

    console.print(table)
    console.print()


def display_event_detail(ev: Event, idx: int):
    """Show full details of a single event in a panel."""
    src_color = SOURCE_COLORS.get(ev.source, "white")
    days = days_until(ev.start_date or ev.registration_deadline)
    urgency = ""
    if days is not None:
        left = days_until(ev.end_date)
        if days < 0 and left is not None and left >= 0:
            urgency = "  [bright_cyan]Ongoing - " + str(left) + " day(s) left[/]"
        elif days < 0:
            urgency = "  [dim strike](Event has passed)[/]"
        elif days == 0:
            urgency = "  [bold bright_red]🔥 TODAY![/]"
        elif days <= 3:
            urgency = f"  [bold bright_red]⚡ {days} day(s) away![/]"
        elif days <= 7:
            urgency = f"  [yellow]📅 {days} days away[/]"
        else:
            urgency = f"  [bright_green]{days} days away[/]"

    lines = [
        f"[bold bright_white]{ev.title}[/]{urgency}",
        "",
        f"  [bold]Source:[/]     [{src_color}]{ev.source.upper()}[/]",
        f"  [bold]URL:[/]        [link={ev.url}]{ev.url}[/link]",
        f"  [bold]Dates:[/]      {format_date_range(ev)}",
        f"  [bold]Location:[/]   {format_location(ev)}",
        f"  [bold]Prize:[/]      {ev.prize or '—'}",
        f"  [bold]Organizer:[/]  {ev.organizer or '—'}",
    ]
    if ev.description:
        # Truncate very long descriptions
        desc = ev.description[:300] + ("…" if len(ev.description) > 300 else "")
        lines.append(f"  [bold]Description:[/] {desc}")

    if ev.created_at:
        lines.append(f"\n  [dim]First tracked: {ev.created_at}[/]")

    content = "\n".join(lines)
    console.print(Panel(content, title=f"[bold]Event #{idx}[/]", border_style="bright_blue", expand=True, padding=(1, 2)))


# ─── Actions ────────────────────────────────────────────────────────────────

def action_browse(show_all: bool = False):
    """Browse all upcoming events with the ability to inspect details."""
    conn = get_connection()
    events = db.get_events(conn, only_new=False, show_all=show_all)

    label = "All Events (including past)" if show_all else "Upcoming Events"
    display_events_table(events, title=label)

    if not events:
        return

    console.print("[dim]Enter an event number for details, 'a' to show all (including past), or press Enter to go back.[/]")
    while True:
        choice = Prompt.ask("[bright_cyan]Event #[/]", default="")
        if choice.strip().lower() == "a" and not show_all:
            clear_screen()
            show_header()
            action_browse(show_all=True)
            return
        if not choice.strip():
            return
        try:
            num = int(choice)
            if 1 <= num <= len(events):
                display_event_detail(events[num - 1], num)
            else:
                console.print("[red]Invalid number.[/red]")
        except ValueError:
            console.print("[red]Please enter a valid number.[/red]")


def action_fetch():
    """Fetch events from all scrapers and show results."""
    conn = get_connection()
    scrapers = get_available_scrapers()

    if not scrapers:
        console.print(Panel("[yellow]No scrapers available.[/yellow]", border_style="yellow"))
        return

    def report(name, kept, fetched, error):
        src_color = SOURCE_COLORS.get(name, "white")
        if error:
            console.print(f"  [red]✘ {name.upper()}[/]  →  Error: {error}")
        else:
            console.print(f"  [{src_color}]✔ {name.upper()}[/]  →  kept {kept} of {fetched} events")

    console.print()
    with console.status("[bold bright_cyan]Fetching events from all sources...[/]", spinner="dots"):
        run_id, results = run_fetch(conn, scrapers, on_result=report)
    total = sum(kept for _, kept, _, _ in results)

    console.print()
    console.print(
        Panel(
            f"[bold bright_green]Fetch complete![/]\n"
            f"Run #{run_id}  •  {total} event(s) stored/updated",
            border_style="bright_green",
        )
    )


def action_new_events():
    """Show events first seen in the latest fetch run."""
    conn = get_connection()
    events = db.get_events(conn, only_new=True, show_all=True)
    display_events_table(events, title="🆕 Newly Discovered Events")

    if events:
        console.print("[dim]Enter an event number for details, or press Enter to go back.[/]")
        while True:
            choice = Prompt.ask("[bright_cyan]Event #[/]", default="")
            if not choice.strip():
                return
            try:
                num = int(choice)
                if 1 <= num <= len(events):
                    display_event_detail(events[num - 1], num)
                else:
                    console.print("[red]Invalid number.[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number.[/red]")


def action_dashboard():
    """Show a quick stats overview."""
    conn = get_connection()
    all_events = db.get_events(conn, show_all=True)
    upcoming = db.get_events(conn, show_all=False)
    new_events = db.get_events(conn, only_new=True, show_all=True)

    # Count by source
    source_counts: dict[str, int] = {}
    for ev in all_events:
        source_counts[ev.source] = source_counts.get(ev.source, 0) + 1

    # Events this week
    this_week = []
    for ev in upcoming:
        d = days_until(ev.start_date or ev.registration_deadline)
        if d is not None and 0 <= d <= 7:
            this_week.append(ev)

    # Build stat cards
    cards = [
        Panel(
            f"[bold bright_white]{len(all_events)}[/]\n[dim]Total Events[/]",
            border_style="bright_blue", width=20, padding=(1, 2),
        ),
        Panel(
            f"[bold bright_green]{len(upcoming)}[/]\n[dim]Upcoming[/]",
            border_style="bright_green", width=20, padding=(1, 2),
        ),
        Panel(
            f"[bold bright_yellow]{len(this_week)}[/]\n[dim]This Week[/]",
            border_style="bright_yellow", width=20, padding=(1, 2),
        ),
        Panel(
            f"[bold bright_magenta]{len(new_events)}[/]\n[dim]New (Last Fetch)[/]",
            border_style="bright_magenta", width=20, padding=(1, 2),
        ),
    ]

    console.print()
    console.print(Columns(cards, equal=True, expand=True))
    console.print()

    # Source breakdown
    if source_counts:
        src_table = Table(
            title="[bold]Events by Source[/]", box=box.SIMPLE_HEAVY,
            border_style="bright_blue", expand=False,
        )
        src_table.add_column("Source", style="bold")
        src_table.add_column("Count", justify="right")
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            color = SOURCE_COLORS.get(src, "white")
            src_table.add_row(f"[{color}]{src.upper()}[/]", str(count))
        console.print(Align.center(src_table))
        console.print()

    # Happening soon
    if this_week:
        console.print("[bold bright_yellow]📅 Happening This Week:[/]")
        for ev in this_week:
            d = days_until(ev.start_date or ev.registration_deadline)
            label = "TODAY" if d == 0 else f"in {d}d"
            console.print(f"  [bright_yellow]•[/] {ev.title} [dim]({label})[/]")
        console.print()


def action_add_manual():
    """Interactively add a manual event."""
    console.print(Panel("[bold]Add a Manual Event[/]", border_style="bright_magenta"))

    title = Prompt.ask("[bold]Title[/]")
    url = Prompt.ask("[bold]URL[/]")
    dates = Prompt.ask("[bold]Dates[/] [dim](e.g. 2026-11-01 to 2026-11-03)[/]", default="")
    location = Prompt.ask("[bold]Location[/]", default="Online")
    organizer = Prompt.ask("[bold]Organizer[/]", default="")
    event_type = Prompt.ask("[bold]Type[/]", choices=list(VALID_EVENT_TYPES), default="other")
    mode = Prompt.ask(f"[bold]Mode[/] [dim]({' / '.join(VALID_MODES)}, blank = from location)[/]",
                      choices=["", *VALID_MODES], default="", show_choices=False)
    tags = Prompt.ask("[bold]Tags[/] [dim](comma-separated, see taxonomy.yaml)[/]", default="")

    yaml_path = Path("manual_events.yaml")
    try:
        entry = make_manual_entry(title, url, dates, location, organizer, event_type, mode, tags)
    except ValueError as exc:
        console.print(Panel(f"[bold red]Not saved:[/] {exc}", border_style="red"))
        return
    updated = save_manual_entry(entry, yaml_path)

    action = "Updated" if updated else "Added"
    console.print(
        Panel(
            f"[bold bright_green]{action}:[/] {title.strip()}\n[dim]{yaml_path}[/]",
            border_style="bright_green",
        )
    )


def action_search():
    """Search events by keyword in title, organizer, location, or description."""
    keyword = Prompt.ask("[bold bright_cyan]Search keyword[/]")
    if not keyword.strip():
        return

    conn = get_connection()
    all_events = db.get_events(conn, show_all=True)
    kw = keyword.strip().lower()

    matches = [
        ev for ev in all_events
        if kw in (ev.title or "").lower()
        or kw in (ev.organizer or "").lower()
        or kw in (ev.location or "").lower()
        or kw in (ev.description or "").lower()
        or kw in (ev.source or "").lower()
    ]

    display_events_table(matches, title=f"🔍 Search Results for \"{keyword.strip()}\"")

    if matches:
        console.print("[dim]Enter an event number for details, or press Enter to go back.[/]")
        while True:
            choice = Prompt.ask("[bright_cyan]Event #[/]", default="")
            if not choice.strip():
                return
            try:
                num = int(choice)
                if 1 <= num <= len(matches):
                    display_event_detail(matches[num - 1], num)
                else:
                    console.print("[red]Invalid number.[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number.[/red]")


# ─── Main Loop ──────────────────────────────────────────────────────────────

def main():
    try:
        while True:
            clear_screen()
            show_header()
            show_menu()

            choice = Prompt.ask("\n[bold bright_cyan]Choose an option[/]", default="0")

            if choice == "1":
                clear_screen()
                show_header()
                action_browse()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "2":
                clear_screen()
                show_header()
                action_fetch()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "3":
                clear_screen()
                show_header()
                action_new_events()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "4":
                clear_screen()
                show_header()
                action_dashboard()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "5":
                clear_screen()
                show_header()
                action_add_manual()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "6":
                clear_screen()
                show_header()
                action_search()
                Prompt.ask("\n[dim]Press Enter to continue…[/]", default="")

            elif choice == "0":
                clear_screen()
                console.print(
                    Panel(
                        "[bold bright_cyan]👋 Goodbye! Happy hacking![/]",
                        border_style="bright_blue",
                    )
                )
                break
            else:
                console.print("[red]Invalid option. Try again.[/red]")
                time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted. Bye![/dim]")
        sys.exit(0)


if __name__ == "__main__":
    main()
