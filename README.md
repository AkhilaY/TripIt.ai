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

- **Your travel taste:** a five-question profile (pace, budget, food, interests, mornings) tailors everything below. Start it from the Trips screen or **Settings → Your travel taste**.
- **The Edits:** Claude curates each trip's saved places into editorial lists ("The Date Night Edit", "One Perfect Afternoon in Williamsburg"), shown on the Trips screen and at the top of each trip. Without Claude, simple lists by rule (must-dos, coffee & pastry, after dark) are used instead.
- **Concierge:** a chat tab that knows your saved places, itinerary, taste and the time of day. Ask it to plan an evening or rework a day; it proposes changes and nothing moves until you tap **Apply**.
- **Daily briefing:** the Today view opens with a short briefing for the day: how it starts, what's closed or closing early, what to book, and a tip from your saves.
- **Today:** when a trip has a start date and today falls inside it, Trips opens with a **Today** card. The day view shows the next stop with a big **Directions** button, whether it closes soon ("Closes in 35 min"), the travel time from the last stop, and **Done** to move on to the next one.
- **Offline:** TripIt keeps the trips you open on your phone, with their photos, travel times and the map areas you've looked at, so it works on the subway or abroad without data. Today's trip is saved automatically; use **••• → Save for offline** before you go. Tapping **Done** without signal is saved on the phone and syncs when you're back online.
- **Notifications:** turn on **Settings → Import notifications** to hear when a shared reel's places are saved ("3 new places saved to New York") or when it couldn't be read. On iPhone this works once TripIt is on your Home Screen (iOS 16.4 or later).
- **Add without a reel:** the **+** button takes a TikTok/Instagram/YouTube link, a **Google Maps or Apple Maps link**, or a place name to search for. **Choose screenshots** reads screenshots of a post, map or article and finds the places in them.
- **Trips:** places are grouped into one trip per city. Reels about the same city add to the same trip, and duplicates are merged. A place several reels recommend shows a **🔥 3 reels** badge and is listed first.
- **Places home:** the home screen has a **Trips | Places** switch. **Places** lists every saved place across your trips. Filter by **Starred**, **Food**, **Coffee**, **Drinks**, **Hotels**, **Shopping**, **Sights** and **Activities**, narrow to one trip, and sort by **Most popular** (reels that mention it, then Google's rating), **A to Z**, **Closest to me** (asks for your location; the distance is computed on your phone), **Highest rated** or **Recently saved**. Your choices are remembered.
- **Stars:** tap the star on any place to rank it. Starred places are listed first in every list, whatever the sort, and the planner always fits them in. (This replaces the earlier "must-do" flag.)
- **Places:** places are listed by category with what to order and tips from the reel. A place that couldn't be found on the map has an orange dot; open it and tap **Find** to search again.
- **Itinerary:** **Plan my trip** asks Claude to group places by neighborhood and time of day. If Claude can't be reached, an offline planner groups nearby places instead. Tap **Edit** and drag the handles to reorder stops or move them between days (arrow keys work too). **Build it yourself:** tap **Select** in the Places list (on the home screen or inside a trip), tick places, then **Add to itinerary** and choose a day or a new one; or use **Add places** under any day. No chat needed. **Tidy with AI** then keeps your days as they are, orders each day to cut down on travel, suggests times and follows an optional instruction like "make day 2 more relaxed"; without Claude it orders by time of day and distance. Set an **Exact time** on a place for reservations; the itinerary and calendar use it.
- **Photos:** each place gets pictures. Claude picks the frames or slides of the reel that show the place, Google adds its place photos when you have a server key, and landmarks get a Wikimedia Commons photo. Thumbnails appear in the place list and itinerary; a place's page opens with a swipeable photo strip next to its map, and tapping a photo opens it full screen. Places saved before this feature get Google and Wikimedia photos via **••• → Update hours, photos & ratings**; reel frames are only kept for reels shared from now on.
- **Travel times:** in the itinerary, pick **Walk**, **Transit**, **Drive** or **Bike** to see how long each hop takes, with a day total and a **Directions** link for each leg. Tap **From me** to add travel times from where you are; it asks for location permission the first time. A place's page also shows every mode from your location.
- **Place details:** a place's page lists its Google rating (with a **Read reviews** link to Google Maps), website and phone number, tap to open or call. They come from Google when you have a server key and from OpenStreetMap otherwise. Only plain `http(s)` websites are kept. Places saved earlier get them via **••• → Update hours, photos & ratings**.
- **Menus:** restaurants, cafés, bars and sweet shops have an **Overview | Menu** switch on their page. Tap **Find the menu** and TripIt looks on the place's website (the page, PDF or menu image it links to), lets Claude read it, and saves a neat, sectioned menu with prices and dietary marks, plus a filter for vegetarian, vegan, gluten-free and spicy. If the page's HTML has none (many sites draw their menu with JavaScript) it tries the usual addresses (/menu, /food…) and a menu named in the site's data, then Google Maps menu photos when you have a server Google key, and finally opens the site in a real browser, finds the Menu link or tab, clicks it and reads what appears (page text and screenshots), following any PDF links in a pop-up of menus. When a site lists many menu PDFs, Claude picks the restaurant's main ones (food, lunch, dessert, wine, drinks) and skips private dining, events and festive menus. A place saved without a website gets one looked up first. The server is gentle with each site (one request at a time, a pause between, a retry when told to slow down); some sites still refuse automated visits, so **Add a photo or PDF of the menu** reads a menu you photograph or download yourself, and **Add the restaurant's website** sets the address by hand. When no menu is found, **What we tried** lists each step. Looking costs a few cents of Claude the first time; after that the menu is saved, with a **Refresh** button. Menus can be out of date or misread, so the page says to check with the restaurant. each place shows whether it's open now and its weekly hours. With a start date, the itinerary shows that day's hours and warns when a stop is closed or not open at its planned time (e.g. "Closed on Mondays"). Claude also takes hours into account when planning. Use **••• → Update opening hours** to look them up for places saved earlier.
- **Opening hours:** each place shows whether it's open now and its weekly hours. With a start date, the itinerary shows that day's hours and warns when a stop is closed or not open at its planned time (e.g. "Closed on Mondays"). Claude also takes hours into account when planning. Use **••• → Update hours, photos & ratings** to look them up for places saved earlier.
- **Packing list:** open a trip's **Packing list** (on its page, or **•••**) and TripIt writes one for *this* trip: your planned days and stops, the weather on your dates (a forecast within about two weeks, last year's conditions for the same dates when it's further out), any bookings and your taste profile, with a short reason beside anything that isn't obvious ("Light rain on days 1 and 2", "9 km of walking on day 2"). Tick items off, add your own (they stay when you remake the list), switch on **Carry-on only**, and mark what you **didn't use** after the trip so it's left off next time. Items meant for the bag you carry out show under **Today's bag** on the Today view. Without Claude a basic rule-based list is made. Temperatures show in °F for US English and °C otherwise.
- **Bookings:** each trip has a **Bookings** tab for flights, hotels, table reservations and car rentals, in one timeline with times, addresses and confirmation numbers. Add one from a **screenshot** or **pasted confirmation text** (Claude reads it and shows what it found for you to check before saving, so nothing is saved unseen) or enter it yourself. Times are kept as printed on the booking, in the place's local time. With a trip start date, bookings also appear on their day in the itinerary and in Today. A confirmation number alone can't be looked up with an airline or hotel, so TripIt reads the confirmation itself. Bookings are never included in shared trip links.
- **Reserve:** on a restaurant's page, **Reserve** opens its own page on Resy, OpenTable, Tock or SevenRooms, found by reading links on its website (TripIt doesn't book or see availability). When you come back to the app it asks whether you booked, and saving sets the table's exact time and puts it on that day of your itinerary.
- **Map:** pins are colored by category. Filter by day to see that day's route in order.
- **Open in Maps:** each place has buttons for Apple Maps and Google Maps, plus directions.
- **Share & export:** **Share** on a trip creates a read-only link friends can open without the app (they see the map, the itinerary and each place, but not your notes; turn it off any time). It can also send the list as text, add the itinerary to your **Calendar** (needs a start date), or download a **.kml** file to import into Google My Maps.

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
| `PUSH_CONTACT` | app address | `mailto:` or `https:` contact sent to push services with notifications. The notification key is created on first start and kept next to the database |
| `DATABASE_PATH` | `data/tripit.db` (`/data/tripit.db` in Docker) | SQLite file |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `CLAUDE_EFFORT` | `medium` | `low` is cheaper and faster |
| `WEATHER` / `WEATHER_API_KEY` / `WEATHER_BASE_URL` | `open-meteo` | Weather for packing lists. Open-Meteo's free service is for non-commercial use: a public or paid app needs its commercial plan (set the key and base URL) or another provider. `none` makes lists without weather |
| `MENU_BROWSER` / `MENU_BROWSER_PATH` | `true` / – | When a website's menu can't be read from its HTML, open it in headless Chromium and click through to the menu. Needs Playwright and Chromium (the Docker image has both, and the app uses 2 GB of memory for it); switches itself off when they're missing |
| `MENU_GOOGLE_PHOTOS` | `true` | When a website has no menu, read menu photos from Google Maps. Google's terms may not allow extracting text from its photos: check them, and set this to `false` if in doubt |
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

