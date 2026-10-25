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
    # Edits mix your saved places with ones recommended by travel and food publications, found with Claude's
    # web search (about $10 per 1,000 searches, a few per refresh; edits refresh at most once a day per trip).
    edits_web: bool = True
    edits_web_searches: int = 4
    # Menus: when a place's website has none, read menu photos listed for it on Google Maps. Google's terms
    # may not allow extracting text from its photos, so check them and turn this off if in doubt.
    # Events during a trip (the "What's on" section), from the Ticketmaster Discovery API. A free key from
    # developer.ticketmaster.com; without one the feature stays hidden.
    ticketmaster_api_key: str = ""
    events_radius_km: int = 40
    menu_google_photos: bool = True
    # When the plain fetch finds no menu, open the site in headless Chromium and click through to it. Needs
    # Playwright and Chromium (the Docker image has them); off automatically when they are missing.
    menu_browser: bool = True
    menu_browser_path: str = ""  # a Chromium to use instead of the one Playwright installed
    # Packing lists use weather from Open-Meteo (no key). Its free service is for non-commercial use; a
    # public or paid app needs its commercial plan (set the key and URL below) or another provider.
    # "none" makes lists without weather.
    weather: str = "open-meteo"
    weather_api_key: str = ""
    weather_base_url: str = ""

    # Cost caps. AI pauses for everyone once the month's spend reaches monthly_budget_usd (alerts go to Sentry at
    # 50%, 80% and 100%). Each person also has a daily spend cap and daily limits per feature; the owner skips
    # those. 0 turns a limit off. The owner can change all of these on the Usage page without redeploying.
    monthly_budget_usd: float = 150.0
    user_daily_budget_usd: float = 3.0
    limit_imports_per_day: int = 25
    limit_plans_per_day: int = 15  # AI plans, tidies and suggestions
    limit_concierge_per_day: int = 50
    limit_menus_per_day: int = 20
    limit_bookings_per_day: int = 20
    limit_packing_per_day: int = 10
    limit_edits_per_day: int = 10
    # Claude prices used for the estimates: $ per million tokens, and $ per 1,000 web searches.
    price_input_mtok: float = 4.0
    price_output_mtok: float = 20.0
    price_cache_read_mtok: float = 0.20
    price_cache_write_mtok: float = 5.0
    price_web_search_k: float = 10.0

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
    # Notifications for the native iOS app (Apple Push Notification service). From developer.apple.com →
    # Keys, make a key with "Apple Push Notifications service" ticked: paste the .p8 file's contents, its key ID,
    # your Team ID and the app's bundle ID. Without them, only the web app gets notifications.
    # Error reporting (optional): a Sentry project's DSN. Server errors, the web app's errors and in-app
    # feedback go there. Only account ids are attached, never emails, passwords or saved places.
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    sentry_release: str = ""
    sentry_traces_sample_rate: float = 0.0
    # Accounts: anyone can sign up (with Apple or an email). False makes new accounts need an invite code.
    open_signup: bool = True
    # Features switched off, comma separated: events, concierge, menus, lounges, calendar, chatgpt, booking_needs.
    # The apps hide them and their endpoints answer 404. fly.toml sets the list for the first App Store version.
    features_off: str = ""
    # Sign in with Apple: the app's bundle ID(s), comma separated. Defaults to APNS_TOPIC, which is the bundle ID.
    apple_client_ids: str = ""
    # Optional: a Sign in with Apple key (.p8, its key ID; team defaults to APNS_TEAM_ID), so deleting an account
    # also revokes its Apple sign-in, as Apple asks.
    apple_signin_key: str = ""
    apple_signin_key_id: str = ""
    apple_team_id: str = ""

    apns_key: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_topic: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


def features_off(settings: "Settings") -> set[str]:
    return {f.strip() for f in settings.features_off.split(",") if f.strip()}
