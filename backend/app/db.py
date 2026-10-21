"""SQLite storage for trips, places, saved reels and import jobs.

One file, no server to run. On Fly.io/Render put DATABASE_PATH on a persistent volume.
"""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .models import Booking, ExtractionResult, Job, JobStatus, Place, Reel, ReelMetadata, Trip, TripDetail

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
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
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
    ],
    "trips": [("share_token", "TEXT"), ("kind", "TEXT NOT NULL DEFAULT 'trip'")],
}

PLACE_COLUMNS = (
    "trip_id", "reel_id", "name", "category", "summary", "recommended_items", "price_hint", "tips",
    "user_notes", "confidence", "visited", "neighborhood", "address", "city", "country", "latitude",
    "longitude", "maps_url", "resolved_name", "day_number", "day_order", "time_of_day", "day_note",
    "opening_hours", "hours_checked_at", "photos", "photos_checked_at", "must_do", "start_time",
    "rating", "rating_count", "rating_checked_at", "website", "phone", "contact_checked_at",
    "reserve_url", "reserve_provider", "reserve_checked_at", "booking_kind", "booking_need", "booking_note", "booking_checked_at",
)
BOOKING_COLUMNS = (
    "kind", "title", "start_at", "end_at", "origin", "destination", "address", "confirmation", "party_size",
    "notes", "place_id", "source",
)
TRIP_COLUMNS = ("name", "city", "country", "start_date", "day_count", "day_titles", "plan_notes", "planned_by", "share_token", "kind")
# Places plus the reels that mention them.
PLACE_SELECT = ("SELECT p.*, (SELECT group_concat(m.reel_id) FROM place_mentions m WHERE m.place_id = p.id) AS mention_reels "
                "FROM places p")
