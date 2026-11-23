"""Compares models (and frame counts) for reading posts, on recent real saves, before switching the server's default.

Run on the server from /app: python model_check.py [how many posts] [arm ...], an arm being model:frames, e.g.
claude-opus-5-5:24 claude-haiku-5-5:12. The first arm is the baseline. For each post it downloads once, then asks
each arm for the places and prints how many it found, how many of the baseline's it also found, and what it cost.
Only counts and costs are printed, never links or place names (this repository's logs are public). Nothing is saved.
Costs real money: roughly the posts times each arm's cost per save (about $5 for 20 posts and the default arms). Run in the background; it writes as it goes.
"""
import asyncio
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app.llm import ClaudeService  # noqa: E402
from app.media import download_reel, extract_audio, extract_frames  # noqa: E402
from app.transcribe import transcribe  # noqa: E402
from app.usage import MODEL_PRICES  # noqa: E402

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 20
ARMS = [(a.split(":")[0], int(a.split(":")[1])) for a in sys.argv[2:]] or [
    ("claude-opus-5-5", 24), ("claude-opus-5-5", 12), ("claude-sonnet-5-5", 12), ("claude-haiku-5-5", 12)]


def key(name: str) -> set[str]:
    words = re.sub(r"[^\w\s]", " ", name.casefold()).split()
    return {w for w in words if w not in {"the", "a", "of", "and", "de", "la", "le", "el", "cafe", "café", "restaurant", "bar"}} or set(words)


def same(a: str, b: str) -> bool:
    ka, kb = key(a), key(b)
    return bool(ka and kb) and len(ka & kb) / min(len(ka), len(kb)) >= 0.5


class Meter:
    """Stands in for the usage tracker: adds up what each call cost."""

    def __init__(self):
        self.cost = 0.0

    def check(self, feature):
        pass

    def record(self, feature, usage, model=None):
        p_in, p_out, p_read, p_write = MODEL_PRICES.get(model or "", (4.0, 20.0, 0.2, 5.0))
        u = lambda k: getattr(usage, k, 0) or 0  # noqa: E731
        self.cost += (u("input_tokens") * p_in + u("output_tokens") * p_out
                      + u("cache_read_input_tokens") * p_read + u("cache_creation_input_tokens") * p_write) / 1e6


async def main() -> None:
    logging.disable(logging.CRITICAL)
    sys.stderr = open(os.devnull, "w")
    settings = get_settings()
    db = sqlite3.connect(f"file:{settings.database_path}?mode=ro", uri=True)
    urls = [r[0] for r in db.execute(
        "SELECT url FROM jobs WHERE url NOT LIKE 'upload:%' AND status = 'done' GROUP BY url ORDER BY MAX(created_at) DESC LIMIT ?",
        (COUNT,))]
    print(f"{len(urls)} recent posts; arms: {', '.join(f'{m} {f} frames' for m, f in ARMS)}; baseline {ARMS[0][0]} {ARMS[0][1]}\n", flush=True)
    totals = {arm: {"found": 0, "matched": 0, "cost": 0.0, "secs": 0.0, "errors": 0} for arm in ARMS}
    base_total = 0
    for n, url in enumerate(urls, 1):
        with tempfile.TemporaryDirectory(prefix="model-") as tmp:
            work = Path(tmp)
            try:
                reel = download_reel(url, work, settings)
            except Exception:
                print(f"post {n}: couldn't download, skipped", flush=True)
                continue
            transcript, video_frames = None, []
            if reel.video_path:
                audio = extract_audio(reel.video_path, work)
                transcript = transcribe(audio, settings) if audio else None
                wide = settings.model_copy(update={"max_frames": max(f for _, f in ARMS)})
                video_frames = extract_frames(reel.video_path, work, wide)
            slides = [(f"Slide {i}", p) for i, p in enumerate(reel.image_paths, 1)]
            baseline: list[str] = []
            line = [f"post {n} ({reel.metadata.platform}):"]
            for arm in ARMS:
                model, frames = arm
                # Spread the arm's frames across the video, as extract_frames would with that many.
                step = max(1, len(video_frames) / frames) if video_frames else 1
                picked = [video_frames[int(i * step)] for i in range(min(frames, len(video_frames)))]
                inputs = (slides + [(f"Frame at {s:.0f}s", p) for s, p in picked])[:frames]
                service = ClaudeService(settings.model_copy(update={"import_model": model}))
                service.usage = meter = Meter()
                start = time.monotonic()
                try:
                    result = await service.extract_places(reel.metadata, None, transcript, inputs)
                    names = [p.name for p in result.places]
                except Exception:
                    totals[arm]["errors"] += 1
                    line.append(f"{model.split('-')[1]}{frames}=error")
                    continue
                t = totals[arm]
                t["secs"] += time.monotonic() - start
                t["cost"] += meter.cost
                t["found"] += len(names)
                if arm == ARMS[0]:
                    baseline = names
                    base_total += len(names)
                    t["matched"] += len(names)
                else:
                    t["matched"] += sum(1 for b in baseline if any(same(b, x) for x in names))
                line.append(f"{model.split('-')[1]}{frames}={len(names)} (${meter.cost:.3f})")
            print("  ".join(line), flush=True)
    print("\nArm                         places  found of baseline's  cost/post  secs/post  errors")
    posts = max(1, len(urls))
    for (model, frames), t in totals.items():
        share = t["matched"] / base_total * 100 if base_total else 0
        print(f"{model} {frames:>2} frames   {t['found']:>6}  {t['matched']:>4}/{base_total} ({share:3.0f}%)"
              f"      ${t['cost'] / posts:.3f}     {t['secs'] / posts:5.1f}   {t['errors']}")


if __name__ == "__main__":
    asyncio.run(main())
