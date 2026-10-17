# TripIt.ai

Share a TikTok or Instagram reel like "best places to eat in NYC" to TripIt. It finds every place mentioned (in the caption, the voiceover *and* the on-screen text), pins them on a map, and turns them into a day-by-day itinerary. No more screenshots and notes apps.

TripIt runs as a **web app you add to your iPhone's Home Screen**, plus an **iOS Shortcut** that puts TripIt in the share sheet. No App Store and no Apple Developer account are needed.

```
TikTok / Instagram ──Share──▶ "TripIt" Shortcut ──POST /v1/jobs──▶ TripIt server (FastAPI, one Docker container)
                                                                    │ yt-dlp: download reel + caption
                                                                    │ ffmpeg: audio + video frames
                                                                    │ faster-whisper: transcript
                                                                    │ Claude: extract places (vision + text)
                                                                    │ Google Places / OpenStreetMap: coordinates
                                                                    │ SQLite: trips, places, itineraries
                                                                    ▼
                                         TripIt web app (served by the same server, add to Home Screen)
                                         Trips · Itinerary (Claude, or offline fallback) · Map pins · Open in Apple/Google Maps
```

## Repo layout

| Path | What |
|---|---|
| `backend/app/` | FastAPI server: imports reels, stores trips, plans itineraries |
| `backend/app/static/` | The web app (plain HTML/CSS/JS, no build step) |
| `ios/` | Optional native SwiftUI app + Share Extension, for when you have an Apple Developer account (builds in CI) |
| `docs/iphone-shortcut.md` | Step-by-step iPhone share-sheet setup |

---

## 1. Run it locally

