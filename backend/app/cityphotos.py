"""Photos of cities for the app's city cards and Home header, and the cover of a trip's PDF.

The places the app features have hand-picked Unsplash photos (data/city_photos.json, made by ios/scripts/photos/gen.py).
Any other city gets the best Unsplash search result the first time it's asked for, kept in the database so each
city is searched only once. Unsplash's rules, followed here and in the app: the photographer is named where a photo
is shown, images are loaded from Unsplash's own addresses, and Unsplash is told when the app picks a photo (the
"download" ping).
"""
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from .db import Database

log = logging.getLogger(__name__)
CATALOGUE = json.loads((Path(__file__).parent / "data" / "city_photos.json").read_text())
RETRY_AFTER = timedelta(days=7)  # a city with no good photo is searched again after this long


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(folded.casefold().split())


def curated(city: str) -> Optional[dict]:
    """The hand-picked photo for this city: its own, or its featured place's when the city is that place's
    (Kyoto, or Lucerne for "Lake Lucerne"), not just in the same country."""
    key = norm(city)
    if len(key) < 3:
        return None
    if key in CATALOGUE["cities"]:
        return CATALOGUE["cities"][key]
    for p in CATALOGUE["places"]:
        if (p["names"] and p["names"][0] == key) or re.search(rf"\b{re.escape(key)}\b", norm(p["place"])):
            return {"photo": p["photo"], "name": p["name"], "username": p["username"]}
    return None


def image_url(photo: str, width: int, height: int, quality: int = 80) -> str:
    return f"https://images.unsplash.com/{photo}?w={width}&h={height}&fit=crop&crop=entropy&q={quality}&fm=jpg"


class CityPhotos:
    def __init__(self, db: Database, access_key: str):
        self.db, self.key = db, access_key

    async def get(self, city: str, country: str = "") -> Optional[dict]:
        """{"photo", "name", "username"} for this city, or None when there's no good one (yet)."""
        if hit := curated(city):
            return hit
        key = f"{norm(city)}|{norm(country)}"
        row = self.db.city_photo(key)
        if row:
            if row["photo"]:
                return {"photo": row["photo"], "name": row["name"], "username": row["username"]}
            if datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - RETRY_AFTER:
                return None
        if not self.key or not norm(city):
            return None
        found = await self._search(" ".join(x for x in (city, country) if x))
        if found is _BUSY:
            return None  # over Unsplash's hourly limit: nothing is saved, so it's tried again next time
        self.db.save_city_photo(key, found)
        return found

    async def _search(self, query: str):
        headers = {"Authorization": f"Client-ID {self.key}", "Accept-Version": "v1"}
        try:
            async with httpx.AsyncClient(timeout=12, headers=headers) as client:
                r = await client.get("https://api.unsplash.com/search/photos",
                                     params={"query": query, "per_page": 8, "orientation": "portrait", "content_filter": "high"})
                if r.status_code in (403, 429):
                    log.warning("Unsplash search refused (%s): over the hourly limit?", r.status_code)
                    return _BUSY
                r.raise_for_status()
                # Unsplash+ photos aren't free to use. Of the most relevant few, the best liked.
                results = [x for x in r.json().get("results", [])[:6]
                           if x["urls"]["raw"].startswith("https://images.unsplash.com/") and x["width"] >= 1500]
                if not results:
                    return None
                best = max(results, key=lambda x: x.get("likes", 0))
                try:  # Unsplash asks to be told which photo an app chose (it credits the photographer)
                    await client.get(best["links"]["download_location"])
                except httpx.HTTPError:
                    pass
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("Unsplash search failed: %s", type(e).__name__)
            return _BUSY
        return {"photo": best["urls"]["raw"].split("?")[0].rsplit("/", 1)[-1], "name": best["user"]["name"],
                "username": best["user"]["username"]}


_BUSY = object()
