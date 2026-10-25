"""Runs each step of a TikTok import and prints what TikTok sent back. Run from the backend folder (or /app on the
server): python tiktok_check.py <link> [<link> ...]"""

import json
import re
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app import tiktok  # noqa: E402
from app.media import OEMBED  # noqa: E402


def show(label, value):
    print(f"  {label}: {value}", flush=True)


INTERESTING = {"desc", "text", "title", "caption", "imagePost", "imagePostInfo", "images", "displayImages", "urlList",
               "uniqueId", "imageURL", "itemInfos", "videoData", "authorInfos", "musicInfos", "itemStruct"}


def state_paths(html):
    """Where the embed page keeps its data: the path and a short value for each interesting key."""
    match = re.search(r'<script[^>]+id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return ["no __FRONTITY_CONNECT_STATE__"]
    try:
        state = json.loads(match.group(1))
    except ValueError as e:
        return [f"state isn't JSON: {e}"]
    out = []

    def walk(node, path):
        if len(out) > 60:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in INTERESTING:
                    out.append(f"{path}.{k} = {json.dumps(v, ensure_ascii=False)[:160]}")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node[:3]):
                walk(v, f"{path}[{i}]")

    walk(state, "$")
    return out


def page_summary(html):
    if not html:
        return "nothing"
    scripts = re.findall(r'<script[^>]+id="([^"]+)"', html)
    out = f"{len(html)} chars, script ids {scripts[:8]}"
    match = re.search(r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if match:
        try:
            scope = json.loads(match.group(1)).get("__DEFAULT_SCOPE__") or {}
            out += f", scope keys {list(scope)[:10]}"
            detail = scope.get("webapp.video-detail") or {}
            out += f", video-detail status {detail.get('statusCode')} {detail.get('statusMsg')!r}"
        except ValueError:
            out += ", rehydration data isn't JSON"
    for word in ("imagePost", "photomode", "captcha", "verify", "Access Denied"):
        if word in html:
            out += f", has {word!r}"
    return out


def server_cookies():
    """The TikTok cookies the server would send (only whether there are any is printed)."""
    try:
        from app.config import get_settings
        from app.media import _cookies_from_env

        settings = get_settings()
        return tiktok.cookies_for_tiktok(settings.ytdlp_cookies_file or _cookies_from_env(settings.ytdlp_cookies))
    except Exception as e:  # noqa: BLE001 - settings need secrets that only the server has
        print(f"No server settings here ({type(e).__name__})")
        return {}


COOKIES = server_cookies()
print(f"TikTok cookies configured: {len(COOKIES)} cookies", flush=True)


def check(link):
    print(f"\n=== {link}", flush=True)
    resolved = tiktok.resolve(link)
    show("resolved to", resolved)
    try:
        r = httpx.get(link, headers={"User-Agent": tiktok.BROWSER_UA}, timeout=15, follow_redirects=False)
        show("short link answer", f"{r.status_code} location={r.headers.get('location')}")
    except httpx.HTTPError as e:
        show("short link answer", f"error {e}")
    show("photo post", tiktok.is_photo_post(resolved))
    for page in dict.fromkeys([resolved, resolved.replace("/photo/", "/video/")]):
        html = tiktok._get_page(page, COOKIES)
        show(f"page {page}", page_summary(html))
        item = tiktok.parse_item(html) if html else None
        show("  post data", f"id {item.get('id')}, {len(tiktok.slide_urls(item))} slides, desc {item.get('desc', '')[:80]!r}"
             if item else "not found")
    match = tiktok.ITEM_RE.search(resolved)
    if match:
        for embed_url in (f"https://www.tiktok.com/embed/v2/{match.group(2)}", f"https://www.tiktok.com/player/v1/{match.group(2)}"):
            html = tiktok._get_page(embed_url, COOKIES)
            show(f"embed {embed_url}", page_summary(html))
            if html:
                slides = tiktok.embed_slides(html)
                show("  slides", f"{len(slides)} {[s[:90] for s in slides[:2]]}")
                show("  caption", (tiktok.embed_caption(html) or "")[:100])
                if "embed/v2" in embed_url:
                    for line in state_paths(html):
                        print(f"      {line}", flush=True)
                images = sorted({u.split('?')[0][:110] for u in re.findall(r'https://[^"\'\s<>\\]+\.(?:jpe?g|webp|png|image)[^"\'\s<>\\]*', html.replace("\\u002F", "/"))})
                show("  any images", f"{len(images)} {images[:4]}")
    for candidate in dict.fromkeys([resolved, resolved.replace("/photo/", "/video/"), link]):
        try:
            r = httpx.get(OEMBED["tiktok"], params={"url": candidate, "format": "json"}, timeout=15, follow_redirects=True)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
            if isinstance(body, dict):
                body = {k: (str(v)[:90]) for k, v in body.items() if k in ("title", "author_unique_id", "thumbnail_url", "code", "message")}
            show(f"oEmbed {candidate}", f"{r.status_code} {body}")
        except Exception as e:  # noqa: BLE001
            show(f"oEmbed {candidate}", f"error {e}")
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(resolved, download=False)
        show("yt-dlp", f"ok: {info.get('title', '')[:60]!r}, formats {len(info.get('formats') or [])}")
    except Exception as e:  # noqa: BLE001
        show("yt-dlp", f"error {str(e)[:200]}")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            got = tiktok.download_photo_post(resolved, Path(tmp), cookies=COOKIES)
            show("download_photo_post", f"{len(got[1])} slides, caption {(got[0].caption or '')[:60]!r}, by {got[0].uploader}" if got else "None")
        except Exception:  # noqa: BLE001
            show("download_photo_post", traceback.format_exc()[-300:])


for arg in sys.argv[1:]:
    try:
        check(arg)
    except Exception:  # noqa: BLE001
        print(traceback.format_exc(), flush=True)
