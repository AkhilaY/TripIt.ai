"""Compares models (and frame counts) for reading posts, on recent real saves, before changing which one the server
uses. Runs inside the server as an owner-only background task (POST /v1/admin/model-check, then GET it to follow).

For each post it downloads once, then asks each arm for the places and records how many it found, how many of the
first (baseline) arm's it also found, and what it cost. Only counts and costs are kept, never links or place names,
because the GitHub workflow that starts it prints them to a public log. Nothing is saved to the library.
Costs real money: roughly the posts times each arm's cost per save.
"""
import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from .config import Settings
from .db import Database
from .llm import ClaudeService
from .media import download_reel, extract_audio, extract_frames
from .transcribe import transcribe
from .usage import MODEL_PRICES

log = logging.getLogger(__name__)

DEFAULT_ARMS = [("claude-opus-5-5", 24), ("claude-opus-5-5", 12), ("claude-sonnet-5-5", 12), ("claude-haiku-5-5", 12)]
STOP_WORDS = {"the", "a", "of", "and", "de", "la", "le", "el", "cafe", "café", "restaurant", "bar"}


def key(name: str) -> set[str]:
    words = re.sub(r"[^\w\s]", " ", name.casefold()).split()
    return {w for w in words if w not in STOP_WORDS} or set(words)


def same(a: str, b: str) -> bool:
    ka, kb = key(a), key(b)
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.5


def parse_arms(text: Optional[str]) -> list[tuple[str, int]]:
    arms = []
    for part in (text or "").split():
        model, _, frames = part.partition(":")
        if re.fullmatch(r"claude-[a-z0-9-]+", model) and frames.isdigit() and 1 <= int(frames) <= 40:
            arms.append((model, int(frames)))
    return arms or DEFAULT_ARMS


class Meter:
    """Stands in for the usage tracker: adds up what each call cost, and checks nothing."""

    def __init__(self):
        self.cost = 0.0

    def check(self, feature):
        pass

    def record(self, feature, usage, model=None):
        p_in, p_out, p_read, p_write = MODEL_PRICES.get(model or "", (4.0, 20.0, 0.2, 5.0))
        u = lambda k: getattr(usage, k, 0) or 0  # noqa: E731
        self.cost += (u("input_tokens") * p_in + u("output_tokens") * p_out
                      + u("cache_read_input_tokens") * p_read + u("cache_creation_input_tokens") * p_write) / 1e6


async def compare(settings: Settings, db: Database, count: int, arms: list[tuple[str, int]], say) -> None:
    """Runs the comparison, calling say(line) as it goes."""
    urls = [r["url"] for r in db._rows(
        "SELECT url FROM jobs WHERE url NOT LIKE 'upload:%' AND status = 'done' GROUP BY url ORDER BY MAX(created_at) DESC LIMIT ?",
        (count,))]
    say(f"{len(urls)} recent posts; arms: {', '.join(f'{m} {f} frames' for m, f in arms)}; baseline {arms[0][0]} {arms[0][1]}")
    totals = {arm: {"found": 0, "matched": 0, "cost": 0.0, "secs": 0.0, "errors": 0, "posts": 0} for arm in arms}
    base_total = 0
    widest = max(f for _, f in arms)
    for n, url in enumerate(urls, 1):
        with tempfile.TemporaryDirectory(prefix="model-") as tmp:
            work = Path(tmp)
            try:
                reel = await asyncio.to_thread(download_reel, url, work, settings)
            except Exception:
                say(f"post {n}: couldn't download, skipped")
                continue
            transcript, video_frames = None, []
            if reel.video_path:
                try:  # a very long or odd video can time out in ffmpeg; skip it rather than stop the comparison
                    audio = await asyncio.to_thread(extract_audio, reel.video_path, work)
                    transcript = await asyncio.to_thread(transcribe, audio, settings) if audio else None
                    video_frames = await asyncio.to_thread(
                        extract_frames, reel.video_path, work, settings.model_copy(update={"max_frames": widest}))
                except Exception as e:
                    say(f"post {n}: couldn't read the video ({type(e).__name__}), skipped")
                    continue
            slides = [(f"Slide {i}", p) for i, p in enumerate(reel.image_paths, 1)]
            baseline: list[str] = []
            line = [f"post {n} ({reel.metadata.platform}):"]
            for arm in arms:
                model, frames = arm
                step = len(video_frames) / frames if video_frames and len(video_frames) > frames else 1
                picked = [video_frames[int(i * step)] for i in range(min(frames, len(video_frames)))]
                inputs = (slides + [(f"Frame at {s:.0f}s", p) for s, p in picked])[:frames]
                service = ClaudeService(settings.model_copy(update={"import_model": model}))
                service.usage = meter = Meter()
                start = time.monotonic()
                try:
                    result = await service.extract_places(reel.metadata, None, transcript, inputs)
                    names = [p.name for p in result.places]
                except Exception as e:
                    totals[arm]["errors"] += 1
                    line.append(f"{model.split('-')[1]}{frames}=error ({type(e).__name__})")
                    continue
                t = totals[arm]
                t["posts"] += 1
                t["secs"] += time.monotonic() - start
                t["cost"] += meter.cost
                t["found"] += len(names)
                if arm == arms[0]:
                    baseline = names
                    base_total += len(names)
                    t["matched"] += len(names)
                else:
                    t["matched"] += sum(1 for b in baseline if any(same(b, x) for x in names))
                line.append(f"{model.split('-')[1]}{frames}={len(names)} (${meter.cost:.3f})")
            say("  ".join(line))
    say("")
    say("Arm                        places  found of baseline's  cost/post  secs/post  errors")
    for (model, frames), t in totals.items():
        share = t["matched"] / base_total * 100 if base_total else 0
        posts = max(1, t["posts"])
        say(f"{model} {frames:>2} frames  {t['found']:>6}  {t['matched']:>4}/{base_total} ({share:3.0f}%)"
            f"      ${t['cost'] / posts:.3f}    {t['secs'] / posts:5.1f}     {t['errors']}")
