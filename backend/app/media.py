"""Downloading reels and turning them into things Claude can read: caption, audio, frames."""

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import Settings
from .models import ReelMetadata

log = logging.getLogger(__name__)

# Only these hosts are accepted. yt-dlp's generic extractor would otherwise fetch any URL (SSRF risk).
ALLOWED_HOSTS = {
    "tiktok.com": "tiktok",
    "vm.tiktok.com": "tiktok",
    "vt.tiktok.com": "tiktok",
    "instagram.com": "instagram",
    "instagr.am": "instagram",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
}

URL_RE = re.compile(r"https?://[^\s<>\"']+")


class UnsupportedURLError(ValueError):
    pass


def find_url(text: str) -> Optional[str]:
    """Pull the first link out of shared text like 'Check this out! https://vm.tiktok.com/abc/'."""
    match = URL_RE.search(text)
    return match.group(0).rstrip(").,") if match else None


def platform_for(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsupportedURLError("Not a web link")
    host = parsed.hostname.lower()
    for allowed, platform in ALLOWED_HOSTS.items():
        if host == allowed or host.endswith("." + allowed):
            return platform
    raise UnsupportedURLError("Only TikTok, Instagram and YouTube links are supported")


@dataclass
class DownloadedReel:
    metadata: ReelMetadata
    video_path: Optional[Path] = None
    image_paths: list[Path] = field(default_factory=list)


def download_reel(url: str, workdir: Path, settings: Settings) -> DownloadedReel:
    """Download a reel with yt-dlp. Falls back to metadata-only if the media can't be fetched."""
    import yt_dlp

    platform = platform_for(url)
    opts = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "format": "best[height<=720]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,  # IG carousels come through as playlists
        "playlistend": 10,
        "socket_timeout": 30,
        "match_filter": yt_dlp.utils.match_filter_func(f"duration <=? {settings.max_video_seconds}"),
    }
    cookie_file = settings.ytdlp_cookies_file or _cookies_from_env(settings.ytdlp_cookies)
    if cookie_file:
        opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            log.warning("Media download failed, retrying for metadata only: %s", e)
            try:
                info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as e2:
                log.warning("Metadata fetch failed too: %s", e2)
                raise DownloadFailed(clean_error(str(e2))) from e2
            return DownloadedReel(metadata=_metadata(info, url, platform))

    reel = DownloadedReel(metadata=_metadata(info, url, platform))
    for path in sorted(workdir.iterdir()):
        suffix = path.suffix.lower()
        if suffix in (".mp4", ".mov", ".webm", ".mkv") and reel.video_path is None:
            reel.video_path = path
        elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
            reel.image_paths.append(path)
    return reel


class DownloadFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def clean_error(message: str) -> str:
    """Turns a yt-dlp error into one short line people can act on."""
    line = _ANSI.sub("", message).strip().splitlines()[0] if message.strip() else "unknown error"
    line = re.sub(r"^ERROR:\s*", "", line)
    line = re.sub(r"^\[[^\]]+\]\s*[\w-]*:\s*", "", line)  # "[TikTok] 7420…: " prefix
    line = line.split("; please report this issue")[0].rstrip(". ")
    return line[:180] or "unknown error"


OEMBED = {
    "tiktok": "https://www.tiktok.com/oembed",
    "youtube": "https://www.youtube.com/oembed",
}


def fetch_oembed(url: str) -> Optional[ReelMetadata]:
    """Caption and creator from the platform's public embed API. Works when video downloads are blocked.
    Instagram's embed API needs a Meta app token, so it isn't covered."""
    import httpx

    platform = platform_for(url)
    endpoint = OEMBED.get(platform)
    if not endpoint:
        return None
    try:
        response = httpx.get(endpoint, params={"url": url, "format": "json"}, timeout=15, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        log.info("oEmbed lookup failed for %s: %s", url, e)
        return None
    caption = (data.get("title") or "").strip()
    if not caption:
        return None
    return ReelMetadata(
        platform=platform,
        url=url,
        title=caption[:120],
        caption=caption,
        uploader=data.get("author_unique_id") or data.get("author_name"),
        thumbnail_url=data.get("thumbnail_url"),
    )


def _cookies_from_env(contents: str) -> Optional[str]:
    """Writes cookies pasted into YTDLP_COOKIES to a private temp file, once."""
    global _cookie_path
    if not contents.strip():
        return None
    if _cookie_path is None or not Path(_cookie_path).exists():
        fd, _cookie_path = tempfile.mkstemp(prefix="tripit-cookies-", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write(contents.replace("\\n", "\n").strip() + "\n")
    return _cookie_path


_cookie_path: Optional[str] = None


def _metadata(info: dict, url: str, platform: str) -> ReelMetadata:
    if info.get("_type") == "playlist" and info.get("entries"):
        first = next((e for e in info["entries"] if e), {})
        info = {**first, **{k: v for k, v in info.items() if v and k != "entries"}}
    return ReelMetadata(
        platform=platform,
        url=info.get("webpage_url") or url,
        title=info.get("title"),
        caption=info.get("description"),
        uploader=info.get("uploader") or info.get("channel"),
        thumbnail_url=info.get("thumbnail"),
        duration_seconds=info.get("duration"),
    )


def extract_audio(video: Path, workdir: Path) -> Optional[Path]:
    out = workdir / "audio.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(out)],
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0 or not out.exists():
        log.info("No audio track extracted: %s", result.stderr.decode(errors="ignore")[:300])
        return None
    return out


def extract_frames(video: Path, workdir: Path, settings: Settings) -> list[tuple[float, Path]]:
    """Sample frames so Claude can read on-screen text (most list reels caption each place on screen)."""
    frames_dir = workdir / "frames"
    frames_dir.mkdir(exist_ok=True)
    interval = settings.frame_interval_seconds
    duration = probe_duration(video)
    if duration and duration / interval > settings.max_frames:
        interval = duration / settings.max_frames

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
            "-vf", f"fps=1/{interval:.3f},scale={settings.frame_width}:-2",
            "-q:v", "4", "-frames:v", str(settings.max_frames),
            str(frames_dir / "frame_%03d.jpg"),
        ],
        capture_output=True,
        timeout=180,
        check=False,
    )
    frames = sorted(frames_dir.glob("frame_*.jpg"))
    return [(i * interval, path) for i, path in enumerate(frames)]


def probe_duration(video: Path) -> Optional[float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        timeout=30,
    )
    try:
        return float(result.stdout.decode().strip())
    except ValueError:
        return None
