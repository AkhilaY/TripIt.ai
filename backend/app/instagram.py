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
    pictures, _, caption, author = parse_embed_media(page)
    return pictures, caption, author


def parse_embed_media(page: str) -> tuple[list[str], list[str], str, str]:
    """(picture links, video links, caption, author) from an embed page."""
    pictures: list[str] = []
    videos: list[str] = []
    caption = author = ""
    media = _media_from_context(page)
    if media:
        edges = ((media.get("edge_sidecar_to_children") or {}).get("edges")) or []
        nodes = [e.get("node") or {} for e in edges] or [media]
        for node in nodes:
            if node.get("is_video") and node.get("video_url"):
                videos.append(node["video_url"])
            elif not node.get("is_video") and node.get("display_url"):
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
    if not videos:
        videos = [htmllib.unescape(v) for v in re.findall(r'<video[^>]+src="([^"]+)"', page)]
    return list(dict.fromkeys(pictures))[:MAX_SLIDES], list(dict.fromkeys(videos))[:1], caption, author


def resolve(url: str, client: Optional[httpx.Client] = None) -> str:
    """Instagram's share links (instagram.com/share/...) open the post they point to; others are left alone."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts or parts[0] != "share":
        return url
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    try:
        final = str(client.get(url).url)
        host = (urlparse(final).hostname or "").lower()
        return final if (host == "instagram.com" or host.endswith(".instagram.com")) and shortcode(final) else url
    except httpx.HTTPError as e:
        log.warning("Instagram share link didn't open: %s", e)
        return url
    finally:
        if own:
            client.close()


def download_post(url: str, workdir: Path, client: Optional[httpx.Client] = None,
                  max_video_bytes: int = 80 << 20) -> Optional[tuple[ReelMetadata, list[Path], Optional[Path]]]:
    """A post read from its public embed page: (caption and author, pictures saved as slides, the video if it
    has one), or None if the page gave nothing usable. Used for photo posts and carousels, which yt-dlp can't
    download, and as a second way in when yt-dlp is blocked."""
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
        pictures, videos, caption, author = parse_embed_media(r.text)
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
        video: Optional[Path] = None
        for link in videos:
            try:
                with client.stream("GET", link) as v:
                    if v.status_code != 200 or not v.headers.get("content-type", "").startswith("video/"):
                        continue
                    path, size = workdir / "ig-video.mp4", 0
                    with path.open("wb") as out:
                        for chunk in v.iter_bytes():
                            size += len(chunk)
                            if size > max_video_bytes:
                                break
                            out.write(chunk)
                    if size <= max_video_bytes:
                        video = path
            except httpx.HTTPError:
                continue
        if not slides and not caption and video is None:
            return None
        metadata = ReelMetadata(platform="instagram", url=url, caption=caption or None, uploader=author or None)
        return metadata, slides, video
    except httpx.HTTPError as e:
        log.warning("Instagram embed failed: %s", e)
        return None
    finally:
        if own:
            client.close()


def download_photo_post(url: str, workdir: Path, client: Optional[httpx.Client] = None) -> Optional[tuple[ReelMetadata, list[Path]]]:
    got = download_post(url, workdir, client)
    return (got[0], got[1]) if got else None
