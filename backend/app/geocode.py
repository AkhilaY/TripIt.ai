"""Finding coordinates for places Claude extracted.

- Google Places (Text Search) when GOOGLE_MAPS_API_KEY is set: best match quality for restaurants and
  shops, and gives a direct Google Maps link. Has a monthly free allowance.
- Otherwise OpenStreetMap's Nominatim: free, no key, good for landmarks and well-known spots, weaker for
  small businesses. Limited to 1 request/second by its usage policy.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

from .config import Settings
from .hours import from_google, parse_osm
from .models import OpeningHours

log = logging.getLogger(__name__)


@dataclass
class GeoMatch:
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    maps_url: Optional[str] = None
    hours: Optional[OpeningHours] = None


class Geocoder(Protocol):
    async def locate(
        self, name: str, neighborhood: Optional[str], city: str, country: str, query: Optional[str] = None
    ) -> Optional[GeoMatch]: ...


class NoGeocoder:
    async def locate(self, name, neighborhood, city, country, query=None) -> Optional[GeoMatch]:
        return None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


class GooglePlacesGeocoder:
    URL = "https://places.googleapis.com/v1/places:searchText"
    # Opening hours put this request in Google's "Enterprise" Text Search tier (smaller free allowance).
    FIELDS = "places.displayName,places.formattedAddress,places.location,places.googleMapsUri,places.regularOpeningHours"

    def __init__(self, api_key: str, client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=15)

    async def locate(self, name, neighborhood, city, country, query=None) -> Optional[GeoMatch]:
        text = query or ", ".join(p for p in (name, neighborhood, city, country) if p)
        try:
            response = await self.client.post(
                self.URL,
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": self.FIELDS},
                json={"textQuery": text, "pageSize": 1},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Google Places lookup failed for %r: %s", text, e)
            return None
        places = response.json().get("places") or []
        if not places:
            return None
        p = places[0]
        loc = p.get("location") or {}
        if "latitude" not in loc:
            return None
        return GeoMatch(
            name=(p.get("displayName") or {}).get("text") or name,
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            address=p.get("formattedAddress"),
            maps_url=p.get("googleMapsUri"),
            hours=from_google(p.get("regularOpeningHours")),
        )


class NominatimGeocoder:
    URL = "https://nominatim.openstreetmap.org/search"
    MIN_INTERVAL = 1.1  # seconds; Nominatim allows at most 1 request per second

    def __init__(self, contact_email: str = "", client: Optional[httpx.AsyncClient] = None):
        agent = "TripIt/1.0 (personal trip planner" + (f"; {contact_email}" if contact_email else "") + ")"
        self.client = client or httpx.AsyncClient(timeout=15, headers={"User-Agent": agent})
        self.email = contact_email
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._cities: dict[str, Optional[tuple[float, float]]] = {}

    async def _search(self, params: dict) -> list[dict]:
        params = {"format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 3, **params}
        if self.email:
            params["email"] = self.email
        async with self._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self.client.get(self.URL, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Nominatim lookup failed for %r: %s", params.get("q"), e)
                return []
            finally:
                self._last = time.monotonic()

    async def _city_center(self, city: str, country: str) -> Optional[tuple[float, float]]:
        key = f"{city}|{country}".lower()
        if key not in self._cities:
            results = await self._search({"q": ", ".join(p for p in (city, country) if p), "limit": 1})
            self._cities[key] = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
        return self._cities[key]

    async def locate(self, name, neighborhood, city, country, query=None) -> Optional[GeoMatch]:
        center = await self._city_center(city, country) if city else None
        extra: dict = {}
        if center:
            lat, lon = center
            # ~35 km box around the city center keeps same-named places elsewhere out.
            extra = {"viewbox": f"{lon - 0.4},{lat + 0.3},{lon + 0.4},{lat - 0.3}", "bounded": 1}

        queries = [query] if query else [
            ", ".join(p for p in (name, neighborhood, city) if p),
            f"{name}, {city}" if city else name,
        ]
        for q in dict.fromkeys(queries):  # de-dupe, keep order
            for result in await self._search({"q": q, **extra}):
                lat, lon = float(result["lat"]), float(result["lon"])
                if center and _km(lat, lon, *center) > 60:
                    continue
                address = result.get("address") or {}
                street = " ".join(p for p in (address.get("house_number"), address.get("road")) if p)
                area = address.get("suburb") or address.get("neighbourhood") or address.get("city")
                return GeoMatch(
                    name=result.get("name") or name,
                    latitude=lat,
                    longitude=lon,
                    address=", ".join(p for p in (street, area) if p) or result.get("display_name"),
                    hours=parse_osm((result.get("extratags") or {}).get("opening_hours")),
                )
        return None


def make_geocoder(settings: Settings) -> Geocoder:
    choice = settings.geocoder
    if choice == "none":
        return NoGeocoder()
    if choice == "google" or (choice == "auto" and settings.google_maps_api_key):
        if not settings.google_maps_api_key:
            raise RuntimeError("GEOCODER=google needs GOOGLE_MAPS_API_KEY")
        return GooglePlacesGeocoder(settings.google_maps_api_key)
    return NominatimGeocoder(settings.nominatim_email)
