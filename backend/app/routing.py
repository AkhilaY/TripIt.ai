"""Travel times by walking, transit, driving and cycling.

With GOOGLE_MAPS_API_KEY (and the Routes API enabled on it), times come from Google's Routes API and
are cached in SQLite. Otherwise, or if Google refuses, they're estimated from straight-line distance
and marked `estimated` so the app can say so. There is no free worldwide transit routing, so transit
estimates are only given for longer hops and are rough.
"""

import asyncio
import logging
import math
from typing import Optional

import httpx

from .config import Settings
from .db import Database, cache_get, cache_put
from .models import Leg, Place, TravelMode, TravelTime

log = logging.getLogger(__name__)

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
GOOGLE_MODE = {TravelMode.walk: "WALK", TravelMode.transit: "TRANSIT", TravelMode.drive: "DRIVE", TravelMode.bike: "BICYCLE"}
CACHE_TTL = {TravelMode.walk: 30 * 86400, TravelMode.bike: 30 * 86400, TravelMode.drive: 3 * 86400, TravelMode.transit: 3 * 86400}

Point = tuple[float, float]


def straight_line_m(a: Point, b: Point) -> float:
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(h))


def estimate(a: Point, b: Point, mode: TravelMode) -> Optional[TravelTime]:
    """Rough city travel time from straight-line distance (streets add ~30–40%)."""
    d = straight_line_m(a, b)
    if mode == TravelMode.walk:
        dist = d * 1.3
        secs = dist / (4.8 / 3.6)
    elif mode == TravelMode.bike:
        dist = d * 1.3
        secs = dist / (14 / 3.6)
    elif mode == TravelMode.drive:
        dist = d * 1.4
        secs = dist / (24 / 3.6) + 120  # city traffic plus parking
    else:  # transit: only worth estimating for longer hops
        if d < 1200:
            return None
        dist = d * 1.3
        secs = dist / (20 / 3.6) + 8 * 60  # walking to/from stops and waiting
    return TravelTime(duration_s=int(round(secs)), distance_m=int(round(dist)), estimated=True)


class Router:
    def __init__(self, db: Database, settings: Settings, client: Optional[httpx.AsyncClient] = None):
        self.db = db
        self.key = settings.google_maps_api_key if settings.routing != "estimate" else ""
        self.client = client or httpx.AsyncClient(timeout=20)
        self.google_off_reason: Optional[str] = None

    @property
    def provider(self) -> str:
        return "google" if self.key and not self.google_off_reason else "estimate"

    async def _google_matrix(self, origins: list[Point], destinations: list[Point], mode: TravelMode) -> Optional[dict]:
        """Returns {(origin_index, destination_index): TravelTime | None}, or None if Google can't be used."""
        if self.provider != "google":
            return None
        waypoint = lambda p: {"waypoint": {"location": {"latLng": {"latitude": p[0], "longitude": p[1]}}}}
        body = {"origins": [waypoint(o) for o in origins], "destinations": [waypoint(d) for d in destinations],
                "travelMode": GOOGLE_MODE[mode]}
        try:
            response = await self.client.post(
                MATRIX_URL,
                headers={"X-Goog-Api-Key": self.key,
                         "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,condition"},
                json=body,
            )
        except httpx.HTTPError as e:
            log.warning("Routes API request failed: %s", e)
            return None
        if response.status_code in (400, 401, 403):
            # Usually "Routes API has not been used in project … or it is disabled". Stop trying until restart.
            self.google_off_reason = response.text[:300]
            log.warning("Routes API refused the key, using estimates: %s", self.google_off_reason)
            return None
        if response.status_code != 200:
            log.warning("Routes API error %s: %s", response.status_code, response.text[:200])
            return None
        out: dict = {}
        for element in response.json():
            key = (element.get("originIndex", 0), element.get("destinationIndex", 0))  # zero values are omitted
            if element.get("condition") == "ROUTE_EXISTS" and "duration" in element:
                out[key] = TravelTime(duration_s=int(float(element["duration"].rstrip("s"))),
                                      distance_m=int(element.get("distanceMeters", 0)))
            else:
                out[key] = None
        return out

    async def _pair(self, a: Point, b: Point, mode: TravelMode) -> Optional[TravelTime]:
        cache_key = f"{mode.value}:{a[0]:.5f},{a[1]:.5f}:{b[0]:.5f},{b[1]:.5f}"
        if self.provider == "google":
            cached = cache_get(self.db, cache_key, CACHE_TTL[mode])
            if cached is not None:
                if cached["duration_s"] is None:
                    return None
                return TravelTime(duration_s=cached["duration_s"], distance_m=cached["distance_m"])
            result = await self._google_matrix([a], [b], mode)
            if result is not None:
                time = result.get((0, 0))
                cache_put(self.db, cache_key, time.duration_s if time else None, time.distance_m if time else None, "google")
                return time
        return estimate(a, b, mode)

    async def _all_modes(self, a: Point, b: Point) -> dict[TravelMode, Optional[TravelTime]]:
        modes = list(TravelMode)
        results = await asyncio.gather(*(self._pair(a, b, m) for m in modes))
        return dict(zip(modes, results))

    async def day_legs(self, stops: list[Place]) -> list[Leg]:
        """Legs between consecutive stops that are on the map."""
        located = [p for p in stops if p.latitude is not None and p.longitude is not None]
        pairs = list(zip(located, located[1:]))
        times = await asyncio.gather(*(self._all_modes((a.latitude, a.longitude), (b.latitude, b.longitude)) for a, b in pairs))
        return [Leg(from_place_id=a.id, to_place_id=b.id, times=t) for (a, b), t in zip(pairs, times)]

    async def from_point(self, origin: Point, places: list[Place]) -> list[Leg]:
        """Travel times from `origin` (e.g. your location) to each place, one Google request per mode."""
        located = [p for p in places if p.latitude is not None and p.longitude is not None]
        if not located:
            return []
        points = [(p.latitude, p.longitude) for p in located]
        per_mode: dict[TravelMode, dict[int, Optional[TravelTime]]] = {}
        for mode in TravelMode:
            matrix = await self._google_matrix([origin], points, mode)
            if matrix is not None:
                per_mode[mode] = {j: matrix.get((0, j)) for j in range(len(points))}
            else:
                per_mode[mode] = {j: estimate(origin, pt, mode) for j, pt in enumerate(points)}
        return [Leg(from_place_id=None, to_place_id=p.id, times={m: per_mode[m][j] for m in TravelMode})
                for j, p in enumerate(located)]