For better map search on restaurants and shops too, enable **Places API (New)** and put a *second* key (no website restriction, API-restricted to **Places API (New)** and **Routes API**) in `GOOGLE_MAPS_API_KEY`. That one stays on the server.

### Real travel times and better opening hours (optional)

Without Google, travel times are estimates from distance (marked "≈"), there are no transit times for short hops, and opening hours come from OpenStreetMap where it has them. For real routes, transit and fuller hours, use a server-side Google key in `GOOGLE_MAPS_API_KEY` with these APIs enabled in Google Cloud:

- **Routes API**: walking, transit, driving and cycling times. Results are cached for days to keep requests low.
- **Places API (New)**: map search, opening hours, ratings and place photos. Photos are fetched through your server each time they're viewed (Google doesn't allow storing them), and each fetch counts as a Place Photo request. Asking for hours puts searches in Google's "Enterprise" tier, which has a smaller free monthly allowance.

Restrict this key by API (Routes API and Places API (New)), not by website, because it's used from the server. If Google refuses the key, TripIt falls back to estimates automatically. **Settings → Travel times** shows which one is active.

### Costs

- **Claude:** with Opus and about 24 frames, a reel costs roughly 10–15¢. Planning an itinerary, curating a trip's edits, a daily briefing (cached per day) or a concierge reply each cost a few cents.
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
| `POST /v1/trips/{id}/add-to-day` `{place_ids, day?}` | Put places at the end of a day (a new day when `day` is omitted) |
| `POST /v1/trips/{id}/tidy` `{instruction?}` | Claude (or an offline fallback) orders and times the days you built |
| `GET /v1/places`, `PATCH/DELETE /v1/places/{id}`, `POST /v1/places/{id}/locate` | Edit places, move them between days, re-run the map search |
| `POST /v1/trips/{id}/move` `{place_id, day, index}` | Drag and drop: put a place at a position in a day (`day` 0 = not scheduled) |
| `POST /v1/places/search` `{query, trip_id?}`, `POST /v1/places` `{candidate_id \| name, trip_id?, city?}` | Add a place without a reel |
| `POST /v1/places/from-link` `{url, trip_id?}` | Add the place from a Google Maps or Apple Maps link |
| `POST /v1/jobs/screenshots` `{images: [base64 JPEG], note?}` | Find places in up to 10 screenshots |
| `POST/DELETE /v1/trips/{id}/share`, `GET /s/{token}` | Public read-only link to a trip (`/s/{token}/trip.ics` and `.kml` too) |
| `POST /v1/trips/{id}/export-link?format=ics\|kml` | Short-lived download link for a calendar or Google My Maps file |
| `POST/DELETE /v1/push/subscriptions`, `POST /v1/push/test` | Web Push notifications for finished imports |
| `GET/PUT /v1/profile` | Your travel taste |
| `GET /v1/edits`, `GET/POST /v1/trips/{id}/edits` | Curated edits (POST curates or refreshes them) |
| `POST /v1/concierge` `{trip_id?, messages, local_time?}` | Concierge reply, with places to show and proposed changes |
| `POST /v1/trips/{id}/days/{n}/briefing` `{local_date?, refresh?}` | The daily briefing |
| `GET /share?url=…` | Share target used by Android and the simpler Shortcut variant |

## Native iOS app (optional)

`ios/` has a native SwiftUI version with a real Share Extension and iCloud sync. It compiles in GitHub Actions on every push (no Mac needed). Installing it on a phone requires the Apple Developer Program ($99/year). It uses the same server.
