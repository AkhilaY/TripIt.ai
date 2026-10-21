"""Discover: well-rated places near you, ranked for your taste, for people who don't live on social media.

Candidates come from Google Maps (popular places of a kind around a point, with their ratings). Claude adds a
line on why each suits you and, only when it is confident, a recognition such as a Michelin star. Those labels
come from Claude's knowledge, not a feed, so the app shows them with a "check before you go" note. Michelin and
Yelp don't offer open data feeds; Yelp can be added later if its terms allow.
"""

import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from .concierge import profile_text
from .db import Database, normalize
from .geocode import GooglePlacesGeocoder
from .llm import ClaudeError, ClaudeService
from .models import DiscoverArea, DiscoverItem, DiscoverNotes, DiscoverResult, TasteProfile
from .photos import PhotoStore

log = logging.getLogger(__name__)

KINDS = {
    "restaurants": ["restaurant"],
    "coffee": ["cafe", "coffee_shop", "bakery"],
    "bars": ["bar", "pub", "wine_bar"],
    "dessert": ["ice_cream_shop", "dessert_shop", "confectionery"],
    "things": ["tourist_attraction", "museum", "art_gallery"],
}
FRESH_HOURS = 24
SHOWN = 15
EXPLAINED = 10
PRICE = {"PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2, "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))


def parse_nearby(raw: dict) -> Optional[dict]:
    """One Places API result as the fields we keep, or None when it lacks what's needed."""
    try:
        pid = raw["id"]
        name = (raw.get("displayName") or {}).get("text")
        loc = raw.get("location") or {}
        if not pid or not name or "latitude" not in loc:
            return None
        photos = raw.get("photos") or []
        return {
            "id": f"google:{pid}", "name": name[:150], "kind_label": ((raw.get("primaryTypeDisplayName") or {}).get("text") or None),
            "address": raw.get("formattedAddress"), "latitude": loc["latitude"], "longitude": loc["longitude"],
            "rating": raw.get("rating"), "rating_count": raw.get("userRatingCount"), "price_level": PRICE.get(raw.get("priceLevel") or ""),
            "maps_url": raw.get("googleMapsUri"), "photo": photos[0].get("name") if photos and photos[0].get("name") else None,
        }
    except (KeyError, TypeError, AttributeError):
        return None


def score(item: dict) -> float:
    return (item["rating"] or 0) * math.log10((item["rating_count"] or 0) + 10)


class DiscoverService:
    def __init__(self, db: Database, claude: Optional[ClaudeService], geocoder, photos: PhotoStore):
        self.db = db
        self.claude = claude
        self.geocoder = geocoder
        self.photos = photos

    def photo_url(self, ref: str) -> str:
        return f"/v1/discover/photo?ref={quote(ref, safe='')}&sig={self.photos.signature('discover', 0, ref)}"

    @staticmethod
    def _taste_key(profile: TasteProfile) -> str:
        return hashlib.sha1(json.dumps([profile.pace, profile.budget, sorted(profile.food), sorted(profile.interests), profile.notes]).encode()).hexdigest()[:10]

    async def discover(self, kind: str, area: DiscoverArea, radius_m: int, profile: TasteProfile, refresh: bool = False) -> DiscoverResult:
        if not isinstance(self.geocoder, GooglePlacesGeocoder):
            return DiscoverResult(status="disabled", area=area, kind=kind)
        key = f"{kind}:{round(area.latitude, 2)}:{round(area.longitude, 2)}:{radius_m}:{self._taste_key(profile)}"
        row = self.db.get_discover(key)
        data = None
        if row and not refresh and datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"]) < timedelta(hours=FRESH_HOURS):
            data = json.loads(row["data"])
        if data is None:
            raw = await self.geocoder.nearby(area.latitude, area.longitude, KINDS[kind], radius_m)
            if raw is None:
                data = json.loads(row["data"]) if row else None  # Google is down: show what we had
                if data is None:
                    return DiscoverResult(status="error", area=area, kind=kind)
            else:
                items = [i for i in (parse_nearby(r) for r in raw) if i]
                floor = 300 if kind == "things" else 100
                good = [i for i in items if (i["rating"] or 0) >= 4.2 and (i["rating_count"] or 0) >= floor]
                good = sorted(good, key=score, reverse=True)[:SHOWN]
                curated = await self._explain(good, area, kind, profile)
                data = {"items": good, "curated_by": curated, "fetched_at": datetime.now(timezone.utc).isoformat()}
                self.db.save_discover(key, data)

        saved = [(normalize(p.name), p.latitude, p.longitude) for p in self.db.list_places()]
        out = []
        for raw_item in data["items"]:
            item = DiscoverItem(**{**raw_item, "photo": self.photo_url(raw_item["photo"]) if raw_item.get("photo") else None})
            item.distance_m = round(metres(area.latitude, area.longitude, item.latitude, item.longitude))
            n = normalize(item.name)
            item.saved = any(sn == n or (slat is not None and metres(item.latitude, item.longitude, slat, slon) < 60 and (sn in n or n in sn))
                             for sn, slat, slon in saved)
            out.append(item)
        return DiscoverResult(status="ok", area=area, kind=kind, items=out, curated_by=data.get("curated_by"), fetched_at=data["fetched_at"])

    async def _explain(self, items: list[dict], area: DiscoverArea, kind: str, profile: TasteProfile) -> Optional[str]:
        top = items[:EXPLAINED]
        if not top:
            return None
        if self.claude is not None:
            context = {
                "taste": profile_text(profile) or None, "area": area.name, "looking_for": kind,
                "places": [{k: v for k, v in {"id": i["id"], "name": i["name"], "type": i["kind_label"], "rating": i["rating"],
                                              "reviews": i["rating_count"], "price": i["price_level"], "address": i["address"]}.items() if v is not None} for i in top],
            }
            try:
                notes: DiscoverNotes = await self.claude.explain_discover({k: v for k, v in context.items() if v})
                by_id = {n.id: n for n in notes.notes}
                for i in top:
                    note = by_id.get(i["id"])
                    if note:
                        i["why"] = " ".join(note.why.split())[:160] or None
                        i["award"] = " ".join((note.award or "").split())[:40] or None
                return "claude"
            except ClaudeError as e:
                log.warning("Claude discover notes failed, showing plain results: %s", e)
        return "offline"
