"""TikTok specifics yt-dlp doesn't cover: short links and photo (slideshow) posts.

Photo posts ("/photo/<id>") are swipeable image carousels. List-style posts like "10 places to eat in
NYC" are often slideshows with the place names written on each slide, so the slides are what matter.
"""

import json
import logging
import re
import subprocess
import time
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
# Browsers to look like when fetching TikTok pages, best first. TikTok sends servers that look like desktop Chrome a
# 1.5 KB page without the post, while these four get the whole page (checked from the Fly server).
PROFILES = ("chrome_android", "safari_ios", "safari", "edge", "chrome")
EMBED_PAUSE = 0.8  # seconds between embed page tries; TikTok answers 503 to quick repeats


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


def _get_page(url: str, cookies: Optional[dict[str, str]] = None, profile: str = PROFILES[0]) -> Optional[str]:
    """Fetches a TikTok page looking like the given browser when curl_cffi is installed (TikTok checks TLS
    fingerprints)."""
    try:
        from curl_cffi import requests as cffi_requests

        response = cffi_requests.get(url, impersonate=profile, timeout=20, cookies=cookies or None)
        if response.status_code == 200:
            return response.text
        log.info("TikTok page returned %s as %s", response.status_code, profile)
        return None
    except ImportError:
        pass
    except Exception as e:  # curl_cffi raises its own error types, also for a profile it doesn't know
        log.info("TikTok page fetch failed as %s: %s", profile, e)
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
        key = urlparse(url).path.split("~")[0]  # the same slide in several sizes and from several hosts
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


def embed_post(html: str, url: str) -> Optional[tuple[ReelMetadata, list[str]]]:
    """Caption, creator and slides from the embed page's data (__FRONTITY_CONNECT_STATE__ → source.data →
    videoData), or from the slide addresses in the page if that data moves."""
    video = None
    match = re.search(r'<script[^>]+id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        try:
            data = ((json.loads(match.group(1)).get("source") or {}).get("data")) or {}
            video = next((v["videoData"] for v in data.values() if isinstance(v, dict) and isinstance(v.get("videoData"), dict)), None)
        except (ValueError, AttributeError, TypeError):
            video = None
    if video:
        caption = ((video.get("itemInfos") or {}).get("text") or "").strip()
        uploader = (video.get("authorInfos") or {}).get("uniqueId")
        images = []
        for image in (video.get("imagePostInfo") or {}).get("displayImages") or []:
            candidate = next((u for u in (image.get("urlList") or []) if _allowed_image(u)), None)
            if candidate:
                images.append(candidate)
        images = images[:MAX_SLIDES]
    else:
        caption, uploader, images = embed_caption(html) or "", None, embed_slides(html)
    if not (caption or images):
        return None
    metadata = ReelMetadata(platform="tiktok", url=url, title=caption[:120] or None, caption=caption or None, uploader=uploader)
    return metadata, images


def find_photo_post(url: str, cookies: Optional[dict[str, str]] = None) -> Optional[tuple[ReelMetadata, list[str]]]:
    """A slideshow's caption and slide addresses, from whichever page TikTok will serve: the post as a video address
    (the photo address never carries the data for a server), looking like each browser in turn; then the embed page;
    then the photo page itself."""
    match = ITEM_RE.search(urlparse(url).path)
    if not match:
        return None
    caption_only: Optional[ReelMetadata] = None
    video_url = url.replace("/photo/", "/video/")
    for profile in PROFILES:
        html = _get_page(video_url, cookies, profile)
        item = parse_item(html) if html else None
        if item:
            slides = slide_urls(item)
            if slides:
                return metadata_from_item(item, url), slides
            caption_only = caption_only or metadata_from_item(item, url)
    for i, profile in enumerate(PROFILES):
        if i:
            time.sleep(EMBED_PAUSE)
        html = _get_page(f"https://www.tiktok.com/embed/v2/{match.group(2)}", cookies, profile)
        found = embed_post(html, url) if html else None
        if found and found[1]:
            return found
        caption_only = caption_only or (found[0] if found else None)
    html = _get_page(url, cookies)
    item = parse_item(html) if html else None
    if item and slide_urls(item):
        return metadata_from_item(item, url), slide_urls(item)
    if caption_only is None:
        log.info("TikTok served none of the pages for %s", url)
        return None
    return caption_only, []


def download_photo_post(url: str, workdir: Path, frame_width: int = 1024,
                        cookies: Optional[dict[str, str]] = None) -> Optional[tuple[ReelMetadata, list[Path]]]:
    """Downloads a TikTok slideshow's caption and slide images. Returns None if TikTok served none of its pages."""
    found = find_photo_post(url, cookies)
    if found is None:
        return None
    metadata, images = found
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
