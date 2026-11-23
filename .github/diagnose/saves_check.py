"""Re-runs the download step of past imports with today's code, to see which kinds of posts still fail.

Run on the server from /app: python saves_check.py [how many]. Reads the most recent distinct links people have
shared (no screenshots), tries to open each one exactly as an import would (video, photo slides, or the caption
fallback), and prints only the platform, the shape of the link and what happened: never the link itself or who
shared it, since this repository's Actions logs are public. Nothing is saved or changed.
"""
import collections
import hashlib
import re
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as Timeout
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app import instagram  # noqa: E402
from app.media import DownloadFailed, download_reel, fetch_oembed, platform_for  # noqa: E402

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40
PER_LINK = 75  # seconds


def shape(url: str) -> str:
    """'tiktok /video/', 'tiktok short link', 'instagram /reel/' and so on: the kind of link, without its id."""
    p = urlparse(url)
    host = (p.hostname or "").removeprefix("www.").removeprefix("m.")
    parts = [s for s in p.path.split("/") if s]
    if host in ("vm.tiktok.com", "vt.tiktok.com") or (host == "tiktok.com" and parts[:1] == ["t"]):
        return "tiktok short link"
    if host == "youtu.be":
        return "youtube short link"
    kinds = [s for s in parts if s in ("video", "photo", "reel", "reels", "p", "tv", "shorts", "watch", "share", "stories")]
    return f"{host} /{kinds[0]}/" if kinds else f"{host} (other)"


def tag(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:6]


def attempt(url: str, settings) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="check-") as tmp:
        try:
            reel = download_reel(url, Path(tmp), settings)
        except Exception as e:  # noqa: BLE001 (an import falls back to the caption on any download error)
            reason = e.reason if isinstance(e, DownloadFailed) else f"{type(e).__name__}: {e}"
            caption = fetch_oembed(url)
            fallback = "caption only" if caption and (caption.caption or caption.title) else "FAILED"
            return fallback, re.sub(r"https?://\S+", "<link>", reason)[:140]
        if reel.video_path:
            return "video", ""
        if reel.image_paths:
            return f"{len(reel.image_paths)} slides", ""
        return "caption only", "opened, but no video or images"


def embed_check(url: str) -> str:
    """The Instagram backup route on its own (the post's embed page), whatever yt-dlp managed."""
    with tempfile.TemporaryDirectory(prefix="embed-") as tmp:
        got = instagram.download_post(instagram.resolve(url), Path(tmp))
        if not got:
            return "embed: nothing"
        meta, slides, video = got
        return f"embed: {len(slides)} pictures, {'video' if video else 'no video'}, caption {'yes' if meta.caption else 'no'}"


def main() -> None:
    settings = get_settings()
    db = sqlite3.connect(f"file:{settings.database_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT url, MAX(created_at) AS last, "
        "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, COUNT(*) AS tries "
        "FROM jobs WHERE url NOT LIKE 'upload:%' GROUP BY url ORDER BY last DESC LIMIT ?", (LIMIT,)
    ).fetchall()
    print(f"Checking {len(rows)} links shared most recently (each up to {PER_LINK}s)\n", flush=True)
    results = []
    pool = ThreadPoolExecutor(max_workers=1)
    for row in rows:
        url = row["url"]
        start = time.monotonic()
        try:
            outcome, why = pool.submit(attempt, url, settings).result(timeout=PER_LINK)
        except Timeout:
            outcome, why = "FAILED", f"took over {PER_LINK}s"
            pool = ThreadPoolExecutor(max_workers=1)  # leave the stuck one behind
        took = time.monotonic() - start
        before = "failed before" if row["failed"] == row["tries"] else ("failed once" if row["failed"] else "worked before")
        results.append((platform_for(url), shape(url), outcome, why))
        extra = ""
        if platform_for(url) == "instagram":
            try:
                extra = "  | " + pool.submit(embed_check, url).result(timeout=PER_LINK)
            except Exception as e:  # noqa: BLE001
                extra = f"  | embed: {type(e).__name__}"
        print(f"{tag(url)}  {shape(url):28} {outcome:13} {took:5.1f}s  ({before})  {why}{extra}", flush=True)

    print("\nSummary by kind of link")
    by_shape = collections.defaultdict(collections.Counter)
    for _, s, outcome, _ in results:
        by_shape[s]["failed" if outcome == "FAILED" else ("caption" if outcome == "caption only" else "ok")] += 1
    for s, counts in sorted(by_shape.items()):
        total = sum(counts.values())
        print(f"  {s:28} {counts['ok']}/{total} full, {counts['caption']} caption only, {counts['failed']} failed")
    full = sum(1 for _, _, outcome, _ in results if outcome not in ("FAILED", "caption only"))
    print(f"\n  All: {full}/{len(results)} opened fully")
    reasons = collections.Counter(why for _, _, outcome, why in results if outcome != "video" and why)
    if reasons:
        print("\nWhy")
        for why, n in reasons.most_common(12):
            print(f"  {n} × {why}")


if __name__ == "__main__":
    main()
