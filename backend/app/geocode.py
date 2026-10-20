"""Finding coordinates for places Claude extracted.

- Google Places (Text Search) when GOOGLE_MAPS_API_KEY is set: best match quality for restaurants and
  shops, and gives a direct Google Maps link. Has a monthly free allowance.
- Otherwise OpenStreetMap's Nominatim: free, no key, good for landmarks and well-known spots, weaker for
  small businesses. Limited to 1 request/second by its usage policy.
"""

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .hours import from_google, parse_osm
from .models import OpeningHours
from .photos import wikidata_image

log = logging.getLogger(__name__)


@dataclass
class GeoMatch:
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    maps_url: Optional[str] = None
    hours: Optional[OpeningHours] = None
    photos: list[dict] = field(default_factory=list)  # {"source", "ref", "attribution"}
    rating: Optional[float] = None  # Google's rating out of 5
    rating_count: Optional[int] = None
    website: Optional[str] = None  # an http(s) address
    phone: Optional[str] = None
    # Filled in by search()/details(), used when adding a place by hand.
    place_id: Optional[str] = None  # "google:<id>" or "osm:N123"
    category: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


def clean_website(value: Optional[str]) -> Optional[str]:
    """Only plain http(s) addresses are kept, so a stored value is always safe to link to."""
    value = (value or "").strip()
    if not value or len(value) > 500 or any(ch.isspace() for ch in value):
        return None
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    return value if parts.scheme in ("http", "https") and parts.netloc and "." in parts.netloc else None


def clean_phone(value: Optional[str]) -> Optional[str]:
    """A phone number as people write it: digits, spaces and + - ( ) . only."""
    value = (value or "").split(";")[0].strip()  # OpenStreetMap sometimes lists several, separated by ;
    if not (5 <= len(value) <= 40) or not re.fullmatch(r"[+\d][\d\s().\-/]*", value) or sum(ch.isdigit() for ch in value) < 5:
        return None
    return value


def osm_website(tags: dict) -> Optional[str]:
    return clean_website(tags.get("website") or tags.get("contact:website") or tags.get("url"))


def osm_phone(tags: dict) -> Optional[str]:
    return clean_phone(tags.get("phone") or tags.get("contact:phone"))


class Geocoder(Protocol):
    async def locate(
        self, name: str, neighborhood: Optional[str], city: str, country: str, query: Optional[str] = None
    ) -> Optional[GeoMatch]: ...

    async def search(self, query: str, near: Optional[tuple[float, float]] = None, limit: int = 5) -> list[GeoMatch]: ...

    async def details(self, place_id: str) -> Optional[GeoMatch]: ...


class NoGeocoder:
    async def locate(self, name, neighborhood, city, country, query=None) -> Optional[GeoMatch]:
        return None

    async def search(self, query, near=None, limit=5) -> list[GeoMatch]:
        return []

    async def details(self, place_id) -> Optional[GeoMatch]:
        return None


# Google place types (https://developers.google.com/maps/documentation/places/web-service/place-types) and
# OpenStreetMap tags, mapped to TripIt categories. First match wins.
GOOGLE_TYPES = [
    ("dessert", ("ice_cream_shop", "dessert_shop", "dessert_restaurant", "confectionery", "donut_shop", "chocolate_shop", "candy_store")),
    ("cafe", ("cafe", "coffee_shop", "bakery", "tea_house", "breakfast_restaurant", "brunch_restaurant")),
    ("nightlife", ("night_club", "karaoke", "comedy_club")),
    ("drinks", ("bar", "pub", "wine_bar", "cocktail_bar", "brewery", "beer_garden", "lounge_bar")),
    ("food", ("restaurant", "meal_takeaway", "food_court", "deli", "sandwich_shop", "pizza")),
    ("stay", ("lodging", "hotel", "hostel", "motel", "resort_hotel", "bed_and_breakfast", "guest_house")),
    ("nature", ("park", "beach", "garden", "hiking_area", "national_park", "botanical_garden", "state_park", "campground")),
    ("activity", ("amusement_park", "zoo", "aquarium", "spa", "bowling_alley", "water_park", "tour_agency", "stadium", "sports_activity_location")),
    ("attraction", ("museum", "art_gallery", "tourist_attraction", "historical_landmark", "monument", "church", "place_of_worship", "observation_deck", "cultural_landmark", "plaza")),
    ("shopping", ("store", "shopping_mall", "market", "book_store", "clothing_store", "department_store")),
]
OSM_TAGS = {
    "amenity": {"restaurant": "food", "fast_food": "food", "food_court": "food", "cafe": "cafe", "ice_cream": "dessert",
                "bar": "drinks", "pub": "drinks", "biergarten": "drinks", "nightclub": "nightlife", "theatre": "activity",
                "cinema": "activity", "marketplace": "shopping", "place_of_worship": "attraction"},
    "tourism": {"museum": "attraction", "gallery": "attraction", "attraction": "attraction", "viewpoint": "attraction",
                "artwork": "attraction", "zoo": "activity", "theme_park": "activity", "aquarium": "activity",
                "hotel": "stay", "hostel": "stay", "guest_house": "stay", "motel": "stay", "apartment": "stay"},
    "leisure": {"park": "nature", "garden": "nature", "nature_reserve": "nature", "beach_resort": "nature",
                "water_park": "activity", "stadium": "activity"},
    "natural": {"*": "nature"},
    "historic": {"*": "attraction"},
    "shop": {"bakery": "cafe", "pastry": "dessert", "confectionery": "dessert", "chocolate": "dessert", "*": "shopping"},
}


