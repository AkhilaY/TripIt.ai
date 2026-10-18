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

Your phone needs to reach the server over HTTPS. The repo deploys itself to [Fly.io](https://fly.io) from GitHub Actions, so everything happens in the browser, even from a phone.

1. **Create a Fly.io account** at fly.io and add a payment card (needed even for small apps).
2. **Create a Fly token:** in the Fly dashboard go to **Tokens → Create token**. Choose an **Organization** token for your *personal* org, which can create apps. Copy it.
3. **Add GitHub secrets:** in this repo, open **Settings → Secrets and variables → Actions**. On the **Secrets** tab, add:
   - `FLY_API_TOKEN`: the token from step 2
   - `ANTHROPIC_API_KEY`: from console.anthropic.com
   - `APP_API_KEY`: any long random string (e.g. 32+ characters from a password generator). You'll type it into the app and the Shortcut, so save it in your password manager.
   - Optional: `GOOGLE_MAPS_API_KEY`, `NOMINATIM_EMAIL`, `YTDLP_COOKIES` (the full contents of an Instagram cookies.txt)
4. **Add GitHub variables:** on the **Variables** tab, add:
   - `FLY_APP_NAME`: a unique name, e.g. `tripit-yourname`. This becomes `https://tripit-yourname.fly.dev`.
   - Optional: `FLY_REGION`, the [region](https://fly.io/docs/reference/regions/) nearest you (default `iad`, US East). Set it before the first deploy, because the storage volume can't move later.
5. **Deploy:** open **Actions → Deploy to Fly.io → Run workflow**. The first run creates the app and a 1 GB volume for your trips, sets the secrets and deploys, which takes about 5–10 minutes. The run summary shows your app's address.

After that, every push that changes `backend/` redeploys automatically. Updated secrets apply on the next deploy.

The machine stops when idle and starts on the next request (a few seconds), so a personal setup costs a few dollars a month. An import interrupted by a stop resumes automatically.

Prefer the command line? Install `flyctl`, set `app` in `backend/fly.toml`, then from `backend/` run `fly apps create <name>`, `fly volumes create tripit_data --size 1 --region iad`, `fly secrets set ANTHROPIC_API_KEY=… APP_API_KEY=…` and `fly deploy --ha=false`.

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
- **Travel times:** in the itinerary, pick **Walk**, **Transit**, **Drive** or **Bike** to see how long each hop takes, with a day total and a **Directions** link for each leg. Tap **From me** to add travel times from where you are; it asks for location permission the first time. A place's page also shows every mode from your location.
- **Opening hours:** each place shows whether it's open now and its weekly hours. With a start date, the itinerary shows that day's hours and warns when a stop is closed or not open at its planned time (e.g. "Closed on Mondays"). Claude also takes hours into account when planning. Use **••• → Update opening hours** to look them up for places saved earlier.
- **Map:** pins are colored by category. Filter by day to see that day's route in order.
- **Open in Maps:** each place has buttons for Apple Maps and Google Maps, plus directions. **Share** on a trip sends the list with Google Maps links.

## How a reel becomes places

1. **yt-dlp** downloads the video (≤720p) with its caption and creator, or the images for photo carousels.
2. **ffmpeg** pulls 16 kHz mono audio and samples up to 24 frames.
3. **faster-whisper** transcribes the voiceover with timestamps.
4. **Claude** (`claude-opus-5-5`, structured outputs) reads the frames, caption and transcript, and returns each place with its category, city, neighborhood, what to order, tips and a confidence level. On-screen text in the frames is where most list-style reels name their places.
5. Each place is found on the map with **Google Places** if `GOOGLE_MAPS_API_KEY` is set, otherwise with free **OpenStreetMap search** limited to the destination city.

### Instagram

Instagram blocks most anonymous downloads. Export cookies for instagram.com from a logged-in browser (a "cookies.txt" extension, Netscape format), then either paste its contents into the `YTDLP_COOKIES` secret (Fly.io) or mount the file and set `YTDLP_COOKIES_FILE` (Docker). Use a secondary account. TikTok and YouTube Shorts usually work without cookies.

> Downloading videos may conflict with TikTok's and Instagram's terms of service. TripIt is meant for personal use on your own server.

## Configuration (`backend/.env` or `fly secrets set`)

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Required |
| `APP_API_KEY` | – | Shared secret for the web app and Shortcut. Leave empty only on your own computer |
| `GOOGLE_MAPS_API_KEY` | – | Optional, server-side. Enable "Places API (New)" for map search and hours, and "Routes API" for travel times |
| `GOOGLE_MAPS_BROWSER_KEY` | – | Optional. Shows Google Maps inside the app instead of OpenStreetMap (see below) |
| `NOMINATIM_EMAIL` | – | Contact email for OpenStreetMap's geocoder (requested by its usage policy) |
| `DATABASE_PATH` | `data/tripit.db` (`/data/tripit.db` in Docker) | SQLite file |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `CLAUDE_EFFORT` | `medium` | `low` is cheaper and faster |
| `WHISPER_MODEL` | `base` | `small` is more accurate but slower on CPU |
| `YTDLP_COOKIES_FILE` / `YTDLP_COOKIES` | – | Needed for most Instagram reels: a path to cookies.txt, or its contents |

### Google Maps inside the app (optional)

Without a key, the app's maps use free OpenStreetMap tiles. To use Google Maps instead:

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and add a billing account. Personal use should stay within Google's free monthly allowance for map loads.
2. Go to **APIs & Services → Library**, find **Maps JavaScript API** and click **Enable**.
3. Go to **APIs & Services → Credentials → Create credentials → API key**. Open the new key and set:
   - **Application restrictions:** Websites → add `https://my-tripit.fly.dev/*` (your app's address).
   - **API restrictions:** Restrict key → **Maps JavaScript API**.
   This key is visible to browsers, so these restrictions are what keep others from using it.
4. Add it as the GitHub secret `GOOGLE_MAPS_BROWSER_KEY` and redeploy.

If Google rejects the key, the app falls back to OpenStreetMap and shows a message. **Settings → Maps in the app** shows which one is active.

For better map search on restaurants and shops too, enable **Places API (New)** and put a *second* key (no website restriction, API-restricted to Places API (New)) in `GOOGLE_MAPS_API_KEY`. That one stays on the server.

### Real travel times and better opening hours (optional)

Without Google, travel times are estimates from distance (marked "≈"), there are no transit times for short hops, and opening hours come from OpenStreetMap where it has them. For real routes, transit and fuller hours, use a server-side Google key in `GOOGLE_MAPS_API_KEY` with these APIs enabled in Google Cloud:

- **Routes API**: walking, transit, driving and cycling times. Results are cached for days to keep requests low.
- **Places API (New)**: map search plus opening hours. Asking for hours puts searches in Google's "Enterprise" tier, which has a smaller free monthly allowance.

Restrict this key by API (Routes API and Places API (New)), not by website, because it's used from the server. If Google refuses the key, TripIt falls back to estimates automatically. **Settings → Travel times** shows which one is active.

### Costs

- **Claude:** with Opus and about 24 frames, a reel costs roughly 10–15¢. Planning an itinerary costs a few cents.
- **Hosting:** a few dollars a month on Fly.io with auto-stop.
- **Maps:** OpenStreetMap search and map tiles are free for light personal use. Google Places has a monthly free allowance.

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
