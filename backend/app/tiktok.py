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


def cookies_for_tiktok(cookie_file: Optional[str]) -> dict[str, str]:
    """TikTok cookies from a Netscape cookies.txt (the YTDLP_COOKIES setting). Signed-in cookies make TikTok far
    more willing to send a post's data to a server."""
    out: dict[str, str] = {}
    if not cookie_file:
        return out
    try:
        lines = Path(cookie_file).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) == 7 and not line.startswith("#") and parts[0].lstrip(".").endswith("tiktok.com"):
            out[parts[5]] = parts[6]
    return out


def _get_page(url: str, cookies: Optional[dict[str, str]] = None) -> Optional[str]:
    """Fetches the post page, impersonating Chrome when curl_cffi is installed (TikTok checks TLS fingerprints)."""
    try:
        from curl_cffi import requests as cffi_requests

        response = cffi_requests.get(url, impersonate="chrome", timeout=20, cookies=cookies or None)
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
        response = httpx.get(url, headers={"User-Agent": BROWSER_UA}, timeout=20, follow_redirects=True, cookies=cookies or None)
        return response.text if response.status_code == 200 else None
    except httpx.HTTPError as e:
        log.info("TikTok page fetch failed: %s", e)
        return None


def parse_item(html: str) -> Optional[dict[str, Any]]:
    """Finds the post data TikTok embeds in its web page."""
    match = re.search(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        try:
            scope = json.loads(match.group(1)).get("__DEFAULT_SCOPE__") or {}
            # Usually "webapp.video-detail"; TikTok renames these, so look through every part of the page data.
            parts = [scope.get("webapp.video-detail")] + [v for k, v in scope.items() if k != "webapp.video-detail"]
            for part in parts:
                item = ((part or {}).get("itemInfo") or {}).get("itemStruct") if isinstance(part, dict) else None
                if item and item.get("id"):
                    return item
        except (ValueError, AttributeError, TypeError):
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


def embed_slides(html: str) -> list[str]:
    """Slide images from TikTok's embed page (meant for other sites, so served more readily than the post page).
    Found by their address rather than the page's structure, which changes: photo-mode images on TikTok's CDN."""
    text = html.replace("\\u002F", "/").replace("\\/", "/").replace("&amp;", "&")
    seen, out = set(), []
    for url in re.findall(r'https://[^"\'\s<>\\]+', text):
        if "photomode" not in url or not _allowed_image(url):
            continue
        key = url.split("?")[0].split("~")[0]  # the same slide in several sizes
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out[:MAX_SLIDES]


def embed_caption(html: str) -> Optional[str]:
    match = re.search(r'"desc"\s*:\s*("(?:[^"\\]|\\.)*")', html)
    if match:
        try:
            return json.loads(match.group(1)).strip() or None
        except ValueError:
            pass
    meta = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', html)
    return meta.group(1).strip() or None if meta else None


def download_photo_post(url: str, workdir: Path, frame_width: int = 1024,
                        cookies: Optional[dict[str, str]] = None) -> Optional[tuple[ReelMetadata, list[Path]]]:
    """Downloads a TikTok slideshow's caption and slide images: from the post page (as a photo, then as a video
    address, which TikTok often serves when the photo one is blocked), then from the embed page. Returns None if
    TikTok served none of them."""
    item, images = None, []
    for page in dict.fromkeys([url, url.replace("/photo/", "/video/")]):
        html = _get_page(page, cookies)
        found = parse_item(html) if html else None
        if found:
            item = item or found
            images = slide_urls(found)
            if images:
                break
    metadata = metadata_from_item(item, url) if item else None
    if not images:
        match = ITEM_RE.search(urlparse(url).path)
        embed = _get_page(f"https://www.tiktok.com/embed/v2/{match.group(2)}", cookies) if match else None
        if embed:
            images = embed_slides(embed)
            caption = embed_caption(embed)
            if metadata is None and (images or caption):
                metadata = ReelMetadata(platform="tiktok", url=url, title=(caption or "")[:120] or None, caption=caption)
    if metadata is None:
        log.info("TikTok served neither the post nor its embed for %s", url)
        return None
    paths: list[Path] = []
    with httpx.Client(timeout=20, headers={"User-Agent": BROWSER_UA, "Referer": "https://www.tiktok.com/"}) as client:
        for i, image_url in enumerate(images, start=1):
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


def fetch_cover(image_url: str, workdir: Path, width: int = 1024) -> Optional[Path]:
    """Downloads a post's cover image (from TikTok's embed API), so a post that can't be downloaded still shows
    Claude its first slide or frame."""
    if not image_url or not _allowed_image(image_url):
        return None
    try:
        response = httpx.get(image_url, headers={"User-Agent": BROWSER_UA, "Referer": "https://www.tiktok.com/"}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPError as e:
        log.info("Cover download failed: %s", e)
        return None
    raw = workdir / "cover.img"
    raw.write_bytes(response.content)
    return _normalize(raw, workdir / "cover.jpg", width)
