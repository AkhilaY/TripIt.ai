import logging
import threading
from pathlib import Path
from typing import Optional

from .config import Settings

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


def _get_model(settings: Settings):
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model %s", settings.whisper_model)
            _model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
        return _model


def transcribe(audio: Path, settings: Settings) -> Optional[str]:
    """Transcribe speech with timestamps. Returns None when the reel is music-only."""
    model = _get_model(settings)
    segments, info = model.transcribe(str(audio), vad_filter=True, beam_size=5)
    lines = [f"[{seg.start:5.1f}s] {seg.text.strip()}" for seg in segments if seg.text.strip()]
    if not lines:
        return None
    log.info("Transcribed %d segments (language=%s)", len(lines), info.language)
    return "\n".join(lines)