def google_category(types: list[str]) -> str:
    for category, wanted in GOOGLE_TYPES:
        if any(t in wanted or (category == "food" and t.endswith("_restaurant")) or (category == "shopping" and t.endswith("_store"))
               for t in types):
            return category
    return "other"


def osm_category(key: str, value: str) -> str:
    tags = OSM_TAGS.get(key) or {}
    return tags.get(value) or tags.get("*") or "other"


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


class GooglePlacesGeocoder:
    URL = "https://places.googleapis.com/v1/places:searchText"
    # Opening hours put this request in Google's "Enterprise" Text Search tier (smaller free allowance).
    FIELDS = ("places.displayName,places.formattedAddress,places.location,places.googleMapsUri,"
              "places.regularOpeningHours,places.photos,places.rating,places.userRatingCount,"
              "places.websiteUri,places.internationalPhoneNumber")
    # Search results only need enough to pick one; details() then fetches the rest for the chosen place.
    SEARCH_FIELDS = "places.id,places.displayName,places.formattedAddress,places.location,places.types"
    DETAIL_FIELDS = ("id,displayName,formattedAddress,location,googleMapsUri,regularOpeningHours,photos,types,"
                     "addressComponents,rating,userRatingCount,websiteUri,internationalPhoneNumber")

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
            rating=p.get("rating"), rating_count=p.get("userRatingCount"),
            website=clean_website(p.get("websiteUri")), phone=clean_phone(p.get("internationalPhoneNumber")),
            photos=[
                {"source": "google", "ref": photo["name"],
                 "attribution": ", ".join(a.get("displayName", "") for a in photo.get("authorAttributions", [])) or None}
                for photo in (p.get("photos") or [])[:4] if photo.get("name")
            ],
        )

    async def search(self, query, near=None, limit=5) -> list[GeoMatch]:
        body: dict = {"textQuery": query, "pageSize": limit}
        if near:
            body["locationBias"] = {"circle": {"center": {"latitude": near[0], "longitude": near[1]}, "radius": 30000.0}}
        try:
            response = await self.client.post(
                self.URL, headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": self.SEARCH_FIELDS}, json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Google Places search failed for %r: %s", query, e)
            return []
        results = []
        for p in response.json().get("places") or []:
            loc = p.get("location") or {}
            if "latitude" not in loc or not p.get("id"):
                continue
            results.append(GeoMatch(
                name=(p.get("displayName") or {}).get("text") or query, latitude=loc["latitude"], longitude=loc["longitude"],
                address=p.get("formattedAddress"), place_id=f"google:{p['id']}", category=google_category(p.get("types") or []),
            ))
        return results

    async def details(self, place_id) -> Optional[GeoMatch]:
        if not place_id.startswith("google:"):
            return None
        pid = place_id.split(":", 1)[1]
        if not pid.replace("_", "").replace("-", "").isalnum():
            return None
        try:
            response = await self.client.get(
                f"https://places.googleapis.com/v1/places/{pid}",
                headers={"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": self.DETAIL_FIELDS},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Google Places details failed for %s: %s", pid, e)
            return None
        p = response.json()
        loc = p.get("location") or {}
        if "latitude" not in loc:
            return None
        parts = {t: c for c in p.get("addressComponents") or [] for t in c.get("types", [])}
        city = parts.get("locality") or parts.get("postal_town") or parts.get("administrative_area_level_2") or {}
        return GeoMatch(
            name=(p.get("displayName") or {}).get("text") or "",
            latitude=loc["latitude"], longitude=loc["longitude"], address=p.get("formattedAddress"),
            maps_url=p.get("googleMapsUri"), hours=from_google(p.get("regularOpeningHours")),
            rating=p.get("rating"), rating_count=p.get("userRatingCount"),
            website=clean_website(p.get("websiteUri")), phone=clean_phone(p.get("internationalPhoneNumber")),
            photos=[
                {"source": "google", "ref": photo["name"],
                 "attribution": ", ".join(a.get("displayName", "") for a in photo.get("authorAttributions", [])) or None}
                for photo in (p.get("photos") or [])[:4] if photo.get("name")
            ],
            place_id=place_id, category=google_category(p.get("types") or []),
            city=city.get("longText"), country=(parts.get("country") or {}).get("longText"),
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

    async def _search(self, params: dict, url: Optional[str] = None) -> list[dict]:
        params = {"format": "jsonv2", "addressdetails": 1, "extratags": 1, **({} if url else {"limit": 3}), **params}
        if self.email:
            params["email"] = self.email
        async with self._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self.client.get(url or self.URL, params=params)
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
                extratags = result.get("extratags") or {}
                image = await wikidata_image(self.client, extratags.get("wikidata", ""))
                return GeoMatch(
                    name=result.get("name") or name,
                    latitude=lat,
                    longitude=lon,
                    address=", ".join(p for p in (street, area) if p) or result.get("display_name"),
                    hours=parse_osm(extratags.get("opening_hours")),
                    website=osm_website(extratags), phone=osm_phone(extratags),
                    photos=[image] if image else [],
                )
        return None

    @staticmethod
    def _match(result: dict) -> GeoMatch:
        address = result.get("address") or {}
        street = " ".join(p for p in (address.get("house_number"), address.get("road")) if p)
        area = address.get("suburb") or address.get("neighbourhood") or address.get("city")
        osm_type = (result.get("osm_type") or "node")[0].upper()
        return GeoMatch(
            name=result.get("name") or (result.get("display_name") or "").split(",")[0],
            latitude=float(result["lat"]), longitude=float(result["lon"]),
            address=", ".join(p for p in (street, area) if p) or result.get("display_name"),
            place_id=f"osm:{osm_type}{result.get('osm_id')}",
            category=osm_category(result.get("category") or "", result.get("type") or ""),
            city=address.get("city") or address.get("town") or address.get("village") or address.get("municipality"),
            country=address.get("country"),
        )

    async def search(self, query, near=None, limit=5) -> list[GeoMatch]:
        params: dict = {"q": query, "limit": limit}
        if near:  # prefer, but don't require, results near the trip
            lat, lon = near
            params["viewbox"] = f"{lon - 0.4},{lat + 0.3},{lon + 0.4},{lat - 0.3}"
        return [self._match(r) for r in await self._search(params) if r.get("lat")]

    async def details(self, place_id) -> Optional[GeoMatch]:
        osm_id = place_id.split(":", 1)[1] if place_id.startswith("osm:") else ""
        if not (len(osm_id) > 1 and osm_id[0] in "NWR" and osm_id[1:].isdigit()):
            return None
        results = await self._search({"osm_ids": osm_id}, url="https://nominatim.openstreetmap.org/lookup")
        if not results:
            return None
        match = self._match(results[0])
        extratags = results[0].get("extratags") or {}
        match.hours = parse_osm(extratags.get("opening_hours"))
        match.website, match.phone = osm_website(extratags), osm_phone(extratags)
        image = await wikidata_image(self.client, extratags.get("wikidata", ""))
        match.photos = [image] if image else []
        return match


def make_geocoder(settings: Settings) -> Geocoder:
    choice = settings.geocoder
    if choice == "none":
        return NoGeocoder()
    if choice == "google" or (choice == "auto" and settings.google_maps_api_key):
        if not settings.google_maps_api_key:
            raise RuntimeError("GEOCODER=google needs GOOGLE_MAPS_API_KEY")
        return GooglePlacesGeocoder(settings.google_maps_api_key)
    return NominatimGeocoder(settings.nominatim_email)
