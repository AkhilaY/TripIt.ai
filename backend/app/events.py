"""What's on during a trip: concerts, theatre, sport and more near where you're staying, matched to your taste.

Events come from the Ticketmaster Discovery API (https://developer.ticketmaster.com). TripIt shows them with a
link to Ticketmaster, where tickets are bought; it never sells or holds tickets. Coverage is strongest in North
America and parts of Europe, so some destinations return little or nothing.
"""

import hashlib
import json
import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from .concierge import profile_text
from .config import Settings
from .db import Database, normalize
from .geocode import clean_website
from .library import Library
from .llm import ClaudeError, ClaudeService
from .models import EventItem, EventNotes, TasteProfile, TripDetail, TripEvents

log = logging.getLogger(__name__)

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
FRESH_HOURS = 12
MAX_EVENTS = 40
EXPLAIN = 8  # events Claude writes a line for
DEFAULT_DAYS = 4

SEGMENT_CATEGORY = {"music": "music", "arts & theatre": "arts", "sports": "sports", "film": "arts"}
# Which kinds of event each interest on the taste profile points to.
INTEREST_CATEGORY = {
    "live music": "music", "nightlife": "music", "theatre & comedy": "arts", "art & museums": "arts",
    "design & architecture": "arts", "sports": "sports",
}
CATEGORY_LABEL = {"music": "live music", "arts": "theatre and the arts", "sports": "sport"}