JSON_COLUMNS = {"recommended_items", "day_titles", "warnings", "opening_hours", "photos"}


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
        # Places saved before mentions were tracked count their first reel.
        self._conn.execute(
            "INSERT OR IGNORE INTO place_mentions (place_id, reel_id) "
            "SELECT id, reel_id FROM places WHERE reel_id IS NOT NULL AND reel_id IN (SELECT id FROM reels)"
        )

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
        self._exec(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            [_encode(k, v) for k, v in fields.items()] + [row_id],
        )

    # ---------- Trips ----------

    def create_trip(self, name: str, city: str, country: str, kind: str = "trip") -> Trip:
        trip_id = new_id()
        self._exec(
            "INSERT INTO trips (id, name, city, country, created_at, kind) VALUES (?, ?, ?, ?, ?, ?)",
            (trip_id, name, city, country, now().isoformat(), kind),
        )
        return self.get_trip(trip_id)

    def list_trips(self) -> list[Trip]:
        rows = self._rows("SELECT * FROM trips ORDER BY created_at DESC")
        stats = self._rows(
            "SELECT trip_id, category, COUNT(*) AS n, SUM(latitude IS NOT NULL) AS mapped "
            "FROM places GROUP BY trip_id, category"
        )
        by_trip: dict[str, list[sqlite3.Row]] = {}
        for s in stats:
            by_trip.setdefault(s["trip_id"], []).append(s)
        covers = self._covers()
        return [self._trip(r, by_trip.get(r["id"], []), covers.get(r["id"])) for r in rows]

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        rows = self._rows("SELECT * FROM trips WHERE id = ?", (trip_id,))
        if not rows:
            return None
        stats = self._rows(
            "SELECT trip_id, category, COUNT(*) AS n, SUM(latitude IS NOT NULL) AS mapped "
            "FROM places WHERE trip_id = ? GROUP BY category",
            (trip_id,),
        )
        return self._trip(rows[0], stats, self._covers(trip_id).get(trip_id))

    def get_trip_detail(self, trip_id: str) -> Optional[TripDetail]:
        trip = self.get_trip(trip_id)
        if trip is None:
            return None
        return TripDetail(**trip.model_dump(), places=self.list_places(trip_id), reels=self.list_reels(trip_id),
                          bookings=self.list_bookings(trip_id))

    def find_trip_by_city(self, city: str) -> Optional[Trip]:
        key = normalize(city)
        for row in self._rows("SELECT id, city FROM trips"):
            if normalize(row["city"]) == key:
                return self.get_trip(row["id"])
        return None

    def update_trip(self, trip_id: str, **changes: Any) -> None:
        self._update("trips", trip_id, TRIP_COLUMNS, changes)

    def delete_trip(self, trip_id: str) -> None:
        self._exec("DELETE FROM trips WHERE id = ?", (trip_id,))

    def trip_by_share_token(self, token: str) -> Optional[TripDetail]:
        rows = self._rows("SELECT id FROM trips WHERE share_token = ?", (token,)) if token else []
        return self.get_trip_detail(rows[0]["id"]) if rows else None

    def _covers(self, trip_id: Optional[str] = None) -> dict[str, dict]:
        """One cover photo per trip: the first saved place with a photo, preferring real
        photos over reel frames (those often carry caption text)."""
        sql = "SELECT id, trip_id, photos FROM places WHERE photos IS NOT NULL AND photos != '[]'"
        args: tuple = ()
        if trip_id:
            sql += " AND trip_id = ?"
            args = (trip_id,)
        best: dict[str, tuple[int, dict]] = {}
        for row in self._rows(sql + " ORDER BY created_at", args):
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
        )

    # ---------- Places ----------

    def add_place(self, **fields: Any) -> Place:
        place_id = new_id()
        fields = {k: v for k, v in fields.items() if k in PLACE_COLUMNS}
        columns = ["id", "created_at", *fields]
        values = [place_id, now().isoformat(), *(_encode(k, v) for k, v in fields.items())]
        self._exec(
            f"INSERT INTO places ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        if fields.get("reel_id"):
            self.add_mention(place_id, fields["reel_id"])
        return self.get_place(place_id)

    def add_mention(self, place_id: str, reel_id: str) -> None:
        self._exec("INSERT OR IGNORE INTO place_mentions (place_id, reel_id) VALUES (?, ?)", (place_id, reel_id))

    def get_place(self, place_id: str) -> Optional[Place]:
        rows = self._rows(f"{PLACE_SELECT} WHERE p.id = ?", (place_id,))
        return self._place(rows[0]) if rows else None

    def list_places(self, trip_id: Optional[str] = None) -> list[Place]:
        if trip_id:
            rows = self._rows(f"{PLACE_SELECT} WHERE p.trip_id = ? ORDER BY p.created_at, p.rowid", (trip_id,))
        else:
            rows = self._rows(f"{PLACE_SELECT} ORDER BY p.created_at, p.rowid")
        return [self._place(r) for r in rows]

    def update_place(self, place_id: str, **changes: Any) -> None:
        self._update("places", place_id, PLACE_COLUMNS, changes)

    def delete_place(self, place_id: str) -> None:
        self._exec("DELETE FROM places WHERE id = ?", (place_id,))

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
        return Place(**data)

    # ---------- Reels ----------

    def add_reel(self, metadata: ReelMetadata, title: str, summary: str) -> Reel:
        reel_id = new_id()
        self._exec(
            "INSERT INTO reels (id, url, platform, title, summary, caption, creator, thumbnail_url, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (reel_id, metadata.url, metadata.platform, title, summary, metadata.caption, metadata.uploader,
             metadata.thumbnail_url, now().isoformat()),
        )
        return self.get_reel(reel_id)

    def get_reel(self, reel_id: str) -> Optional[Reel]:
        rows = self._rows(
            "SELECT r.*, (SELECT COUNT(*) FROM places p WHERE p.reel_id = r.id) AS place_count "
            "FROM reels r WHERE r.id = ?",
            (reel_id,),
        )
        return Reel(**dict(rows[0])) if rows else None

    def list_reels(self, trip_id: Optional[str] = None) -> list[Reel]:
        sql = ("SELECT r.*, (SELECT COUNT(*) FROM places p WHERE p.reel_id = r.id) AS place_count "
               "FROM reels r")
        params: tuple = ()
        if trip_id:
            sql += " WHERE r.trip_id = ? OR r.id IN (SELECT reel_id FROM places WHERE trip_id = ?)"
            params = (trip_id, trip_id)
        rows = self._rows(sql + " ORDER BY r.imported_at DESC", params)
        return [Reel(**dict(r)) for r in rows]

    def set_reel_trip(self, reel_id: str, trip_id: Optional[str]) -> None:
        self._exec("UPDATE reels SET trip_id = ? WHERE id = ?", (trip_id, reel_id))

    # ---------- Settings, edits, briefings ----------

    def get_setting(self, key: str) -> Optional[Any]:
        rows = self._rows("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else None

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value, default=str)))

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

    def save_edits(self, trip_id: str, data: list[dict], curated_by: str, signature: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO trip_edits (trip_id, data, curated_by, signature, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, json.dumps(data), curated_by, signature, now().isoformat()),
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

    def save_push_subscription(self, endpoint: str, keys: dict, origin: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, keys, origin, created_at) VALUES (?, ?, ?, ?)",
            (endpoint, json.dumps(keys), origin, now().isoformat()),
        )

    def push_subscriptions(self) -> list[dict]:
        return [
            {"endpoint": r["endpoint"], "keys": json.loads(r["keys"]), "origin": r["origin"]}
            for r in self._rows("SELECT * FROM push_subscriptions")
        ]

    def delete_push_subscription(self, endpoint: str) -> None:
        self._exec("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    # ---------- Jobs ----------

    def create_job(self, url: str, shared_text: Optional[str]) -> Job:
        job_id = uuid.uuid4().hex
        ts = now().isoformat()
        self._exec(
            "INSERT INTO jobs (id, url, shared_text, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, url, shared_text, JobStatus.queued.value, ts, ts),
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Optional[Job]:
        rows = self._rows("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._job(rows[0]) if rows else None

    def job_shared_text(self, job_id: str) -> Optional[str]:
        rows = self._rows("SELECT shared_text FROM jobs WHERE id = ?", (job_id,))
        return rows[0]["shared_text"] if rows else None

    def list_jobs(self, limit: int = 50) -> list[Job]:
        rows = self._rows("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._job(r) for r in rows]

    def reusable_job(self, url: str) -> Optional[Job]:
        """A job for this URL that's still running, or finished with its places still saved."""
        rows = self._rows(
            "SELECT * FROM jobs WHERE url = ? AND status != ? ORDER BY created_at DESC LIMIT 1",
            (url, JobStatus.failed.value),
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
