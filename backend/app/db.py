"""SQLite storage for trips, places, saved reels and import jobs.

One file, no server to run. On Fly.io/Render put DATABASE_PATH on a persistent volume.
"""

import json
import logging
import re as _re
import sqlite3
import threading
import uuid
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .models import Booking, BookingListItem, ExtractionResult, Folder, Job, JobStatus, Place, Reel, ReelMetadata, Trip, TripDetail

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    start_date TEXT,
    day_count INTEGER NOT NULL DEFAULT 0,
    day_titles TEXT NOT NULL DEFAULT '[]',
    plan_notes TEXT,
    planned_by TEXT
);

CREATE TABLE IF NOT EXISTS reels (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    caption TEXT,
    creator TEXT,
    thumbnail_url TEXT,
    trip_id TEXT REFERENCES trips(id) ON DELETE SET NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY,
    trip_id TEXT,  -- unused since saved places moved out of trips (see trip_places)
    reel_id TEXT REFERENCES reels(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    summary TEXT NOT NULL DEFAULT '',
    recommended_items TEXT NOT NULL DEFAULT '[]',
    price_hint TEXT,
    tips TEXT,
    user_notes TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT 'high',
    visited INTEGER NOT NULL DEFAULT 0,
    neighborhood TEXT,
    address TEXT,
    city TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    maps_url TEXT,
    resolved_name TEXT,
    day_number INTEGER,
    day_order INTEGER NOT NULL DEFAULT 0,
    time_of_day TEXT,
    day_note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS places_trip ON places(trip_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    shared_text TEXT,
    status TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reel TEXT,
    result TEXT,
    warnings TEXT NOT NULL DEFAULT '[]',
    trip_id TEXT,
    reel_id TEXT,
    added_places INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_url ON jobs(url);

CREATE TABLE IF NOT EXISTS place_mentions (
    place_id TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    reel_id TEXT NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    PRIMARY KEY (place_id, reel_id)
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    keys TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invites (
    code_hash TEXT PRIMARY KEY,
    hint TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TEXT NOT NULL,
    used_by TEXT,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    message TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- What AI (and Google Maps) calls cost, per UTC day, person ('' for none) and feature.
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    user_id TEXT NOT NULL,
    feature TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    searches INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user_id, feature)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_edits (
    trip_id TEXT PRIMARY KEY REFERENCES trips(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    curated_by TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    origin TEXT,
    destination TEXT,
    address TEXT,
    confirmation TEXT,
    party_size INTEGER,
    notes TEXT,
    place_id TEXT REFERENCES places(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trip_events (
    trip_id TEXT PRIMARY KEY REFERENCES trips(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    signature TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

-- A trip's stops: saved places linked to it, with where they sit in its itinerary. A place can be in
-- any number of trips (and folders); its own details (stars, notes, hours) are shared by all of them.
CREATE TABLE IF NOT EXISTS trip_members (
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'editor',
    joined_at TEXT NOT NULL,
    PRIMARY KEY (trip_id, user_id)
);

CREATE TABLE IF NOT EXISTS trip_places (
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    place_id TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    day_number INTEGER,
    day_order INTEGER NOT NULL DEFAULT 0,
    time_of_day TEXT,
    day_note TEXT,
    start_time TEXT,
    suggested INTEGER NOT NULL DEFAULT 0,
    suggestion_note TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (trip_id, place_id)
);
CREATE INDEX IF NOT EXISTS trip_places_place ON trip_places(place_id);

CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS folder_places (
    folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    place_id TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL,
    PRIMARY KEY (folder_id, place_id)
);
CREATE INDEX IF NOT EXISTS folder_places_place ON folder_places(place_id);

CREATE TABLE IF NOT EXISTS discover_cache (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packing (
    trip_id TEXT PRIMARY KEY REFERENCES trips(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menus (
    place_id TEXT PRIMARY KEY REFERENCES places(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    data TEXT,
    source_kind TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefings (
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    day INTEGER NOT NULL,
    on_date TEXT NOT NULL,
    signature TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (trip_id, day, on_date)
);

CREATE TABLE IF NOT EXISTS route_cache (
    key TEXT PRIMARY KEY,
    duration_s INTEGER,
    distance_m INTEGER,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
"""

# Columns added after the first release; created on existing databases at startup.
MIGRATIONS = {
    "places": [
        ("opening_hours", "TEXT"), ("hours_checked_at", "TEXT"), ("photos", "TEXT"), ("photos_checked_at", "TEXT"),
        ("must_do", "INTEGER NOT NULL DEFAULT 0"), ("start_time", "TEXT"),
        ("rating", "REAL"), ("rating_count", "INTEGER"), ("rating_checked_at", "TEXT"),
        ("website", "TEXT"), ("phone", "TEXT"), ("contact_checked_at", "TEXT"),
        ("reserve_url", "TEXT"), ("reserve_provider", "TEXT"), ("reserve_checked_at", "TEXT"),
        ("booking_kind", "TEXT"), ("booking_need", "TEXT"), ("booking_note", "TEXT"), ("booking_checked_at", "TEXT"),
        ("event_date", "TEXT"), ("event_end_date", "TEXT"), ("venue", "TEXT"),
        ("saved", "INTEGER NOT NULL DEFAULT 1"),  # 0 for a place an AI plan suggested that you haven't kept
        ("user_id", "TEXT"),
    ],
    "trips": [("share_token", "TEXT"), ("kind", "TEXT NOT NULL DEFAULT 'trip'"), ("user_id", "TEXT"), ("stops", "TEXT"),
              ("invite_token", "TEXT")],
    "folders": [("user_id", "TEXT")],
    "users": [("apple_sub", "TEXT"), ("apple_token", "TEXT")],
    "reels": [("user_id", "TEXT")],
    "jobs": [("user_id", "TEXT")],
    "push_subscriptions": [("user_id", "TEXT")],
}

PLACE_COLUMNS = (
    "trip_id", "reel_id", "name", "category", "summary", "recommended_items", "price_hint", "tips",
    "user_notes", "confidence", "visited", "neighborhood", "address", "city", "country", "latitude",
    "longitude", "maps_url", "resolved_name", "day_number", "day_order", "time_of_day", "day_note",
    "opening_hours", "hours_checked_at", "photos", "photos_checked_at", "must_do", "start_time",
    "rating", "rating_count", "rating_checked_at", "website", "phone", "contact_checked_at",
    "reserve_url", "reserve_provider", "reserve_checked_at", "booking_kind", "booking_need", "booking_note", "booking_checked_at",
    "event_date", "event_end_date", "venue", "saved",
)
# Where a place sits in one trip's itinerary; kept per trip in trip_places.
MEMBER_COLUMNS = ("day_number", "day_order", "time_of_day", "day_note", "start_time", "suggested", "suggestion_note")
BOOKING_COLUMNS = (
    "kind", "title", "start_at", "end_at", "origin", "destination", "address", "confirmation", "party_size",
    "notes", "place_id", "source",
)
TRIP_COLUMNS = ("name", "city", "country", "start_date", "day_count", "day_titles", "plan_notes", "planned_by", "share_token", "kind", "stops")
# Places plus the reels that mention them.
# Whose data a request may see. Set by the auth check for each request (and copied into the background tasks it
# starts); every read and write of trips, places, folders, reels, jobs and push subscriptions is limited to it.
# None means no account is in use: the single-user setup from before accounts, tests, and start-up housekeeping.
CURRENT_USER: ContextVar[Optional[str]] = ContextVar("current_user", default=None)
OWNED_TABLES = ("trips", "places", "folders", "reels", "jobs", "push_subscriptions")
# Settings that belong to a person rather than to the server.
USER_SETTINGS = ("taste_profile", "home", "calendar_feed_token", "packing_unused")


def trip_stops(row: sqlite3.Row) -> list[dict]:
    """The trip's route with each stop's days numbered. Without a saved route it's one stop: the trip's city.
    Days past the last stop belong to it, so every day of the trip has a stop."""
    if (row["kind"] or "trip") == "local":
        return []
    keys = row.keys()
    saved = json.loads(row["stops"]) if "stops" in keys and row["stops"] else []
    day_count = row["day_count"] or 0
    if not saved:
        saved = [{"city": row["city"], "country": row["country"] or "", "days": max(day_count, 1)}]
    out, day = [], 1
    for i, s in enumerate(saved):
        days = max(int(s.get("days") or 1), 1)
        if i == len(saved) - 1 and day + days - 1 < day_count:
            days = day_count - day + 1
        out.append({**s, "days": days, "start_day": day, "end_day": day + days - 1})
        day += days
    return out


def _uid() -> Optional[str]:
    return CURRENT_USER.get()


def _mine(alias: str = "") -> tuple[str, tuple]:
    """" AND <alias.>user_id = ?" (and its parameter) when a user is signed in, else nothing."""
    uid = _uid()
    return (f" AND {alias + '.' if alias else ''}user_id = ?", (uid,)) if uid else ("", ())


MEMBER_COUNT = "(SELECT COUNT(*) FROM trip_members WHERE trip_members.trip_id = trips.id) AS member_count"


def _trips_i_can_open(alias: str = "", column: str = "id") -> tuple[str, tuple]:
    """Trips you own or were invited to plan: " AND (<trip id column> is one of them)"."""
    uid = _uid()
    if not uid:
        return "", ()
    col = f"{alias + '.' if alias else ''}{column}"
    return (f" AND ({col} IN (SELECT id FROM trips WHERE user_id = ?) OR {col} IN (SELECT trip_id FROM trip_members WHERE user_id = ?))",
            (uid, uid))


def _places_i_can_open(alias: str = "p") -> tuple[str, tuple]:
    """Your own places, and places on trips you plan with others (someone else may have added them)."""
    uid = _uid()
    if not uid:
        return "", ()
    a = alias + "." if alias else ""
    return (f" AND ({a}user_id = ? OR {a}id IN (SELECT place_id FROM trip_places WHERE trip_id IN "
            "(SELECT id FROM trips WHERE user_id = ?) OR trip_id IN (SELECT trip_id FROM trip_members WHERE user_id = ?)))",
            (uid, uid, uid))


PLACE_SELECT = ("SELECT p.*, (SELECT group_concat(m.reel_id) FROM place_mentions m WHERE m.place_id = p.id) AS mention_reels, "
                "(SELECT group_concat(t.trip_id) FROM trip_places t WHERE t.place_id = p.id) AS trip_list, "
                "(SELECT group_concat(f.folder_id) FROM folder_places f WHERE f.place_id = p.id) AS folder_list "
                "FROM places p")
# The same, as a stop on one trip: its day, order and time come from trip_places.
TRIP_PLACE_SELECT = (PLACE_SELECT[:-len("FROM places p")] + ", tp.trip_id AS m_trip, tp.day_number AS m_day_number, "
                     "tp.day_order AS m_day_order, tp.time_of_day AS m_time_of_day, tp.day_note AS m_day_note, "
                     "tp.start_time AS m_start_time, tp.suggested AS m_suggested, tp.suggestion_note AS m_suggestion_note "
                     "FROM places p JOIN trip_places tp ON tp.place_id = p.id")
JSON_COLUMNS = {"recommended_items", "day_titles", "warnings", "opening_hours", "photos", "stops"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _encode(column: str, value: Any) -> Any:
    if column in JSON_COLUMNS:
        if value is None and column == "opening_hours":
            return None
        return json.dumps(value.model_dump() if hasattr(value, "model_dump") else value)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value"):  # enums
        return value.value
    return value


class Database:
    # Turns a stored photo ref into the URL the app loads; main.py swaps in a signed version.
    photo_url: Callable[[str, int, str], str] = staticmethod(lambda place_id, index, ref: f"/v1/places/{place_id}/photos/{index}")

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        for table, columns in MIGRATIONS.items():
            existing = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, sql_type in columns:
                if name not in existing:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
        # Events saved from What's on before there was an event category.
        if not self._conn.execute("SELECT 1 FROM settings WHERE key = 'migrated_event_category'").fetchone():
            self._conn.execute("UPDATE places SET category = 'event' WHERE website LIKE '%ticketmaster.%' AND category IN ('nightlife', 'activity')")
            self._conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('migrated_event_category', 'true')")
        self._migrate_library()
        # Places saved before mentions were tracked count their first reel.
        self._conn.execute(
            "INSERT OR IGNORE INTO place_mentions (place_id, reel_id) "
            "SELECT id, reel_id FROM places WHERE reel_id IS NOT NULL AND reel_id IN (SELECT id FROM reels)"
        )

    def _migrate_library(self) -> None:
        """Saved places used to belong to exactly one trip, made automatically per city. Now they stand on
        their own: trips you planned keep their places (as links), the rest become folders named after them."""
        if self._conn.execute("SELECT 1 FROM settings WHERE key = 'migrated_library'").fetchone():
            return
        if self._path != ":memory:" and self._conn.execute("SELECT 1 FROM trips").fetchone():
            # A copy from before the move, in case anything needs to be looked up later.
            backup = sqlite3.connect(f"{self._path}.before-library.bak")
            with backup:
                self._conn.backup(backup)
            backup.close()
        info = {r["name"]: r for r in self._conn.execute("PRAGMA table_info(places)")}
        if info["trip_id"]["notnull"]:  # rebuild without the NOT NULL / cascade on trip_id
            sql = self._conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'places'").fetchone()[0]
            new_sql = _re.sub(r"trip_id TEXT NOT NULL REFERENCES trips\(id\) ON DELETE CASCADE", "trip_id TEXT", sql, count=1)
            new_sql = new_sql.replace("CREATE TABLE places", "CREATE TABLE places_new", 1).replace('CREATE TABLE "places"', "CREATE TABLE places_new", 1)
            self._conn.execute("PRAGMA foreign_keys = OFF")
            try:
                self._conn.execute("BEGIN")
                self._conn.execute(new_sql)
                self._conn.execute("INSERT INTO places_new SELECT * FROM places")
                self._conn.execute("DROP TABLE places")
                self._conn.execute("ALTER TABLE places_new RENAME TO places")
                self._conn.execute("CREATE INDEX IF NOT EXISTS places_trip ON places(trip_id)")
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            finally:
                self._conn.execute("PRAGMA foreign_keys = ON")
        stamp = now().isoformat()
        self._conn.execute("BEGIN")
        try:
            self._move_trips_to_library(stamp)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _move_trips_to_library(self, stamp: str) -> None:
        for trip in self._conn.execute("SELECT * FROM trips").fetchall():
            keep = (trip["day_count"] or trip["start_date"] or trip["share_token"]
                    or self._conn.execute("SELECT 1 FROM bookings WHERE trip_id = ?", (trip["id"],)).fetchone()
                    or self._conn.execute("SELECT 1 FROM packing WHERE trip_id = ?", (trip["id"],)).fetchone())
            if keep and (trip["kind"] or "trip") != "local":
                self._conn.execute(
                    "INSERT OR IGNORE INTO trip_places (trip_id, place_id, day_number, day_order, time_of_day, day_note, start_time, added_at) "
                    "SELECT trip_id, id, day_number, day_order, time_of_day, day_note, CASE WHEN category = 'event' THEN NULL ELSE start_time END, created_at "
                    "FROM places WHERE trip_id = ?", (trip["id"],))
                continue
            if self._conn.execute("SELECT 1 FROM places WHERE trip_id = ?", (trip["id"],)).fetchone():
                folder_id = new_id()
                self._conn.execute("INSERT INTO folders (id, name, created_at) VALUES (?, ?, ?)", (folder_id, trip["name"], trip["created_at"] or stamp))
                self._conn.execute("INSERT OR IGNORE INTO folder_places (folder_id, place_id, added_at) SELECT ?, id, created_at FROM places WHERE trip_id = ?",
                                   (folder_id, trip["id"]))
            self._conn.execute("DELETE FROM trips WHERE id = ?", (trip["id"],))
        self._conn.execute("UPDATE places SET trip_id = NULL, day_number = NULL, day_order = 0, time_of_day = NULL, day_note = NULL")
        self._conn.execute("UPDATE places SET start_time = NULL WHERE category != 'event'")
        self._conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('migrated_library', 'true')")

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def _update(self, table: str, row_id: str, allowed: tuple[str, ...], changes: dict[str, Any]) -> None:
        fields = {k: v for k, v in changes.items() if k in allowed}
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        # Trips and their places can be changed by everyone planning the trip; the rest only by their owner.
        scope = {"trips": _trips_i_can_open, "places": lambda: _places_i_can_open("")}.get(table)
        mine, mine_args = scope() if scope else _mine() if table in OWNED_TABLES else ("", ())
        self._exec(
            f"UPDATE {table} SET {assignments} WHERE id = ?{mine}",
            [_encode(k, v) for k, v in fields.items()] + [row_id, *mine_args],
        )

    # ---------- Trips ----------

    def create_trip(self, name: str, city: str, country: str, kind: str = "trip") -> Trip:
        trip_id = new_id()
        self._exec(
            "INSERT INTO trips (id, name, city, country, created_at, kind, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trip_id, name, city, country, now().isoformat(), kind, _uid()),
        )
        return self.get_trip(trip_id)

    def list_trips(self) -> list[Trip]:
        mine, args = _trips_i_can_open()
        rows = self._rows(f"SELECT *, {MEMBER_COUNT} FROM trips WHERE 1{mine} ORDER BY created_at DESC", args)
        stats = self._rows(
            "SELECT tp.trip_id, p.category, COUNT(*) AS n, SUM(p.latitude IS NOT NULL) AS mapped "
            "FROM trip_places tp JOIN places p ON p.id = tp.place_id GROUP BY tp.trip_id, p.category"
        )
        by_trip: dict[str, list[sqlite3.Row]] = {}
        for s in stats:
            by_trip.setdefault(s["trip_id"], []).append(s)
        covers = self._covers()
        return [self._trip(r, by_trip.get(r["id"], []), covers.get(r["id"])) for r in rows]

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        mine, args = _trips_i_can_open()
        rows = self._rows(f"SELECT *, {MEMBER_COUNT} FROM trips WHERE id = ?{mine}", (trip_id, *args))
        if not rows:
            return None
        stats = self._rows(
            "SELECT tp.trip_id, p.category, COUNT(*) AS n, SUM(p.latitude IS NOT NULL) AS mapped "
            "FROM trip_places tp JOIN places p ON p.id = tp.place_id WHERE tp.trip_id = ? GROUP BY p.category",
            (trip_id,),
        )
        return self._trip(rows[0], stats, self._covers(trip_id).get(trip_id))

    def get_trip_detail(self, trip_id: str) -> Optional[TripDetail]:
        trip = self.get_trip(trip_id)
        if trip is None:
            return None
        return TripDetail(**trip.model_dump(), places=self.list_places(trip_id), reels=self.list_reels(trip_id),
                          bookings=self.list_bookings(trip_id))

    # ---------- Planning together ----------

    def trip_owner(self, trip_id: str) -> Optional[str]:
        rows = self._rows("SELECT user_id FROM trips WHERE id = ?", (trip_id,))
        return rows[0]["user_id"] if rows else None

    def trip_by_invite(self, token: str) -> Optional[sqlite3.Row]:
        """The trip an invite link is for, whoever owns it (only the token is checked)."""
        rows = self._rows("SELECT *, (SELECT COUNT(*) FROM trip_members m WHERE m.trip_id = trips.id) AS member_count "
                          "FROM trips WHERE invite_token = ?", (token,)) if token else []
        return rows[0] if rows else None

    def set_invite_token(self, trip_id: str, token: Optional[str]) -> None:
        self._exec("UPDATE trips SET invite_token = ? WHERE id = ?", (token, trip_id))

    def invite_token(self, trip_id: str) -> Optional[str]:
        rows = self._rows("SELECT invite_token FROM trips WHERE id = ?", (trip_id,))
        return rows[0]["invite_token"] if rows else None

    def add_member(self, trip_id: str, user_id: str) -> bool:
        cur = self._exec("INSERT OR IGNORE INTO trip_members (trip_id, user_id, role, joined_at) VALUES (?, ?, 'editor', ?)",
                         (trip_id, user_id, now().isoformat()))
        return cur.rowcount > 0

    def remove_member(self, trip_id: str, user_id: str) -> None:
        self._exec("DELETE FROM trip_members WHERE trip_id = ? AND user_id = ?", (trip_id, user_id))

    def members(self, trip_id: str) -> list[dict]:
        """The owner, then everyone who joined, oldest first."""
        owner = self._rows("SELECT u.id, u.name, u.email FROM trips t JOIN users u ON u.id = t.user_id WHERE t.id = ?", (trip_id,))
        joined = self._rows("SELECT u.id, u.name, u.email FROM trip_members m JOIN users u ON u.id = m.user_id "
                            "WHERE m.trip_id = ? ORDER BY m.joined_at", (trip_id,))
        return [{**dict(r), "role": "owner"} for r in owner] + [{**dict(r), "role": "editor"} for r in joined]

    def find_trip_by_city(self, city: str) -> Optional[Trip]:
        key = normalize(city)
        mine, args = _mine()
        for row in self._rows(f"SELECT id, city FROM trips WHERE 1{mine}", args):
            if normalize(row["city"]) == key:
                return self.get_trip(row["id"])
        return None

    def update_trip(self, trip_id: str, **changes: Any) -> None:
        self._update("trips", trip_id, TRIP_COLUMNS, changes)

    def delete_trip(self, trip_id: str) -> None:
        """Deletes the trip; its places stay saved. Suggestions you never kept go with it."""
        mine, args = _mine()
        self._exec(f"DELETE FROM trips WHERE id = ?{mine}", (trip_id, *args))
        self.prune_unsaved()

    def prune_unsaved(self) -> list[str]:
        rows = self._rows("SELECT id FROM places WHERE saved = 0 AND id NOT IN (SELECT place_id FROM trip_places)")
        for r in rows:
            self._exec("DELETE FROM places WHERE id = ?", (r["id"],))
        return [r["id"] for r in rows]

    def trip_by_share_token(self, token: str) -> Optional[TripDetail]:
        """A shared trip, for anyone with its link (whoever owns it)."""
        rows = self._rows("SELECT id, user_id FROM trips WHERE share_token = ?", (token,)) if token else []
        if not rows:
            return None
        reset = CURRENT_USER.set(rows[0]["user_id"])
        try:
            return self.get_trip_detail(rows[0]["id"])
        finally:
            CURRENT_USER.reset(reset)

    def _covers(self, trip_id: Optional[str] = None) -> dict[str, dict]:
        """One cover photo per trip: the first saved place with a photo, preferring real
        photos over reel frames (those often carry caption text)."""
        sql = ("SELECT p.id, tp.trip_id, p.photos, p.created_at FROM trip_places tp JOIN places p ON p.id = tp.place_id "
               "WHERE p.photos IS NOT NULL AND p.photos != '[]'")
        args: tuple = ()
        if trip_id:
            sql += " AND tp.trip_id = ?"
            args = (trip_id,)
        best: dict[str, tuple[int, dict]] = {}
        for row in self._rows(sql + " ORDER BY p.created_at", args):
            refs = list(enumerate(json.loads(row["photos"])))
            i, ref = next(((i, r) for i, r in refs if r["source"] != "reel"), refs[0])
            rank = 1 if ref["source"] == "reel" else 0
            if row["trip_id"] not in best or rank < best[row["trip_id"]][0]:
                best[row["trip_id"]] = (rank, {
                    "source": ref["source"],
                    "url": self.photo_url(row["id"], i, ref["ref"]),
                    "attribution": ref.get("attribution"),
                })
        return {tid: photo for tid, (_, photo) in best.items()}

    @staticmethod
    def _trip(row: sqlite3.Row, stats: list[sqlite3.Row], cover: Optional[dict] = None) -> Trip:
        return Trip(
            id=row["id"],
            name=row["name"],
            city=row["city"],
            country=row["country"],
            kind=row["kind"] or "trip",
            created_at=row["created_at"],
            start_date=row["start_date"],
            day_count=row["day_count"],
            day_titles=json.loads(row["day_titles"]),
            plan_notes=row["plan_notes"],
            planned_by=row["planned_by"],
            place_count=sum(s["n"] for s in stats),
            mapped_count=sum(s["mapped"] or 0 for s in stats),
            categories=sorted({s["category"] for s in stats}),
            cover_photo=cover,
            share_token=row["share_token"],
            stops=trip_stops(row),
            role="editor" if _uid() and row["user_id"] and row["user_id"] != _uid() else "owner",
            member_count=row["member_count"] if "member_count" in row.keys() else 0,
        )

    # ---------- Places ----------

    def add_place(self, **fields: Any) -> Place:
        place_id = new_id()
        fields = {k: v for k, v in fields.items() if k in PLACE_COLUMNS and k != "user_id"}
        columns = ["id", "created_at", "user_id", *fields]
        values = [place_id, now().isoformat(), _uid(), *(_encode(k, v) for k, v in fields.items())]
        self._exec(
            f"INSERT INTO places ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        if fields.get("reel_id"):
            self.add_mention(place_id, fields["reel_id"])
        return self.get_place(place_id)

    def add_mention(self, place_id: str, reel_id: str) -> None:
        self._exec("INSERT OR IGNORE INTO place_mentions (place_id, reel_id) VALUES (?, ?)", (place_id, reel_id))

    def get_place(self, place_id: str, trip_id: Optional[str] = None) -> Optional[Place]:
        """The place itself, or as a stop on a trip (None if it isn't on that trip)."""
        if trip_id:
            mine, args = _trips_i_can_open("tp", "trip_id")
            rows = self._rows(f"{TRIP_PLACE_SELECT} WHERE p.id = ? AND tp.trip_id = ?{mine}", (place_id, trip_id, *args))
        else:
            mine, args = _places_i_can_open("p")
            rows = self._rows(f"{PLACE_SELECT} WHERE p.id = ?{mine}", (place_id, *args))
        return self._place(rows[0]) if rows else None

    def list_places(self, trip_id: Optional[str] = None, saved_only: bool = False) -> list[Place]:
        """A trip's stops, or every place (saved_only: leave out AI suggestions you haven't kept)."""
        if trip_id:
            mine, args = _trips_i_can_open("tp", "trip_id")
            rows = self._rows(f"{TRIP_PLACE_SELECT} WHERE tp.trip_id = ?{mine} ORDER BY tp.added_at, p.created_at, p.rowid", (trip_id, *args))
        else:
            mine, args = _mine("p")  # your Library: only your own places, never a travel partner's
            rows = self._rows(f"{PLACE_SELECT} WHERE 1{' AND p.saved = 1' if saved_only else ''}{mine} ORDER BY p.created_at, p.rowid", args)
        return [self._place(r) for r in rows]

    def find_saved(self, name: str, city: Optional[str] = None) -> Optional[Place]:
        """A saved place with this name (in this city, when given): saving it again shouldn't duplicate it."""
        key = normalize(name)
        mine, args = _mine()
        for row in self._rows(f"SELECT id, name, city FROM places WHERE saved = 1{mine}", args):
            if normalize(row["name"]) == key and (not city or not row["city"] or normalize(row["city"]) == normalize(city)):
                return self.get_place(row["id"])
        return None

    def update_place(self, place_id: str, trip_id: Optional[str] = None, **changes: Any) -> None:
        """Updates a place. Its day, order, time slot and note are per trip, so changing them needs trip_id;
        start_time with trip_id is the stop's exact time on that trip, without it an event's own start."""
        member = {k: v for k, v in changes.items() if k in MEMBER_COLUMNS and (trip_id or k != "start_time")}
        if member and not trip_id:
            raise ValueError(f"{', '.join(member)} belong to a trip; pass trip_id")
        if member:
            assignments = ", ".join(f"{k} = ?" for k in member)
            self._exec(f"UPDATE trip_places SET {assignments} WHERE trip_id = ? AND place_id = ?",
                       [_encode(k, v) for k, v in member.items()] + [trip_id, place_id])
        self._update("places", place_id, PLACE_COLUMNS, {k: v for k, v in changes.items() if k not in member})

    # ---------- Trip stops and folders ----------

    def add_to_trip(self, trip_id: str, place_id: str, suggested: bool = False, note: Optional[str] = None) -> bool:
        cur = self._exec("INSERT OR IGNORE INTO trip_places (trip_id, place_id, suggested, suggestion_note, added_at) VALUES (?, ?, ?, ?, ?)",
                         (trip_id, place_id, int(suggested), note, now().isoformat()))
        return cur.rowcount > 0

    def remove_from_trip(self, trip_id: str, place_id: str) -> None:
        self._exec("DELETE FROM trip_places WHERE trip_id = ? AND place_id = ?", (trip_id, place_id))

    def list_folders(self) -> list[Folder]:
        mine, args = _mine("f")
        rows = self._rows("SELECT f.*, (SELECT COUNT(*) FROM folder_places fp WHERE fp.folder_id = f.id) AS place_count "
                          f"FROM folders f WHERE 1{mine} ORDER BY f.created_at DESC", args)
        covers: dict[str, list[dict]] = {}
        for r in self._rows("SELECT fp.folder_id, p.id, p.photos FROM folder_places fp JOIN places p ON p.id = fp.place_id "
                            "WHERE p.photos IS NOT NULL AND p.photos != '[]' ORDER BY fp.added_at DESC"):
            refs = json.loads(r["photos"])
            if refs and len(covers.setdefault(r["folder_id"], [])) < 4:
                i, ref = next(((i, x) for i, x in enumerate(refs) if x["source"] != "reel"), (0, refs[0]))
                covers[r["folder_id"]].append({"source": ref["source"], "url": self.photo_url(r["id"], i, ref["ref"]), "attribution": ref.get("attribution")})
        return [Folder(id=r["id"], name=r["name"], created_at=r["created_at"], place_count=r["place_count"], covers=covers.get(r["id"], []))
                for r in rows]

    def get_folder(self, folder_id: str) -> Optional[Folder]:
        return next((f for f in self.list_folders() if f.id == folder_id), None)

    def create_folder(self, name: str) -> Folder:
        folder_id = new_id()
        self._exec("INSERT INTO folders (id, name, created_at, user_id) VALUES (?, ?, ?, ?)", (folder_id, name, now().isoformat(), _uid()))
        return self.get_folder(folder_id)

    def rename_folder(self, folder_id: str, name: str) -> None:
        mine, args = _mine()
        self._exec(f"UPDATE folders SET name = ? WHERE id = ?{mine}", (name, folder_id, *args))

    def delete_folder(self, folder_id: str) -> None:
        mine, args = _mine()
        self._exec(f"DELETE FROM folders WHERE id = ?{mine}", (folder_id, *args))

    def add_to_folder(self, folder_id: str, place_id: str) -> None:
        self._exec("INSERT OR IGNORE INTO folder_places (folder_id, place_id, added_at) VALUES (?, ?, ?)", (folder_id, place_id, now().isoformat()))

    def remove_from_folder(self, folder_id: str, place_id: str) -> None:
        self._exec("DELETE FROM folder_places WHERE folder_id = ? AND place_id = ?", (folder_id, place_id))

    def delete_place(self, place_id: str) -> None:
        mine, args = _mine()
        self._exec(f"DELETE FROM places WHERE id = ?{mine}", (place_id, *args))

    def photo_refs(self, place_id: str) -> list[dict]:
        rows = self._rows("SELECT photos FROM places WHERE id = ?", (place_id,))
        return json.loads(rows[0]["photos"]) if rows and rows[0]["photos"] else []

    def _place(self, row: sqlite3.Row) -> Place:
        data = dict(row)
        refs = json.loads(data["photos"]) if data.get("photos") else []
        data["photos"] = [
            {"source": r["source"], "url": self.photo_url(data["id"], i, r["ref"]), "attribution": r.get("attribution")}
            for i, r in enumerate(refs)
        ]
        data["recommended_items"] = json.loads(data["recommended_items"])
        data["visited"] = bool(data["visited"])
        data["must_do"] = bool(data["must_do"])
        mentions = data.pop("mention_reels", None)
        data["reel_ids"] = sorted(mentions.split(","), key=lambda r: r != data["reel_id"]) if mentions else []
        data["mention_count"] = len(data["reel_ids"])
        data["opening_hours"] = json.loads(data["opening_hours"]) if data.get("opening_hours") else None
        data["trip_ids"] = (data.pop("trip_list", None) or "").split(",") if data.get("trip_list") else []
        data.pop("trip_list", None)
        data["folder_ids"] = (data.pop("folder_list", None) or "").split(",") if data.get("folder_list") else []
        data.pop("folder_list", None)
        data["saved"] = bool(data.get("saved", 1))
        event_time = data["start_time"] if data["category"] == "event" else None
        if "m_trip" in data:  # as a stop on a trip
            data.update(trip_id=data.pop("m_trip"), day_number=data.pop("m_day_number"), day_order=data.pop("m_day_order") or 0,
                        time_of_day=data.pop("m_time_of_day"), day_note=data.pop("m_day_note"),
                        start_time=data.pop("m_start_time") or event_time, suggested=bool(data.pop("m_suggested")),
                        suggestion_note=data.pop("m_suggestion_note"))
        else:
            data.update(trip_id=None, day_number=None, day_order=0, time_of_day=None, day_note=None, start_time=event_time)
        return Place(**data)

    # ---------- Reels ----------

    def add_reel(self, metadata: ReelMetadata, title: str, summary: str) -> Reel:
        reel_id = new_id()
        self._exec(
            "INSERT INTO reels (id, url, platform, title, summary, caption, creator, thumbnail_url, imported_at, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (reel_id, metadata.url, metadata.platform, title, summary, metadata.caption, metadata.uploader,
             metadata.thumbnail_url, now().isoformat(), _uid()),
        )
        return self.get_reel(reel_id)

    def get_reel(self, reel_id: str) -> Optional[Reel]:
        rows = self._rows(
            "SELECT r.*, (SELECT COUNT(*) FROM places p WHERE p.reel_id = r.id) AS place_count "
            "FROM reels r WHERE r.id = ?" + _mine("r")[0],
            (reel_id, *_mine("r")[1]),
        )
        return Reel(**dict(rows[0])) if rows else None

    def place_reels(self, place_id: str) -> list[Reel]:
        rows = self._rows("SELECT r.*, (SELECT COUNT(*) FROM place_mentions pm WHERE pm.reel_id = r.id) AS place_count "
                          "FROM reels r JOIN place_mentions m ON m.reel_id = r.id WHERE m.place_id = ? ORDER BY r.imported_at", (place_id,))
        return [Reel(**dict(r)) for r in rows]

    def list_reels(self, trip_id: Optional[str] = None) -> list[Reel]:
        mine, args = _mine("r")
        sql = ("SELECT r.*, (SELECT COUNT(*) FROM places p WHERE p.reel_id = r.id) AS place_count "
               f"FROM reels r WHERE 1{mine}")
        params: tuple = args
        if trip_id:
            sql += " AND (r.trip_id = ? OR r.id IN (SELECT m.reel_id FROM place_mentions m JOIN trip_places tp ON tp.place_id = m.place_id WHERE tp.trip_id = ?))"
            params = (*args, trip_id, trip_id)
        rows = self._rows(sql + " ORDER BY r.imported_at DESC", params)
        return [Reel(**dict(r)) for r in rows]

    def set_reel_trip(self, reel_id: str, trip_id: Optional[str]) -> None:
        self._exec("UPDATE reels SET trip_id = ? WHERE id = ?", (trip_id, reel_id))

    # ---------- Settings, edits, briefings ----------

    @staticmethod
    def _setting_key(key: str) -> str:
        """Personal settings (taste, home city…) are stored per person as "<key>@<user id>"."""
        uid = _uid()
        return f"{key}@{uid}" if uid and key in USER_SETTINGS else key

    def get_setting(self, key: str) -> Optional[Any]:
        rows = self._rows("SELECT value FROM settings WHERE key = ?", (self._setting_key(key),))
        return json.loads(rows[0]["value"]) if rows else None

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (self._setting_key(key), json.dumps(value, default=str)))

    def user_for_setting(self, key: str, value: Any) -> Optional[str]:
        """Whose personal setting has this value (e.g. which person a calendar feed link belongs to); "" for the
        setting from before accounts."""
        for r in self._rows("SELECT key FROM settings WHERE (key = ? OR key LIKE ?) AND value = ?", (key, f"{key}@%", json.dumps(value))):
            return r["key"].split("@", 1)[1] if "@" in r["key"] else ""
        return None

    # ---------- Discover ----------

    def get_discover(self, key: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM discover_cache WHERE key = ?", (key,))
        return rows[0] if rows else None

    def save_discover(self, key: str, data: dict) -> None:
        self._exec("INSERT OR REPLACE INTO discover_cache (key, data, created_at) VALUES (?, ?, ?)", (key, json.dumps(data, default=str), now().isoformat()))
        self._exec("DELETE FROM discover_cache WHERE created_at < ?", ((now() - __import__("datetime").timedelta(days=3)).isoformat(),))

    # ---------- Events ----------

    def get_trip_events(self, trip_id: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM trip_events WHERE trip_id = ?", (trip_id,))
        return rows[0] if rows else None

    def save_trip_events(self, trip_id: str, data: dict, signature: str) -> None:
        self._exec("INSERT OR REPLACE INTO trip_events (trip_id, data, signature, fetched_at) VALUES (?, ?, ?, ?)",
                   (trip_id, json.dumps(data, default=str), signature, now().isoformat()))

    # ---------- Packing ----------

    def get_packing(self, trip_id: str) -> Optional[dict]:
        rows = self._rows("SELECT data FROM packing WHERE trip_id = ?", (trip_id,))
        return json.loads(rows[0]["data"]) if rows else None

    def save_packing(self, trip_id: str, data: dict) -> None:
        self._exec("INSERT OR REPLACE INTO packing (trip_id, data, updated_at) VALUES (?, ?, ?)",
                   (trip_id, json.dumps(data, default=str), now().isoformat()))

    # ---------- Bookings ----------

    def list_bookings(self, trip_id: str) -> list[Booking]:
        rows = self._rows("SELECT * FROM bookings WHERE trip_id = ? ORDER BY COALESCE(start_at, '9999'), created_at, rowid", (trip_id,))
        return [Booking(**dict(r)) for r in rows]

    def list_all_bookings(self) -> list[BookingListItem]:
        mine, args = _trips_i_can_open("t")
        rows = self._rows("SELECT b.*, t.name AS trip_name, t.kind AS trip_kind FROM bookings b JOIN trips t ON t.id = b.trip_id "
                          f"WHERE 1{mine} "
                          "ORDER BY COALESCE(b.start_at, '9999'), b.created_at, b.rowid", args)
        return [BookingListItem(**{**dict(r), "trip_kind": r["trip_kind"] or "trip"}) for r in rows]

    def get_booking(self, booking_id: str) -> Optional[Booking]:
        rows = self._rows("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        return Booking(**dict(rows[0])) if rows else None

    def add_booking(self, trip_id: str, **fields: Any) -> Booking:
        booking_id = new_id()
        fields = {k: v for k, v in fields.items() if k in BOOKING_COLUMNS}
        columns = ["id", "trip_id", "created_at", *fields]
        values = [booking_id, trip_id, now().isoformat(), *fields.values()]
        self._exec(f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", values)
        return self.get_booking(booking_id)

    def update_booking(self, booking_id: str, **changes: Any) -> None:
        self._update("bookings", booking_id, BOOKING_COLUMNS, changes)

    def delete_booking(self, booking_id: str) -> None:
        self._exec("DELETE FROM bookings WHERE id = ?", (booking_id,))

    def delete_menu(self, place_id: str) -> None:
        self._exec("DELETE FROM menus WHERE place_id = ?", (place_id,))

    def get_menu(self, place_id: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM menus WHERE place_id = ?", (place_id,))
        return rows[0] if rows else None

    def save_menu(self, place_id: str, status: str, data: Optional[dict], source_kind: Optional[str], source_url: Optional[str]) -> None:
        self._exec(
            "INSERT OR REPLACE INTO menus (place_id, status, data, source_kind, source_url, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            (place_id, status, json.dumps(data) if data is not None else None, source_kind, source_url, now().isoformat()),
        )

    def get_edits(self, trip_id: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM trip_edits WHERE trip_id = ?", (trip_id,))
        return rows[0] if rows else None

    def save_edits(self, trip_id: str, data: list[dict], curated_by: str, signature: str, created_at: Optional[str] = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO trip_edits (trip_id, data, curated_by, signature, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, json.dumps(data, default=str), curated_by, signature, created_at or now().isoformat()),
        )

    def get_briefing(self, trip_id: str, day: int, on_date: str) -> Optional[sqlite3.Row]:
        rows = self._rows("SELECT * FROM briefings WHERE trip_id = ? AND day = ? AND on_date = ?", (trip_id, day, on_date))
        return rows[0] if rows else None

    def save_briefing(self, trip_id: str, day: int, on_date: str, signature: str, data: dict) -> None:
        self._exec(
            "INSERT OR REPLACE INTO briefings (trip_id, day, on_date, signature, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (trip_id, day, on_date, signature, json.dumps(data, default=str), now().isoformat()),
        )

    # ---------- Push subscriptions ----------

    # ---------- Feedback ----------

    def add_feedback(self, user_id: Optional[str], message: str, context: dict) -> str:
        feedback_id = new_id()
        self._exec("INSERT INTO feedback (id, user_id, message, context, created_at) VALUES (?, ?, ?, ?, ?)",
                   (feedback_id, user_id, message, json.dumps(context), now().isoformat()))
        return feedback_id

    def list_feedback(self, limit: int = 100) -> list[dict]:
        return [{"id": r["id"], "user_id": r["user_id"], "message": r["message"], "context": json.loads(r["context"]),
                 "created_at": r["created_at"]}
                for r in self._rows("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,))]

    # ---------- Usage and costs ----------

    def add_usage(self, day: str, user_id: str, feature: str, calls: int = 1, input_tokens: int = 0, output_tokens: int = 0,
                  cache_read: int = 0, cache_write: int = 0, searches: int = 0, cost: float = 0.0) -> None:
        self._exec(
            "INSERT INTO usage (day, user_id, feature, calls, input_tokens, output_tokens, cache_read, cache_write, searches, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (day, user_id, feature) DO UPDATE SET "
            "calls = calls + excluded.calls, input_tokens = input_tokens + excluded.input_tokens, "
            "output_tokens = output_tokens + excluded.output_tokens, cache_read = cache_read + excluded.cache_read, "
            "cache_write = cache_write + excluded.cache_write, searches = searches + excluded.searches, "
            "cost_usd = cost_usd + excluded.cost_usd",
            (day, user_id, feature, calls, input_tokens, output_tokens, cache_read, cache_write, searches, cost),
        )

    def usage_cost(self, since_day: str, user_id: Optional[str] = None) -> float:
        """AI spend from since_day on (everyone's, or one person's); Google Maps calls aren't included."""
        sql = "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage WHERE day >= ? AND feature NOT LIKE 'google:%'"
        params: tuple = (since_day,)
        if user_id is not None:
            sql, params = sql + " AND user_id = ?", params + (user_id,)
        return self._rows(sql, params)[0]["c"]

    def usage_calls(self, day: str, user_id: str, features: Iterable[str]) -> int:
        features = tuple(features)
        marks = ", ".join("?" * len(features))
        return self._rows(f"SELECT COALESCE(SUM(calls), 0) AS n FROM usage WHERE day = ? AND user_id = ? AND feature IN ({marks})",
                          (day, user_id) + features)[0]["n"]

    def usage_rows(self, since_day: str) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT * FROM usage WHERE day >= ? ORDER BY day", (since_day,))]

    def is_admin(self, user_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM users WHERE id = ? AND is_admin = 1", (user_id,)))

    def user_emails(self) -> dict[str, str]:
        return {r["id"]: r["email"] for r in self._rows("SELECT id, email FROM users")}

    def save_push_subscription(self, endpoint: str, keys: dict, origin: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, keys, origin, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (endpoint, json.dumps(keys), origin, now().isoformat(), _uid()),
        )

    def push_subscriptions(self) -> list[dict]:
        return [
            {"endpoint": r["endpoint"], "keys": json.loads(r["keys"]), "origin": r["origin"]}
            for r in self._rows("SELECT * FROM push_subscriptions WHERE 1" + _mine()[0], _mine()[1])
        ]

    def delete_push_subscription(self, endpoint: str) -> None:
        self._exec("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    # ---------- Jobs ----------

    def create_job(self, url: str, shared_text: Optional[str]) -> Job:
        job_id = uuid.uuid4().hex
        ts = now().isoformat()
        self._exec(
            "INSERT INTO jobs (id, url, shared_text, status, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, url, shared_text, JobStatus.queued.value, ts, ts, _uid()),
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[Job]:
        mine, args = _mine()
        rows = self._rows(f"SELECT * FROM jobs WHERE id = ?{mine}", (job_id, *args))
        return self._job(rows[0]) if rows else None

    def job_shared_text(self, job_id: str) -> Optional[str]:
        rows = self._rows("SELECT shared_text FROM jobs WHERE id = ?", (job_id,))
        return rows[0]["shared_text"] if rows else None

    def list_jobs(self, limit: int = 50) -> list[Job]:
        mine, args = _mine()
        rows = self._rows(f"SELECT * FROM jobs WHERE 1{mine} ORDER BY created_at DESC LIMIT ?", (*args, limit))
        return [self._job(r) for r in rows]

    def reusable_job(self, url: str) -> Optional[Job]:
        """A job for this URL that's still running, or finished with its places still saved."""
        rows = self._rows(
            "SELECT * FROM jobs WHERE url = ? AND status != ?" + _mine()[0] + " ORDER BY created_at DESC LIMIT 1",
            (url, JobStatus.failed.value, *_mine()[1]),
        )
        if not rows:
            return None
        row = rows[0]
        if row["status"] != JobStatus.done.value:
            return self._job(row)
        if row["reel_id"] and self.get_reel(row["reel_id"]):
            return self._job(row)
        return None

    def unfinished_jobs(self) -> list[Job]:
        rows = self._rows(
            "SELECT * FROM jobs WHERE status NOT IN (?, ?) ORDER BY created_at",
            (JobStatus.done.value, JobStatus.failed.value),
        )
        return [self._job(r) for r in rows]

    def update_job(self, job_id: str, **changes: Any) -> None:
        encoded: dict[str, Any] = {}
        for key, value in changes.items():
            if key in ("reel", "result"):
                encoded[key] = value.model_dump_json() if value is not None else None
            elif key == "warnings":
                encoded[key] = json.dumps(value)
            elif key in ("status", "message", "trip_id", "reel_id", "added_places"):
                encoded[key] = _encode(key, value)
        encoded["updated_at"] = now().isoformat()
        assignments = ", ".join(f"{k} = ?" for k in encoded)
        self._exec(f"UPDATE jobs SET {assignments} WHERE id = ?", [*encoded.values(), job_id])

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            url=row["url"],
            status=row["status"],
            message=row["message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            reel=ReelMetadata.model_validate_json(row["reel"]) if row["reel"] else None,
            result=_load_result(row["result"]),
            warnings=json.loads(row["warnings"]),
            trip_id=row["trip_id"],
            reel_id=row["reel_id"],
            user_id=row["user_id"],
            added_places=row["added_places"],
        )


def _load_result(raw: Optional[str]) -> Optional[ExtractionResult]:
    """Parses a stored extraction, filling in fields added since it was saved (e.g. image_labels)."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        for place in data.get("places", []):
            place.setdefault("image_labels", [])
        return ExtractionResult.model_validate(data)
    except (ValueError, TypeError) as e:  # pydantic's ValidationError is a ValueError
        log.warning("Couldn't read a stored extraction result: %s", e)
        return None


# ---------- Route cache ----------


def cache_get(db: "Database", key: str, max_age_s: int) -> Optional[sqlite3.Row]:
    rows = db._rows("SELECT * FROM route_cache WHERE key = ?", (key,))
    if not rows:
        return None
    age = (now() - datetime.fromisoformat(rows[0]["fetched_at"])).total_seconds()
    return rows[0] if age <= max_age_s else None


def cache_put(db: "Database", key: str, duration_s: Optional[int], distance_m: Optional[int], provider: str) -> None:
    db._exec(
        "INSERT OR REPLACE INTO route_cache (key, duration_s, distance_m, provider, fetched_at) VALUES (?, ?, ?, ?, ?)",
        (key, duration_s, distance_m, provider, now().isoformat()),
    )


def normalize(text: str) -> str:
    """'The Joe’s Pizza!' and "joes pizza" compare equal."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    folded = folded.replace("'", "").replace("’", "")
    words = "".join(c if c.isalnum() else " " for c in folded).split()
    return " ".join(w for w in words if w != "the")