You need an [Anthropic API key](https://console.anthropic.com).

```bash
cd backend
cp .env.example .env          # fill in ANTHROPIC_API_KEY and APP_API_KEY (openssl rand -hex 32)
docker compose up --build     # then open http://localhost:8080
```

Without Docker (needs `ffmpeg`):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
pytest                        # tests (Claude, downloads and geocoding are mocked)
```

Open the app, enter your `APP_API_KEY`, then paste a reel link with **+**.

## 2. Deploy to Fly.io

Your phone needs to reach the server over HTTPS. [Fly.io](https://fly.io) works from Windows, macOS or Linux. Install `flyctl`, then:

```bash
cd backend
# Edit fly.toml: set `app` to something unique, e.g. tripit-yourname
fly launch --no-deploy --copy-config        # creates the app from fly.toml
fly volumes create tripit_data --size 1 --region iad   # where your trips are stored (same region as fly.toml)
fly secrets set ANTHROPIC_API_KEY=sk-ant-... APP_API_KEY=$(openssl rand -hex 32)
fly deploy
```

Your app is at `https://<app>.fly.dev`. With the default settings the machine stops when idle and starts on the next request, so a personal setup costs a few dollars a month. Run `fly secrets list` to see which secrets are set; Fly won't show the key values, so save `APP_API_KEY` somewhere when you create it.

Other hosts work too, as long as they run the Docker image with a **persistent disk** mounted at `/data`. Free tiers that wipe the disk on restart, like Render's free plan, will lose your trips.

## 3. Set up your iPhone

1. Open `https://<app>.fly.dev` in **Safari**, enter your API key, then tap **Share → Add to Home Screen**.
2. Create the **TripIt** Shortcut so it shows up in the share sheet. **Settings** in the app shows the exact steps with your server address and key ready to copy. They're also in [docs/iphone-shortcut.md](docs/iphone-shortcut.md).
3. In TikTok tap **Share → More (•••) → TripIt**. In Instagram tap the **paper plane → Share to… → TripIt**. Open TripIt about 30–60 seconds later and the places are on the map.

On Android, install the app from Chrome's menu (**Install app**). TripIt then appears in the share sheet automatically, with no shortcut needed.

## Using the app

- **Trips:** places are grouped into one trip per city. Reels about the same city add to the same trip, and duplicates are merged.
- **Places:** places are listed by category with what to order and tips from the reel. A place that couldn't be found on the map has an orange dot; open it and tap **Find** to search again.
- **Itinerary:** **Plan my trip** asks Claude to group places by neighborhood and time of day. If Claude can't be reached, an offline planner groups nearby places instead. Tap **Edit** to reorder stops, or move a place to another day from its page.
- **Map:** pins are colored by category. Filter by day to see that day's route in order.
- **Open in Maps:** each place has buttons for Apple Maps and Google Maps, plus directions. **Share** on a trip sends the list with Google Maps links.

## How a reel becomes places

1. **yt-dlp** downloads the video (≤720p) with its caption and creator, or the images for photo carousels.
2. **ffmpeg** pulls 16 kHz mono audio and samples up to 24 frames.
3. **faster-whisper** transcribes the voiceover with timestamps.
4. **Claude** (`claude-opus-5-5`, structured outputs) reads the frames, caption and transcript, and returns each place with its category, city, neighborhood, what to order, tips and a confidence level. On-screen text in the frames is where most list-style reels name their places.
5. Each place is found on the map with **Google Places** if `GOOGLE_MAPS_API_KEY` is set, otherwise with free **OpenStreetMap search** limited to the destination city.

### Instagram

Instagram blocks most anonymous downloads. Export cookies for instagram.com from a logged-in browser (a "cookies.txt" extension, Netscape format), mount the file into the container and set `YTDLP_COOKIES_FILE`. Use a secondary account. TikTok and YouTube Shorts usually work without cookies.

> Downloading videos may conflict with TikTok's and Instagram's terms of service. TripIt is meant for personal use on your own server.

## Configuration (`backend/.env` or `fly secrets set`)

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Required |
| `APP_API_KEY` | – | Shared secret for the web app and Shortcut. Leave empty only on your own computer |
| `GOOGLE_MAPS_API_KEY` | – | Optional. Better matches for restaurants and shops; enable "Places API (New)" |
| `NOMINATIM_EMAIL` | – | Contact email for OpenStreetMap's geocoder (requested by its usage policy) |
| `DATABASE_PATH` | `data/tripit.db` (`/data/tripit.db` in Docker) | SQLite file |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `CLAUDE_EFFORT` | `medium` | `low` is cheaper and faster |
| `WHISPER_MODEL` | `base` | `small` is more accurate but slower on CPU |
| `YTDLP_COOKIES_FILE` | – | Needed for most Instagram reels |

### Costs

- **Claude:** with Opus and about 24 frames, a reel costs roughly 10–15¢. Planning an itinerary costs a few cents.
- **Hosting:** a few dollars a month on Fly.io with auto-stop.
- **Maps:** OpenStreetMap search and the CARTO map tiles are free for personal use. Google Places has a monthly free allowance.

## API

All `/v1` routes need the `X-API-Key` header when `APP_API_KEY` is set.

| Endpoint | Purpose |
|---|---|
| `POST /v1/jobs` `{url, shared_text?}` | Import a reel (the Shortcut calls this). The link can also be inside `shared_text` |
| `GET /v1/jobs`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/retry` | Import status: `queued → downloading → transcribing → analyzing → done/failed` |
| `GET /v1/trips`, `GET/PATCH/DELETE /v1/trips/{id}` | Trips with their places and source reels |
| `POST /v1/trips/{id}/plan` `{days, start_date?, preferences?}` | Build the itinerary (Claude, with offline fallback) |
| `DELETE /v1/trips/{id}/plan`, `POST /v1/trips/{id}/days/{n}/order` | Clear the itinerary or reorder a day |
| `GET /v1/places`, `PATCH/DELETE /v1/places/{id}`, `POST /v1/places/{id}/locate` | Edit places, move them between days, re-run the map search |
| `GET /share?url=…` | Share target used by Android and the simpler Shortcut variant |

## Native iOS app (optional)

`ios/` has a native SwiftUI version with a real Share Extension and iCloud sync. It compiles in GitHub Actions on every push (no Mac needed). Installing it on a phone requires the Apple Developer Program ($99/year). It uses the same server.
