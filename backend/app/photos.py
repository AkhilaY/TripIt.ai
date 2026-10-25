"""Place photos.

Stored per place as a list of {"source", "ref", "attribution"}:
- reel:      ref is a file name in PHOTOS_DIR (a frame or slide from the shared reel)
- google:    ref is a Places API photo resource name; served through the server so the key stays private
- wikimedia: ref is a Wikimedia Commons image URL (free, for landmarks)

Browsers load photos with plain <img> tags, which can't send the API key header, so photo URLs carry a
signature derived from APP_API_KEY instead.
"""

import hashlib
import hmac
import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

MAX_REEL = 3
MAX_GOOGLE = 4


class PhotoStore:
    def __init__(self, directory: Path, secret: str):
        self.dir = directory
        self.secret = secret.encode()
        self.dir.mkdir(parents=True, exist_ok=True)

    def signature(self, place_id: str, index: int, ref: str) -> str:
        return hmac.new(self.secret, f"{place_id}/{index}/{ref}".encode(), hashlib.sha256).hexdigest()[:24]

    def url(self, place_id: str, index: int, ref: str) -> str:
        return f"/v1/places/{place_id}/photos/{index}?sig={self.signature(place_id, index, ref)}"

    def check(self, place_id: str, index: int, ref: str, sig: str) -> bool:
        return not self.secret or hmac.compare_digest(self.signature(place_id, index, ref), sig or "")

    def save_reel_image(self, place_id: str, source: Path) -> Optional[str]:
        name = f"{place_id}_{uuid.uuid4().hex[:8]}.jpg"
        try:
            shutil.copyfile(source, self.dir / name)
        except OSError as e:
            log.warning("Couldn't save reel photo: %s", e)
            return None
        return name

    def path(self, ref: str) -> Optional[Path]:
        if "/" in ref or "\\" in ref or ref.startswith("."):
            return None
        p = self.dir / ref
        return p if p.is_file() else None

    def delete(self, photos: list[dict]) -> None:
        for photo in photos:
            if photo.get("source") == "reel":
                p = self.path(photo.get("ref", ""))
                if p:
                    p.unlink(missing_ok=True)


def merge(existing: list[dict], new: list[dict], replace_sources: tuple[str, ...] = ()) -> list[dict]:
    """Keeps order google → reel → wikimedia, drops duplicates, caps each source."""
    kept = [p for p in existing if p.get("source") not in replace_sources]
    combined = kept + [p for p in new if p.get("ref") not in {k.get("ref") for k in kept}]
    order = {"google": 0, "reel": 1, "wikimedia": 2}
    combined.sort(key=lambda p: order.get(p.get("source"), 3))
    caps = {"google": MAX_GOOGLE, "reel": MAX_REEL, "wikimedia": 1}
    counts: dict[str, int] = {}
    out = []
    for p in combined:
        counts[p["source"]] = counts.get(p["source"], 0) + 1
        if counts[p["source"]] <= caps.get(p["source"], 1):
            out.append(p)
    return out


async def wikidata_image(client: httpx.AsyncClient, qid: str) -> Optional[dict]:
    """Main image (P18) of a Wikidata item, as a Wikimedia Commons URL."""
    if not qid or not qid.startswith("Q") or not qid[1:].isdigit():
        return None
    try:
        response = await client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", timeout=10)
        response.raise_for_status()
        entity = response.json()["entities"][qid]
        filename = entity["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
        return None
    return {
        "source": "wikimedia",
        "ref": f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename.replace(' ', '_'))}?width=1000",
        "attribution": "Wikimedia Commons",
    }


async def fetch_bytes(photo: dict, store: "PhotoStore", google_key: str, width: int = 480,
                      count_google=None) -> Optional[bytes]:
    """A stored photo's image bytes (small), for Claude to look at. None when it can't be loaded."""
    source, ref = photo.get("source"), photo.get("ref") or ""
    try:
        if source == "reel":
            path = store.path(ref)
            return path.read_bytes() if path else None
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            if source == "wikimedia":
                r = await client.get(ref.split("?")[0] + f"?width={width}")
            elif source == "google" and google_key:
                if count_google:
                    count_google("photo")
                r = await client.get(f"https://places.googleapis.com/v1/{ref}/media", params={"maxWidthPx": width, "key": google_key})
            else:
                return None
        ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
        return r.content if ok and len(r.content) < 4_000_000 else None
    except (httpx.HTTPError, OSError):
        return None
