"""Instagram photo posts (one picture or a carousel of slides, no video), which yt-dlp can't download.

Reads the post's public embed page, the one Instagram serves to other websites: its slides' pictures and the
caption. Only for public posts; nothing is signed in.
"""
import html as htmllib
import json
import logging
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from .models import ReelMetadata

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/18.0 Mobile/15E148 Safari/604.1")
MAX_SLIDES = 10


def shortcode(url: str) -> Optional[str]:
    parts = [p for p in urlparse(url).path.split("/") if p]
    for i, part in enumerate(parts[:-1]):
        if part in ("p", "reel", "reels", "tv"):
            return parts[i + 1]
    return None


def _media_from_context(page: str) -> Optional[dict]:
    """The post's data, when the embed page carries it (as an escaped JSON string named contextJSON)."""
    match = re.search(r'"contextJSON"\s*:\s*("(?:[^"\\]|\\.)*")', page)
    if not match:
        return None
    try:
        context = json.loads(json.loads(match.group(1)))
    except ValueError:
        return None
    media = (context.get("gql_data") or {}).get("shortcode_media") or context.get("media")
    return media if isinstance(media, dict) else None


def parse_embed(page: str) -> tuple[list[str], str, str]:
    """(picture links, caption, author) from an embed page."""
    pictures: list[str] = []
    caption = author = ""
    media = _media_from_context(page)
    if media:
        edges = ((media.get("edge_sidecar_to_children") or {}).get("edges")) or []
        nodes = [e.get("node") or {} for e in edges] or [media]
        for node in nodes:
            if not node.get("is_video") and node.get("display_url"):
                pictures.append(node["display_url"])
        captions = ((media.get("edge_media_to_caption") or {}).get("edges")) or []
        if captions:
            caption = (captions[0].get("node") or {}).get("text") or ""
        author = (media.get("owner") or {}).get("username") or ""
    if not pictures:
        for src in re.findall(r'<img[^>]+class="[^"]*EmbeddedMediaImage[^"]*"[^>]*\ssrc="([^"]+)"', page):
            pictures.append(htmllib.unescape(src))
    if not caption:
        match = re.search(r'<div class="Caption">(.*?)<div class="CaptionComments">', page, re.S)
        if match:
            text = re.sub(r"<br\s*/?>", "\n", match.group(1))
            text = re.sub(r'<a class="CaptionUsername"[^>]*>.*?</a>', "", text, flags=re.S)
            caption = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).strip()
    if not author:
        match = re.search(r'class="UsernameText"[^>]*>([^<]+)<', page)
        author = htmllib.unescape(match.group(1)).strip() if match else ""
    seen: list[str] = []
    for p in pictures:
        if p not in seen:
            seen.append(p)
    return seen[:MAX_SLIDES], caption, author


def download_photo_post(url: str, workdir: Path, client: Optional[httpx.Client] = None) -> Optional[tuple[ReelMetadata, list[Path]]]:
    """The post's caption and its pictures saved as slides, or None if the embed page had neither."""
    code = shortcode(url)
    if not code:
        return None
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    try:
        r = client.get(f"https://www.instagram.com/p/{code}/embed/captioned/")
        if r.status_code != 200:
            log.warning("Instagram embed answered %s", r.status_code)
            return None
        pictures, caption, author = parse_embed(r.text)
        slides: list[Path] = []
        for i, link in enumerate(pictures, start=1):
            try:
                img = client.get(link)
            except httpx.HTTPError:
                continue
            if img.status_code == 200 and img.headers.get("content-type", "").startswith("image/"):
                path = workdir / f"ig-slide-{i:02d}.jpg"
                path.write_bytes(img.content)
                slides.append(path)
        if not slides and not caption:
            return None
        metadata = ReelMetadata(platform="instagram", url=url, caption=caption or None, uploader=author or None)
        return metadata, slides
    except httpx.HTTPError as e:
        log.warning("Instagram embed failed: %s", e)
        return None
    finally:
        if own:
            client.close()
