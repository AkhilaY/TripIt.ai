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

from .models import ExtractionResult, Job, JobStatus, Place, Reel, ReelMetadata, Trip, TripDetail

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
    "places": [("opening_hours", "TEXT"), ("hours_checked_at", "TEXT"), ("photos", "TEXT"), ("photos_checked_at", "TEXT")],
}

PLACE_COLUMNS = (
    "trip_id", "reel_id", "name", "category", "summary", "recommended_items", "price_hint", "tips",
    "user_notes", "confidence", "visited", "neighborhood", "address", "city", "country", "latitude",
    "longitude", "maps_url", "resolved_name", "day_number", "day_order", "time_of_day", "day_note",
    "opening_hours", "hours_checked_at", "photos", "photos_checked_at",
)
TRIP_COLUMNS = ("name", "city", "country", "start_date", "day_count", "day_titles", "plan_notes", "planned_by")
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

    def create_trip(self, name: str, city: str, country: str) -> Trip:
        trip_id = new_id()
        self._exec(
            "INSERT INTO trips (id, name, city, country, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, name, city, country, now().isoformat()),
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
        return [self._trip(r, by_trip.get(r["id"], [])) for r in rows]

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        rows = self._rows("SELECT * FROM trips WHERE id = ?", (trip_id,))
        if not rows:
            return None
        stats = self._rows(
            "SELECT trip_id, category, COUNT(*) AS n, SUM(latitude IS NOT NULL) AS mapped "
            "FROM places WHERE trip_id = ? GROUP BY category",
            (trip_id,),
        )
        return self._trip(rows[0], stats)

    def get_trip_detail(self, trip_id: str) -> Optional[TripDetail]:
        trip = self.get_trip(trip_id)
        if trip is None:
            return None
        return TripDetail(**trip.model_dump(), places=self.list_places(trip_id), reels=self.list_reels(trip_id))

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

    @staticmethod
    def _trip(row: sqlite3.Row, stats: list[sqlite3.Row]) -> Trip:
        return Trip(
            id=row["id"],
            name=row["name"],
            city=row["city"],
            country=row["country"],
            created_at=row["created_at"],
            start_date=row["start_date"],
            day_count=row["day_count"],
            day_titles=json.loads(row["day_titles"]),
            plan_notes=row["plan_notes"],
            planned_by=row["planned_by"],
            place_count=sum(s["n"] for s in stats),
            mapped_count=sum(s["mapped"] or 0 for s in stats),
            categories=sorted({s["category"] for s in stats}),
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
        return self.get_place(place_id)

    def get_place(self, place_id: str) -> Optional[Place]:
        rows = self._rows("SELECT * FROM places WHERE id = ?", (place_id,))
        return self._place(rows[0]) if rows else None

    def list_places(self, trip_id: Optional[str] = None) -> list[Place]:
        if trip_id:
            rows = self._rows("SELECT * FROM places WHERE trip_id = ? ORDER BY created_at, rowid", (trip_id,))
        else:
            rows = self._rows("SELECT * FROM places ORDER BY created_at, rowid")
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
