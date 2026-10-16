# TripIt.ai

Share a TikTok or Instagram reel like "best places to eat in NYC" to TripIt. It finds every place mentioned (in the caption, the voiceover, *and* the on-screen text), pins them on a map, and turns them into a day-by-day itinerary. No more screenshots and notes apps.

```
TikTok / Instagram ──Share──▶ TripIt Share Extension ──POST /v1/jobs──▶ Backend (FastAPI)
                                     │                                   │ yt-dlp: download reel + caption
                                     ▼                                   │ ffmpeg: audio + frames
                         App Group "pending imports"                     │ faster-whisper: transcript
                                     │                                   │ Claude: extract places (vision + text)
                                     ▼                                   ▼
                TripIt app ◀──────── polls GET /v1/jobs/{id} ◀──── ExtractionResult
                  │  Apple Maps search → coordinates/address (free, no key)
                  │  SwiftData + iCloud sync
                  └─ Trips · Itinerary (Claude or offline) · Map pins · Open in Apple/Google Maps
```

## Repo layout

| Path | What |
|---|---|
| `backend/` | Python FastAPI service: downloads reels, transcribes, asks Claude for places, plans itineraries |
| `ios/` | SwiftUI app (iOS 17+) and Share Extension, generated with [XcodeGen](https://github.com/yonaskolb/XcodeGen) |

---

## 1. Run the backend

You need an [Anthropic API key](https://console.anthropic.com).

```bash
cd backend
cp .env.example .env          # fill in ANTHROPIC_API_KEY and APP_API_KEY (openssl rand -hex 32)
docker compose up --build     # http://localhost:8080/health
```

Without Docker (needs `ffmpeg` installed):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
pytest                        # unit tests (Claude and downloads are mocked)
```

Try it:

```bash
curl -X POST localhost:8080/v1/jobs -H "X-API-Key: $APP_API_KEY" -H "Content-Type: application/json" \
     -d '{"url": "https://www.tiktok.com/@someone/video/123"}'
curl localhost:8080/v1/jobs/<id> -H "X-API-Key: $APP_API_KEY"
```

### Deploying

Any Docker host works (Fly.io, Render, Railway, a VPS). Give it **at least 1 GB RAM** for Whisper. Set the same env vars as `.env`. Your phone needs to reach it over HTTPS. For testing on the same Wi-Fi you can use `http://<your-mac-ip>:8080`, because local networking is allowed in the app.

Example with Fly.io:

```bash
cd backend
fly launch --no-deploy        # accept the Dockerfile, pick a region
fly secrets set ANTHROPIC_API_KEY=... APP_API_KEY=...
fly scale memory 1024
fly deploy
```

### Instagram

Instagram blocks most anonymous downloads. Export cookies for instagram.com from a logged-in browser (a "cookies.txt" extension, Netscape format), mount the file into the container and set `YTDLP_COOKIES_FILE`. Use a secondary account. TikTok and YouTube Shorts usually work without cookies. If a download fails but the share sheet included the caption text, TikTok usually does, the backend still extracts places from that text.

> Downloading videos may conflict with TikTok's and Instagram's terms of service. This setup is meant for personal use on your own server.

### API

| Endpoint | Purpose |
|---|---|
| `POST /v1/jobs` `{url, shared_text?}` | Start processing a reel (returns a job immediately; the same URL reuses a recent job) |
| `GET /v1/jobs/{id}` | Status: `queued → downloading → transcribing → analyzing → done/failed`, plus places |
| `POST /v1/itineraries` | Plan a day-by-day itinerary from saved places |
| `GET /health` | Health check |

All `/v1` routes require the `X-API-Key` header when `APP_API_KEY` is set.

## 2. Build the iOS app

Requires a Mac with Xcode 16+, and a **paid Apple Developer account** because App Groups and iCloud aren't available to free accounts.

```bash
brew install xcodegen
cd ios
cp Config/Secrets.example.xcconfig Config/Secrets.xcconfig   # team ID, bundle ID, backend URL, API key
xcodegen                                                      # generates TripIt.xcodeproj
open TripIt.xcodeproj
```

In Xcode, select the **TripIt** scheme and your iPhone, then press Run. Automatic signing creates the App Group (`group.<bundle id>`) and iCloud container (`iCloud.<bundle id>`) for you. If it doesn't, add them under *Signing & Capabilities* for both targets.

Re-run `xcodegen` whenever you add or remove Swift files.

### Using it

1. In TikTok, tap **Share → More (…)** and choose **TripIt**. In Instagram, tap **Share** (paper plane) **→ More** and choose **TripIt**. The first time, you may need to tap **More** / **Edit Actions** and enable TripIt.
2. The share sheet confirms and closes. Processing continues on the server, usually in 20–60 s.
3. Open TripIt. New places appear under a trip for that city, pinned on the map. You can also paste links with **+**.
4. In a trip:
   - **Places** lists everything by category.
   - **Itinerary** has **Plan my trip**: pick the number of days and Claude groups places by neighborhood and time of day. If the server is unreachable, an offline plan groups nearby places instead. Drag to reorder, and long-press to move a place between days.
   - **Map** shows pins colored by category, and you can filter by day to see that day's route.
5. On a place, tap **Apple Maps**, **Google Maps** or **Directions**. Google Maps opens in its app when installed, otherwise in the browser. **Share** on a trip exports the list with Google Maps links.

## How place extraction works

1. **yt-dlp** downloads the video (≤720p) along with its caption and creator. For photo carousels it downloads the images.
2. **ffmpeg** pulls 16 kHz mono audio and samples up to 24 frames, roughly one every 2 s.
3. **faster-whisper** transcribes the speech with timestamps. Music-only reels produce no transcript.
4. **Claude** (`claude-opus-5-5`, adaptive thinking, structured outputs) gets the frames, caption and transcript, and returns places with category, city, neighborhood, dishes to try, tips and a confidence level. The model reads on-screen text from the frames, which is where most list-style reels name their places.
5. The app resolves each place with **Apple Maps search** (`MKLocalSearch`) near the destination city to get coordinates, address, phone and website. Places it can't find are flagged and still kept.

Places from multiple reels about the same city merge into one trip, and duplicate places are merged rather than added twice.

## Configuration reference (`backend/.env`)

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Required |
| `APP_API_KEY` | – | Shared secret for the app; leave empty only for local dev |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `CLAUDE_EFFORT` | `medium` | `low` is cheaper/faster, `high` more thorough |
| `WHISPER_MODEL` | `base` | `small` / `medium` are more accurate but slower on CPU |
| `MAX_CONCURRENT_JOBS` | `2` | |
| `YTDLP_COOKIES_FILE` | – | Needed for most Instagram reels |

Jobs are kept in memory for 24 h. If the server restarts, the app automatically resubmits anything still pending.
