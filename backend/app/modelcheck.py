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

# model:frames:effort. "hybrid" is Sonnet at that effort, plus Opus (12 frames) on posts that look like long lists,
# with the two sets of places combined.
DEFAULT_ARMS = [("claude-opus-5-5", 24, "medium"), ("claude-sonnet-5-5", 12, "medium"),
                ("claude-sonnet-5-5", 12, "high"), ("hybrid", 12, "high")]
STOP_WORDS = {"the", "a", "of", "and", "de", "la", "le", "el", "cafe", "café", "restaurant", "bar"}


def key(name: str) -> set[str]:
    words = re.sub(r"[^\w\s]", " ", name.casefold()).split()
    return {w for w in words if w not in STOP_WORDS} or set(words)


def same(a: str, b: str) -> bool:
    ka, kb = key(a), key(b)
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.5


def parse_arms(text: Optional[str]) -> list[tuple[str, int, str]]:
    arms = []
    for part in (text or "").split():
        model, _, rest = part.partition(":")
        frames, _, effort = rest.partition(":")
        effort = effort or "medium"
        if (model == "hybrid" or re.fullmatch(r"claude-[a-z0-9-]+", model)) and frames.isdigit() \
                and 1 <= int(frames) <= 40 and effort in ("low", "medium", "high", "xhigh"):
            arms.append((model, int(frames), effort))
    return arms or DEFAULT_ARMS


def looks_like_list(slides: int, caption: Optional[str], found: int) -> bool:
    """A post worth a second, more thorough read: many slides, a numbered or bulleted caption, or many places."""
    listed = sum(1 for line in (caption or "").splitlines() if re.match(r"\s*(\d+[.)]|[-•*📍]|\S+\s*[:–-])", line))
    return slides >= 6 or listed >= 5 or found >= 6


def union(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for name in b:
        if not any(same(name, x) for x in out):
            out.append(name)
    return out


def label(arm: tuple[str, int, str]) -> str:
    model, frames, effort = arm
    short = "hybrid" if model == "hybrid" else model.split("-")[1]
    return f"{short}{frames}{effort[0]}"


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


async def compare(settings: Settings, db: Database, count: int, arms: list[tuple[str, int, str]], say, skip: int = 0) -> None:
    """Runs the comparison, calling say(line) as it goes. Per post: places found, and against the first arm (the
    baseline), how many of its places were missed (-) and how many new ones were found (+). Names are compared,
    never printed."""
    urls = [r["url"] for r in db._rows(
        "SELECT url FROM jobs WHERE url NOT LIKE 'upload:%' AND status = 'done' GROUP BY url ORDER BY MAX(created_at) DESC LIMIT ? OFFSET ?",
        (count, skip))]
    say(f"{len(urls)} recent posts (after skipping {skip}); arms: {', '.join(label(a) for a in arms)}; baseline {label(arms[0])}")
    totals = {arm: {"found": 0, "missed": 0, "extra": 0, "cost": 0.0, "secs": 0.0, "errors": 0, "posts": 0,
                    "missed_posts": 0} for arm in arms}
    base_total = 0
    widest = max(f for _, f, _ in arms)
    for n, url in enumerate(urls, skip + 1):
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
            done: dict[tuple[str, int, str], tuple[list[str], float, float]] = {}

            async def read(model: str, frames: int, effort: str) -> tuple[list[str], float, float]:
                key_ = (model, frames, effort)
                if key_ not in done:
                    step = len(video_frames) / frames if video_frames and len(video_frames) > frames else 1
                    picked = [video_frames[int(i * step)] for i in range(min(frames, len(video_frames)))]
                    inputs = (slides + [(f"Frame at {s:.0f}s", p) for s, p in picked])[:frames]
                    service = ClaudeService(settings.model_copy(update={"import_model": model, "import_effort": effort}))
                    service.usage = meter = Meter()
                    start = time.monotonic()
                    result = await service.extract_places(reel.metadata, None, transcript, inputs)
                    done[key_] = ([p.name for p in result.places], meter.cost, time.monotonic() - start)
                return done[key_]

            baseline: list[str] = []
            line = [f"post {n} ({reel.metadata.platform}):"]
            for arm in arms:
                model, frames, effort = arm
                try:
                    if model == "hybrid":
                        names, cost, secs = await read("claude-sonnet-5-5", frames, effort)
                        if looks_like_list(len(slides), reel.metadata.caption, len(names)):
                            more, cost2, secs2 = await read("claude-opus-5-5", 12, "medium")
                            names, cost, secs = union(names, more), cost + cost2, max(secs, secs2)
                    else:
                        names, cost, secs = await read(model, frames, effort)
                except Exception as e:
                    totals[arm]["errors"] += 1
                    line.append(f"{label(arm)}=error ({type(e).__name__})")
                    continue
                t = totals[arm]
                t["posts"] += 1
                t["secs"] += secs
                t["cost"] += cost
                t["found"] += len(names)
                if arm == arms[0]:
                    baseline = names
                    base_total += len(names)
                    line.append(f"{label(arm)}={len(names)} (${cost:.3f})")
                    continue
                missed = sum(1 for b in baseline if not any(same(b, x) for x in names))
                extra = sum(1 for x in names if not any(same(b, x) for b in baseline))
                t["missed"] += missed
                t["extra"] += extra
                t["missed_posts"] += 1 if missed else 0
                line.append(f"{label(arm)}={len(names)} -{missed} +{extra} (${cost:.3f})")
            say("  ".join(line))
    say("")
    say(f"Baseline {label(arms[0])}: {base_total} places")
    say("Arm           places  missed  new  posts with a miss  cost/post  secs/post  errors")
    for arm, t in totals.items():
        posts = max(1, t["posts"])
        say(f"{label(arm):<12} {t['found']:>6}  {t['missed']:>6}  {t['extra']:>3}  {t['missed_posts']:>5}/{t['posts']:<11}"
            f"  ${t['cost'] / posts:.3f}     {t['secs'] / posts:5.1f}     {t['errors']}")
