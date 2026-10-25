"""Loads Whisper the way the server does and transcribes a second of silence. Run from /app on the server."""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.config import get_settings  # noqa: E402
from app.transcribe import _get_model, transcribe  # noqa: E402

settings = get_settings()
print(f"model {settings.whisper_model}, device {settings.whisper_device}, compute type {settings.whisper_compute_type}", flush=True)
_get_model(settings)
print("Whisper loaded", flush=True)
with tempfile.TemporaryDirectory() as tmp:
    audio = Path(tmp) / "silence.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "2", str(audio)], check=True)
    print(f"transcript of silence: {transcribe(audio, settings)!r}", flush=True)
