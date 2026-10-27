import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

from hackwatch.dedup import deduplicate
from hackwatch.filters import is_in_jordan, is_relevant
from hackwatch.models import DEFAULT_EVENT_TYPE, Event
from hackwatch.urls import normalize_url

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
                sources TEXT NOT NULL DEFAULT '[]',
                urls TEXT NOT NULL DEFAULT '[]',
                stale INTEGER NOT NULL DEFAULT 0,
                stale_since TEXT,
                first_seen_run_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (first_seen_run_id) REFERENCES fetch_runs(id)
            );
        """)
        migrate(conn)


def _create_observations(conn: sqlite3.Connection) -> None:
    """One row per (source, page): what each source listed, before merging duplicates.

    `events` is rebuilt from these (see rebuild_events), so removing a source's
    stale rows and re-merging is all that's needed after a fetch.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            source TEXT NOT NULL,
            url_key TEXT NOT NULL,
            data TEXT NOT NULL,
            first_seen_run_id INTEGER,
            last_seen_run_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source, url_key)
        );
    """)


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
    for col in ("sources", "urls"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} TEXT NOT NULL DEFAULT '[]';")
    if "stale" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN stale INTEGER NOT NULL DEFAULT 0;")
    if "stale_since" not in existing_cols:
        conn.execute("ALTER TABLE events ADD COLUMN stale_since TEXT;")

    had_observations = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'observations'").fetchone()
    _create_observations(conn)
    if not had_observations:
        # Databases from before dedup: each existing row becomes its source's observation.
        for row in conn.execute("SELECT * FROM events").fetchall():
            ev = _row_to_event(row)
            write_observation(conn, ev, row["first_seen_run_id"], row["created_at"])
        rebuild_events(conn)


def create_fetch_run(conn: sqlite3.Connection) -> int:
    with conn:
        cursor = conn.execute("INSERT INTO fetch_runs (created_at) VALUES (CURRENT_TIMESTAMP);")
        return cursor.lastrowid


def get_latest_fetch_run_id(conn: sqlite3.Connection) -> Optional[int]:
    cursor = conn.execute("SELECT MAX(id) FROM fetch_runs;")
    row = cursor.fetchone()
    return row[0] if row and row[0] is not None else None


STORED_FIELDS = ("title", "url", "source", "organizer", "prize", "registration_deadline",
                 "start_date", "end_date", "location", "country", "mode", "description",
                 "type", "tags", "scope", "stale", "stale_since", "host_key")


def _prepare(event: Event) -> Event:
    """Final defaults before storing: scope from location, type 'other'."""
    if event.scope is None:
        event.scope = "jordan" if is_in_jordan(event) else "worldwide"
    if event.type is None:
        event.type = DEFAULT_EVENT_TYPE
    return event


def write_observation(conn, event: Event, run_id: Optional[int], created_at: Optional[str] = None) -> None:
    data = json.dumps({f: getattr(event, f) for f in STORED_FIELDS}, ensure_ascii=False)
    conn.execute("""
        INSERT INTO observations (source, url_key, data, first_seen_run_id, last_seen_run_id,
                                  created_at, updated_at)
        VALUES (:source, :key, :data, :run, :run, COALESCE(:created, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
        ON CONFLICT(source, url_key) DO UPDATE SET
            data = excluded.data,
            last_seen_run_id = COALESCE(excluded.last_seen_run_id, observations.last_seen_run_id),
            updated_at = CURRENT_TIMESTAMP;
    """, {"source": event.source, "key": normalize_url(event.url), "data": data,
          "run": run_id, "created": created_at})


def count_observations(conn: sqlite3.Connection, source: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM observations WHERE source = ?", (source,)).fetchone()[0]


def replace_source_events(conn: sqlite3.Connection, source: str, events: List[Event],
                          run_id: Optional[int] = None, require_tech: bool = False) -> Tuple[int, int]:
    """Store what `source` listed this run and forget what it no longer lists.

    Only call this for a source that fetched successfully. Returns (kept, removed);
    events failing filters.is_relevant are not kept. Call rebuild_events afterwards.
    """
    keys = set()
    with conn:
        for event in events:
            if is_relevant(event, require_tech):
                write_observation(conn, _prepare(event), run_id)
                keys.add(normalize_url(event.url))
        stale = [row["url_key"] for row in conn.execute(
            "SELECT url_key FROM observations WHERE source = ?", (source,)) if row["url_key"] not in keys]
        conn.executemany("DELETE FROM observations WHERE source = ? AND url_key = ?",
                         [(source, key) for key in stale])
    return len(keys), len(stale)


def rebuild_events(conn: sqlite3.Connection) -> int:
    """Recreate `events` by merging duplicate observations (see hackwatch/dedup.py)."""
    observed = []
    for row in conn.execute("SELECT * FROM observations").fetchall():
        data = json.loads(row["data"])
        observed.append(Event(**data, first_seen_run_id=row["first_seen_run_id"],
                              created_at=row["created_at"], updated_at=row["updated_at"]))
    merged = deduplicate(observed)
    with conn:
        conn.execute("DELETE FROM events")
        for ev in merged:
            conn.execute("""
                INSERT INTO events (
                    id, title, url, source, organizer, prize, registration_deadline, start_date,
                    end_date, location, country, is_online, mode, tags, scope, description, type,
                    sources, urls, stale, stale_since, first_seen_run_id, created_at, updated_at
                ) VALUES (
                    :id, :title, :url, :source, :organizer, :prize, :registration_deadline, :start_date,
                    :end_date, :location, :country, :is_online, :mode, :tags, :scope, :description, :type,
                    :sources, :urls, :stale, :stale_since, :first_seen_run_id, :created_at, :updated_at
                )
            """, {
                **{f: getattr(ev, f) for f in STORED_FIELDS},
                # Stable across sources: the same page always gets the same id.
                "id": hashlib.sha256(normalize_url(ev.url).encode("utf-8")).hexdigest()[:16],
                "is_online": 1 if ev.is_online else 0,
                "tags": json.dumps(ev.tags),
                "sources": json.dumps(ev.sources),
                "urls": json.dumps(ev.urls),
                "stale": 1 if ev.stale else 0,
                "first_seen_run_id": ev.first_seen_run_id,
                "created_at": ev.created_at,
                "updated_at": ev.updated_at,
            })
    return len(merged)


def upsert_event(conn: sqlite3.Connection, event: Event, run_id: Optional[int] = None,
                 require_tech: bool = False) -> bool:
    """Add or update one listing (without removing anything) and re-merge. Returns False if filtered out."""
    if not is_relevant(event, require_tech):
        return False
    with conn:
        write_observation(conn, _prepare(event), run_id)
    rebuild_events(conn)
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

    return [_row_to_event(row) for row in conn.execute(query, params).fetchall()]


def _row_to_event(row: sqlite3.Row) -> Event:
    keys = row.keys()
    return Event(
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
        sources=json.loads(row["sources"]) if "sources" in keys else [],
        urls=json.loads(row["urls"]) if "urls" in keys else [],
        stale=bool(row["stale"]) if "stale" in keys else False,
        stale_since=row["stale_since"] if "stale_since" in keys else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        first_seen_run_id=row["first_seen_run_id"],
    )
