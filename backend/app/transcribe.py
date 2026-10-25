import logging
import threading
from pathlib import Path
from typing import Optional

from .config import Settings

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
load_error: Optional[str] = None  # why the model couldn't load, for the logs and the import's warning


def _get_model(settings: Settings):
    """Loads Whisper once. The image already holds the model, so that copy is tried before the internet, and
    compute types fall back from the configured one (int8) to ones every CPU can run: a shared cloud CPU can
    refuse int8 even though the machine that built the image accepted it."""
    global _model, load_error
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            types = list(dict.fromkeys([settings.whisper_compute_type, "int8_float32", "float32"]))
            errors = []
            for local_only in (True, False):
                for compute_type in types:
                    try:
                        _model = WhisperModel(settings.whisper_model, device=settings.whisper_device,
                                              compute_type=compute_type, local_files_only=local_only)
                        log.info("Loaded Whisper %s (%s%s)", settings.whisper_model, compute_type, ", from the image" if local_only else "")
                        load_error = None
                        return _model
                    except Exception as e:  # noqa: BLE001 - try the next way of loading it
                        errors.append(f"{compute_type}{' local' if local_only else ''}: {type(e).__name__}: {e}"[:200])
            load_error = errors[-1] if errors else "unknown"
            log.error("Couldn't load Whisper: %s", " | ".join(errors))
            raise RuntimeError(f"Whisper didn't load ({load_error})")
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
