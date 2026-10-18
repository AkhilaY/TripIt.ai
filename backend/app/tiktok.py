"""TikTok specifics yt-dlp doesn't cover: short links and photo (slideshow) posts.

Photo posts ("/photo/<id>") are swipeable image carousels. List-style posts like "10 places to eat in
NYC" are often slideshows with the place names written on each slide, so the slides are what matter.
"""

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .models import ReelMetadata

log = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}
ITEM_RE = re.compile(r"/(video|photo)/(\d+)")
# Slide images come from TikTok's CDNs; never fetch anything else from data in the page.
IMAGE_HOST_SUFFIXES = ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "ibyteimg.com", "byteimg.com", "muscdn.com")
MAX_SLIDES = 20


def is_tiktok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def is_short_link(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in SHORT_HOSTS or (is_tiktok(url) and parsed.path.startswith("/t/"))


def is_photo_post(url: str) -> bool:
    match = ITEM_RE.search(urlparse(url).path)
    return bool(match and match.group(1) == "photo")


def resolve(url: str) -> str:
    """Expands tiktok.com/t/… and vm.tiktok.com/… to the full post URL. Only follows redirects within TikTok."""
    if not is_short_link(url):
        return url
    current = url
    with httpx.Client(timeout=15, headers={"User-Agent": BROWSER_UA}) as client:
        for _ in range(5):
            try:
                response = client.get(current, follow_redirects=False)
            except httpx.HTTPError as e:
                log.info("Couldn't expand %s: %s", url, e)
                return url
            location = response.headers.get("location")
            if response.status_code not in (301, 302, 303, 307, 308) or not location:
                break
            nxt = str(httpx.URL(current).join(location))
            if not is_tiktok(nxt):
                break
            current = nxt
            if not is_short_link(current):
                break
    # Drop tracking parameters (?_r=1&_t=…).
    parsed = urlparse(current)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _get_page(url: str) -> Optional[str]:
    """Fetches the post page, impersonating Chrome when curl_cffi is installed (TikTok checks TLS fingerprints)."""
    try:
        from curl_cffi import requests as cffi_requests

        response = cffi_requests.get(url, impersonate="chrome", timeout=20)
        if response.status_code == 200:
            return response.text
        log.info("TikTok page returned %s", response.status_code)
        return None
    except ImportError:
        pass
    except Exception as e:  # curl_cffi raises its own error types
        log.info("TikTok page fetch failed: %s", e)
        return None
    try:
        response = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=20, follow_redirects=True)
        return response.text if response.status_code == 200 else None
    except httpx.HTTPError as e:
        log.info("TikTok page fetch failed: %s", e)
        return None


def parse_item(html: str) -> Optional[dict[str, Any]]:
    """Finds the post data TikTok embeds in its web page."""
    match = re.search(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        try:
            data = json.loads(match.group(1))
            item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
            if item:
                return item
        except (ValueError, KeyError, TypeError):
            pass
    match = re.search(r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.S)
    if match:
        try:
            items = json.loads(match.group(1)).get("ItemModule") or {}
            return next(iter(items.values()), None)
        except (ValueError, AttributeError):
            pass
    return None


def slide_urls(item: dict[str, Any]) -> list[str]:
    images = ((item.get("imagePost") or {}).get("images")) or []
    urls = []
    for image in images:
        candidates = ((image.get("imageURL") or {}).get("urlList")) or []
        url = next((u for u in candidates if _allowed_image(u)), None)
        if url:
            urls.append(url)
    return urls[:MAX_SLIDES]


def _allowed_image(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == s or host.endswith("." + s) for s in IMAGE_HOST_SUFFIXES)


def metadata_from_item(item: dict[str, Any], url: str) -> ReelMetadata:
    caption = (item.get("desc") or "").strip()
    author = item.get("author")
    uploader = author.get("uniqueId") if isinstance(author, dict) else author
    title = ((item.get("imagePost") or {}).get("title") or caption)[:120] or None
    return ReelMetadata(platform="tiktok", url=url, title=title, caption=caption or None, uploader=uploader)


def download_photo_post(url: str, workdir: Path, frame_width: int = 1024) -> Optional[tuple[ReelMetadata, list[Path]]]:
    """Downloads a TikTok slideshow's caption and slide images. Returns None if TikTok didn't serve the post."""
    html = _get_page(url)
    item = parse_item(html) if html else None
    if not item:
        return None
    metadata = metadata_from_item(item, url)
    paths: list[Path] = []
    with httpx.Client(timeout=20, headers={"User-Agent": BROWSER_UA, "Referer": "https://www.tiktok.com/"}) as client:
        for i, image_url in enumerate(slide_urls(item), start=1):
            try:
                response = client.get(image_url)
                response.raise_for_status()
            except httpx.HTTPError as e:
                log.info("Slide %d download failed: %s", i, e)
                continue
            raw = workdir / f"slide_{i:02d}.img"
            raw.write_bytes(response.content)
            jpeg = _normalize(raw, workdir / f"slide_{i:02d}.jpg", frame_width)
            if jpeg:
                paths.append(jpeg)
    return metadata, paths


def _normalize(src: Path, dst: Path, width: int) -> Optional[Path]:
    """Converts a slide (webp, png, jpeg) to a JPEG no wider than `width`, which keeps the Claude request small."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", f"scale='min({width},iw)':-2", "-q:v", "3", str(dst)],
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0 or not dst.exists():
        log.info("Couldn't convert %s: %s", src.name, result.stderr.decode(errors="ignore")[:200])
        return None
    return dst
