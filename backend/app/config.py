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
    # Or paste the cookies.txt contents here (handy as a Fly.io / GitHub secret).
    ytdlp_cookies: str = ""

    # Jobs
    max_concurrent_jobs: int = 2

    # Storage: one SQLite file. Put it on a persistent volume in production.
    database_path: str = "data/tripit.db"
    # Photos saved from reels. Defaults to a "photos" folder next to the database (on the same volume).
    photos_dir: str = ""

    # Geocoding: "auto" uses Google Places when a key is set, otherwise OpenStreetMap (Nominatim).
    geocoder: str = "auto"
    google_maps_api_key: str = ""
    # Separate key for showing Google Maps in the web app. It is sent to browsers, so restrict it in
    # Google Cloud to the Maps JavaScript API and to your app's address (e.g. https://my-tripit.fly.dev/*).
    google_maps_browser_key: str = ""
    # Travel times: "auto" uses Google's Routes API with GOOGLE_MAPS_API_KEY (enable "Routes API" on it),
    # "estimate" always uses distance-based estimates.
    routing: str = "auto"
    # Nominatim asks for a contact address in its usage policy (optional).
    nominatim_email: str = ""
    # Contact sent to push services with notifications (mailto: or https:). Defaults to the app's address.
    push_contact: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
