from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Shared secret the iOS app sends in the X-API-Key header. Leave empty only for local dev.
    app_api_key: str = ""

    # Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"

    # Transcription (faster-whisper). "base" is a good CPU default; "small" is more accurate.
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Media processing
    max_video_seconds: int = 600
    frame_interval_seconds: float = 2.0
    max_frames: int = 24
    frame_width: int = 768
    # Optional Netscape-format cookies file; Instagram often needs a logged-in session.
    ytdlp_cookies_file: str = ""

    # Jobs
    max_concurrent_jobs: int = 2
    job_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