def geohash(lat: float, lon: float, precision: int = 9) -> str:
    """The Discovery API takes a point as a geohash."""
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    bits, bit, even, out = 0, 0, True, []
    while len(out) < precision:
        rng, value = (lon_range, lon) if even else (lat_range, lat)
        mid = (rng[0] + rng[1]) / 2
        if value >= mid:
            bits = (bits << 1) | 1
            rng[0] = mid
        else:
            bits <<= 1
            rng[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            out.append(BASE32[bits])
            bits, bit = 0, 0
    return "".join(out)


def parse_event(raw: dict) -> Optional[EventItem]:
    """One Discovery API event, or None when it's cancelled, off sale or missing what the app needs."""
    try:
        status = ((raw.get("dates") or {}).get("status") or {}).get("code") or ""
        if status in ("cancelled", "canceled", "offsale"):
            return None
        start = (raw.get("dates") or {}).get("start") or {}
        local_date = start.get("localDate")
        if not raw.get("id") or not raw.get("name") or not local_date or start.get("dateTBA"):
            return None
        local_time = None if start.get("timeTBA") else (start.get("localTime") or "")[:5]
        url = clean_website(raw.get("url"))
        if not url:
            return None
        venue = next(iter(((raw.get("_embedded") or {}).get("venues")) or []), {}) or {}
        location = venue.get("location") or {}
        cls = next(iter(raw.get("classifications") or []), {}) or {}
        segment = ((cls.get("segment") or {}).get("name") or "").lower()
        genre = (cls.get("genre") or {}).get("name")
        genre = genre if genre and genre.lower() not in ("undefined", "other") else None
        category = "family" if "family" in (raw.get("name") or "").lower() or cls.get("family") else SEGMENT_CATEGORY.get(segment, "other")
        price = next(iter(raw.get("priceRanges") or []), {}) or {}
        images = sorted((i for i in raw.get("images") or [] if i.get("url") and (i.get("width") or 0) <= 1100), key=lambda i: -(i.get("width") or 0))
        try:
            lat, lon = float(location.get("latitude")), float(location.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
        return EventItem(
            id=str(raw["id"])[:40], name=" ".join(raw["name"].split())[:150], url=url,
            image=clean_website(images[0]["url"]) if images else None,
            start_at=f"{local_date}T{local_time}" if local_time and re.fullmatch(r"\d\d:\d\d", local_time) else local_date,
            status={"onsale": "onsale", "postponed": "postponed", "rescheduled": "rescheduled"}.get(status, "unknown"),
            venue=(venue.get("name") or None) and venue["name"][:120],
            address=", ".join(p for p in ((venue.get("address") or {}).get("line1"), (venue.get("city") or {}).get("name")) if p) or None,
            latitude=lat, longitude=lon, category=category, genre=genre[:60] if genre else None,
            price_min=price.get("min"), price_max=price.get("max"), currency=price.get("currency"),
        )
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


class Ticketmaster:
    URL = "https://app.ticketmaster.com/discovery/v2/events.json"

    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None):
        self.key = settings.ticketmaster_api_key
        self.radius = settings.events_radius_km
        self.client = client or httpx.AsyncClient(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    async def search(self, lat: float, lon: float, start: date, end: date, size: int = 100) -> Optional[list[EventItem]]:
        """Events near a point between two dates, most relevant first; None when the service couldn't be reached."""
        params = {
            "apikey": self.key, "geoPoint": geohash(lat, lon), "radius": str(self.radius), "unit": "km",
            "startDateTime": f"{start.isoformat()}T00:00:00Z", "endDateTime": f"{end.isoformat()}T23:59:59Z",
            "size": str(size), "sort": "relevance,desc", "includeTBA": "no", "includeTBD": "no", "locale": "*",
        }
        try:
            response = await self.client.get(self.URL, params=params)
            response.raise_for_status()
            raw = ((response.json().get("_embedded") or {}).get("events")) or []
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Ticketmaster search failed: %s", type(e).__name__)
            return None
        seen: set[tuple[str, str]] = set()
        out = []
        for item in raw:
            event = parse_event(item)
            key = (normalize(event.name), event.start_at[:10]) if event else None
            if event and key not in seen:  # the same show listed twice for one day
                seen.add(key)
                out.append(event)
        return out


def wanted_categories(profile: TasteProfile) -> set[str]:
    return {INTEREST_CATEGORY[i.lower()] for i in profile.interests if i.lower() in INTEREST_CATEGORY}


def rank(events: list[EventItem], profile: TasteProfile) -> list[EventItem]:
    """Taste matches first, then the order Ticketmaster gave (most relevant first). With no event-related
    interests on the profile, music and the arts count as matches, the broadest default."""
    wanted = wanted_categories(profile) or {"music", "arts"}
    scored = []
    for position, event in enumerate(events):
        event.match = event.category in wanted
        scored.append((-(3 if event.match else 0) + position / 10, event))
    return [e for _, e in sorted(scored, key=lambda x: x[0])]


class EventsService:
    def __init__(self, db: Database, claude: Optional[ClaudeService], ticketmaster: Ticketmaster, library: Library):
        self.db = db
        self.claude = claude
        self.tm = ticketmaster
        self.library = library
        self._lock = threading.RLock()

    def _signature(self, trip: TripDetail, center: tuple[float, float], days: int, profile: TasteProfile) -> str:
        blob = json.dumps([trip.start_date.isoformat() if trip.start_date else None, days, round(center[0], 1), round(center[1], 1),
                           sorted(profile.interests), self.tm.radius])
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def _stored(self, trip_id: str) -> Optional[TripEvents]:
        row = self.db.get_trip_events(trip_id)
        if row is None:
            return None
        data = json.loads(row["data"])
        return TripEvents(status="ok", events=data.get("events", []), fetched_at=row["fetched_at"], curated_by=data.get("curated_by"))

    async def get(self, trip: TripDetail, profile: TasteProfile, refresh: bool = False) -> TripEvents:
        if not self.tm.enabled:
            return TripEvents(status="disabled")
        if not trip.start_date:
            return TripEvents(status="no_dates")
        center = self.library.trip_center(trip.id)
        if center is None:
            return TripEvents(status="no_location")
        days = max(1, min(trip.day_count or DEFAULT_DAYS, 21))
        signature = self._signature(trip, center, days, profile)
        row = self.db.get_trip_events(trip.id)
        if row and not refresh and row["signature"] == signature:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
            if age < timedelta(hours=FRESH_HOURS):
                return self._stored(trip.id)

        end = trip.start_date + timedelta(days=days - 1)
        found = await self.tm.search(center[0], center[1], trip.start_date, end)
        if found is None:  # the service is down: keep showing what we had
            return self._stored(trip.id) or TripEvents(status="error")
        events = []
        for event in rank(found, profile):  # the search is dated, but make sure nothing outside the trip slips in
            index = (date.fromisoformat(event.start_at[:10]) - trip.start_date).days + 1
            if 1 <= index <= days:
                event.day = index
                events.append(event)
        events = events[:MAX_EVENTS]
        curated = await self._explain(trip, profile, events)
        with self._lock:
            self.db.save_trip_events(trip.id, {"events": [e.model_dump() for e in events], "curated_by": curated}, signature)
        return self._stored(trip.id)

    async def _explain(self, trip: TripDetail, profile: TasteProfile, events: list[EventItem]) -> Optional[str]:
        """A line on why each of the best matches suits this traveller."""
        top = events[:EXPLAIN]
        if not top:
            return None
        wanted = wanted_categories(profile)
        if self.claude is not None:
            context = {
                "taste": profile_text(profile) or None, "city": trip.city,
                "events": [{k: v for k, v in {"id": e.id, "name": e.name, "type": e.category, "genre": e.genre, "date": e.start_at,
                                              "venue": e.venue, "fits_their_interests": e.match}.items() if v is not None} for e in top],
            }
            try:
                notes: EventNotes = await self.claude.explain_events({k: v for k, v in context.items() if v})
                by_id = {n.id: " ".join(n.why.split())[:160] for n in notes.notes}
                for e in top:
                    e.why = by_id.get(e.id)
                return "claude"
            except ClaudeError as err:
                log.warning("Claude event notes failed, using plain ones: %s", err)
        for e in top:
            if e.match and e.category in CATEGORY_LABEL and (e.category in wanted):
                e.why = f"You like {CATEGORY_LABEL[e.category]}" + (f" · {e.genre}" if e.genre else "")
        return "offline"

    async def add_to_trip(self, trip: TripDetail, event_id: str):
        """Saves an event as a stop: its venue on the map, its start time, and its day when the trip has dates."""
        stored = self._stored(trip.id)
        event = next((e for e in (stored.events if stored else []) if e.id == event_id), None)
        if event is None:
            return None, False
        existing = self.library.db.find_saved(event.name, trip.city)
        if existing:
            self.library.db.add_to_trip(trip.id, existing.id)
            return self.library.db.get_place(existing.id, trip.id), False
        day_part, _, time_part = event.start_at.partition("T")
        place = self.library.db.add_place(
            name=event.name, category="event",
            summary=" · ".join(p for p in (event.genre, event.venue) if p), event_date=date.fromisoformat(day_part), venue=event.venue, city=trip.city, country=trip.country,
            address=event.address, latitude=event.latitude, longitude=event.longitude, website=event.url,
            start_time=time_part or None,
        )
        self.library.db.add_to_trip(trip.id, place.id)
        if event.day:
            self.library.move_to(self.library.db.get_place(place.id, trip.id), event.day, None)
        return self.library.db.get_place(place.id, trip.id), True
