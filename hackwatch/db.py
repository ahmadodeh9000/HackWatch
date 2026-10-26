import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional
from hackwatch.models import DEFAULT_EVENT_TYPE, Event
from hackwatch.filters import is_in_jordan, is_relevant

DEFAULT_DB_PATH = Path("hackwatch.db")


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fetch_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                organizer TEXT,
                prize TEXT,
                registration_deadline TEXT,
                start_date TEXT,
                end_date TEXT,
                location TEXT,
                country TEXT,
                is_online INTEGER DEFAULT 0,
                mode TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                scope TEXT,
                description TEXT,
                type TEXT NOT NULL DEFAULT 'other',
                first_seen_run_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (first_seen_run_id) REFERENCES fetch_runs(id)
            );
        """)
        migrate(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Bring databases created by older versions up to the current schema."""
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    if "type" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN type TEXT NOT NULL DEFAULT 'other';")
    conn.execute("UPDATE events SET type = 'competition' WHERE type = 'contest';")
    if "mode" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN mode TEXT;")
    if "tags" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';")
    if "scope" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN scope TEXT;")
    # Same defaults as the scrapers, except Eventbrite: old databases may hold
    # online Eventbrite events from anywhere, so those go by country.
    conn.execute("UPDATE events SET scope = CASE WHEN source = 'devpost' THEN 'worldwide' "
                 "WHEN source IN ('gdg', 'josa', 'manual') OR country = 'JO' THEN 'jordan' "
                 "ELSE 'worldwide' END WHERE scope IS NULL;")
    conn.execute("UPDATE events SET mode = CASE is_online WHEN 1 THEN 'online' ELSE 'in-person' END "
                 "WHERE mode IS NULL;")


def create_fetch_run(conn: sqlite3.Connection) -> int:
    with conn:
        cursor = conn.execute("INSERT INTO fetch_runs (created_at) VALUES (CURRENT_TIMESTAMP);")
        return cursor.lastrowid


def get_latest_fetch_run_id(conn: sqlite3.Connection) -> Optional[int]:
    cursor = conn.execute("SELECT MAX(id) FROM fetch_runs;")
    row = cursor.fetchone()
    return row[0] if row and row[0] is not None else None


def upsert_event(conn: sqlite3.Connection, event: Event, run_id: Optional[int] = None) -> bool:
    if not is_relevant(event):
        return False
    with conn:
        conn.execute("""
            INSERT INTO events (
                id, title, url, source, organizer, prize,
                registration_deadline, start_date, end_date,
                location, country, is_online, mode, tags, scope, description, type, first_seen_run_id,
                created_at, updated_at
            ) VALUES (
                :id, :title, :url, :source, :organizer, :prize,
                :registration_deadline, :start_date, :end_date,
                :location, :country, :is_online, :mode, :tags, :scope, :description, :type, :first_seen_run_id,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                source = excluded.source,
                organizer = excluded.organizer,
                prize = excluded.prize,
                registration_deadline = excluded.registration_deadline,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                location = excluded.location,
                country = excluded.country,
                is_online = excluded.is_online,
                mode = excluded.mode,
                tags = excluded.tags,
                scope = excluded.scope,
                description = excluded.description,
                type = excluded.type,
                updated_at = CURRENT_TIMESTAMP;
        """, {
            "id": event.id,
            "title": event.title,
            "url": event.url,
            "source": event.source,
            "organizer": event.organizer,
            "prize": event.prize,
            "registration_deadline": event.registration_deadline,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "location": event.location,
            "country": event.country,
            "is_online": 1 if event.is_online else 0,
            "mode": event.mode,
            "tags": json.dumps(event.tags),
            "scope": event.scope or ("jordan" if is_in_jordan(event) else "worldwide"),
            "description": event.description,
            "type": event.type or DEFAULT_EVENT_TYPE,
            "first_seen_run_id": run_id
        })
    return True


def get_events(
    conn: sqlite3.Connection,
    only_new: bool = False,
    show_all: bool = False,
    country: Optional[str] = None,
    include_online: bool = True,
    event_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mode: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[Event]:
    """Query events; tags matches events that have *all* the given tags."""
    query = "SELECT * FROM events WHERE 1=1"
    params = {}

    if only_new:
        latest_run_id = get_latest_fetch_run_id(conn)
        if latest_run_id is None:
            return []
        query += " AND first_seen_run_id = :latest_run_id"
        params["latest_run_id"] = latest_run_id

    if not show_all:
        today_str = date.today().isoformat()
        # Hide past events: keep if end_date >= today, or start_date >= today, or deadline >= today, or dates are null
        query += """
            AND (
                (end_date IS NOT NULL AND end_date >= :today)
                OR (end_date IS NULL AND start_date IS NOT NULL AND start_date >= :today)
                OR (end_date IS NULL AND start_date IS NULL AND registration_deadline IS NOT NULL AND registration_deadline >= :today)
                OR (end_date IS NULL AND start_date IS NULL AND registration_deadline IS NULL)
            )
        """
        params["today"] = today_str

    if country:
        query += " AND (country = :country" + (" OR is_online = 1)" if include_online else ")")
        params["country"] = country.upper()

    if event_type:
        query += " AND type = :event_type"
        params["event_type"] = event_type.lower()

    for i, tag in enumerate(tags or []):
        query += f" AND EXISTS (SELECT 1 FROM json_each(events.tags) WHERE value = :tag{i})"
        params[f"tag{i}"] = tag

    if mode:
        query += " AND mode = :mode"
        params["mode"] = mode

    if scope:
        query += " AND scope = :scope"
        params["scope"] = scope

    query += " ORDER BY COALESCE(start_date, registration_deadline, created_at) ASC"

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    events = []
    for row in rows:
        events.append(Event(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            source=row["source"],
            organizer=row["organizer"],
            prize=row["prize"],
            registration_deadline=row["registration_deadline"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            location=row["location"],
            country=row["country"],
            is_online=bool(row["is_online"]),
            mode=row["mode"],
            tags=json.loads(row["tags"] or "[]"),
            scope=row["scope"],
            description=row["description"],
            type=row["type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            first_seen_run_id=row["first_seen_run_id"]
        ))
    return events
