# The Travel Edit

*(This repository is TripIt.ai, the app's working name.)*

Share a TikTok or Instagram reel like "best places to eat in NYC" to TripIt. It finds every place mentioned (in the caption, the voiceover *and* the on-screen text), pins them on a map, and turns them into a day-by-day itinerary. No more screenshots and notes apps.

The Travel Edit runs as a **web app you add to your iPhone's Home Screen**, plus an **iOS Shortcut** that puts The Travel Edit in the share sheet. No App Store and no Apple Developer account are needed.

```
TikTok / Instagram ──Share──▶ "Travel Edit" Shortcut ──POST /v1/jobs──▶ The Travel Edit server (FastAPI, one Docker container)
                                                                    │ yt-dlp: download reel + caption
                                                                    │ ffmpeg: audio + video frames
                                                                    │ faster-whisper: transcript
                                                                    │ Claude: extract places (vision + text)
                                                                    │ Google Places / OpenStreetMap: coordinates
                                                                    │ SQLite: trips, places, itineraries
                                                                    ▼
                                         The Travel Edit web app (served by the same server, add to Home Screen)
                                         Trips · Itinerary (Claude, or offline fallback) · Map pins · Open in Apple/Google Maps
```

## Repo layout

| Path | What |
|---|---|
| `backend/app/` | FastAPI server: imports reels, stores trips, plans itineraries |
| `backend/app/static/` | The web app (plain HTML/CSS/JS, no build step) |
| `ios/` | Native SwiftUI iOS app with a Share Extension, for TestFlight and the App Store (builds in CI) |
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

## Backups

Everything lives in one SQLite file and a folder of photos on the server's disk. With backups on:
- **Database:** [Litestream](https://litestream.io) streams every change to a Cloudflare R2 bucket (within about 10 seconds). It keeps 30 days of history.
- **Files:** photos and keys are copied every 15 minutes, and again when the server stops.
- **Restore:** if the server ever starts on an empty disk (a new or lost volume), it restores itself from the bucket first.
- **Weekly check:** the **Check backups** workflow restores the latest backup, checks it and emails you if anything's wrong. It runs on the default branch.

Setting it up takes about 10 minutes, in a browser, at no cost for a small app (R2's free tier is 10 GB):
1. Sign up at [dash.cloudflare.com](https://dash.cloudflare.com), open **R2 Object Storage** and create a bucket, e.g. `travel-edit-backups`. Leave its location on Automatic.
2. In R2, open **Manage API tokens** → **Create API token**:
   - **Permissions:** **Object Read & Write**.
   - **Scope:** this bucket only.
   - Copy the **Access Key ID**, the **Secret Access Key** and the endpoint, `https://<account id>.r2.cloudflarestorage.com`.
3. Add four GitHub secrets: `BACKUP_BUCKET` (the bucket name), `BACKUP_ENDPOINT`, `BACKUP_ACCESS_KEY_ID` and `BACKUP_SECRET_ACCESS_KEY`. The next deploy turns backups on.

To restore by hand:
- Delete the volume, or start a new app with an empty one; the server restores on start.
- Or copy the database to your computer with `litestream restore -o tripit.db` and the same settings.

## 3. Set up your iPhone

1. Open `https://<app>.fly.dev` in **Safari**, sign in (or create your account; see [Accounts](#accounts)), then tap **Share → Add to Home Screen**.
2. Create the **Travel Edit** Shortcut so it shows up in the share sheet. Your **Profile** in the app (the person button, top right) shows the exact steps with your server address and key ready to copy. They're also in [docs/iphone-shortcut.md](docs/iphone-shortcut.md).
3. In TikTok tap **Share → More (•••) → Travel Edit**. In Instagram tap the **paper plane → Share to… → Travel Edit**. Open The Travel Edit about 30–60 seconds later and the places are on the map.

On Android, install the app from Chrome's menu (**Install app**). The Travel Edit then appears in the share sheet automatically, with no shortcut needed.

## Accounts

The Travel Edit is invite-only. Each person signs in with an email and password and only ever sees their own places, folders, trips, bookings and settings.

- **First account (you):** after deploying, open the app and choose a password, using your server key (`APP_API_KEY`) as the code. Everything saved before accounts existed becomes yours, and you become the owner.
- **Inviting testers:** Profile → **Invite people** makes a one-time code (shown once). They choose **Create account** and enter it.
- **Forgotten passwords:** there's no email yet, so Profile → **People** → *Reset password* gives you a temporary password to pass on. They can change it in their Profile.
- **Share Shortcut:** each person makes their own key in Profile → *Share from TikTok & Instagram* → **Make key**. It can only send links and screenshots. Your existing Shortcut with the server key keeps working, as you.
- **Deleting an account** (Profile, at the bottom) removes it and everything in it. Apple requires this for the App Store.

The server key still works as before until the first account is made, so updating doesn't lock anyone out. The web app signs in with a secure cookie; the iOS app uses `Authorization: Bearer <token>` from `/v1/auth/login`.

## Using the app

- **Your travel taste:** a five-question profile (pace, budget, food, interests, mornings) tailors everything below. Start it from the Library or **Profile → Your travel taste**.
- **The Edits:** magazine-style lists for each trip ("The Date Night Edit", "One Perfect Afternoon in Williamsburg") that mix your saved places in that city with places travel and food publications recommend (Eater, The Infatuation, Time Out, Condé Nast Traveler, the Michelin Guide and others), found with Claude's web search. Every card says where it comes from: the post you saved it from, or the publication with a link to the article. Publications' picks are only kept when they cite an article the search actually returned and can be found on the map, and are marked **New** with a **Save** button. **Save this edit** keeps the whole edit as a folder in your Library, because edits refresh about once a day (in the background, when you open the trip) or when your places change. Web research costs about $10 per 1,000 searches plus Claude tokens, a few searches per refresh; set `EDITS_WEB=false` to use saved places only. Without Claude, simple lists by rule are used instead.
- **Concierge:** a chat tab that knows your saved places, itinerary, taste and the time of day. Ask it to plan an evening or rework a day; it proposes changes and nothing moves until you tap **Apply**.
- **Daily briefing:** the Today view opens with a short briefing for the day: how it starts, what's closed or closing early, what to book, and a tip from your saves.
- **Today:** when a trip has a start date and today falls inside it, Trips opens with a **Today** card. The day view shows the next stop with a big **Directions** button, whether it closes soon ("Closes in 35 min"), the travel time from the last stop, and **Done** to move on to the next one.
- **Offline:** The Travel Edit keeps the trips you open on your phone, with their photos, travel times and the map areas you've looked at, so it works on the subway or abroad without data. Today's trip is saved automatically; use **••• → Save for offline** before you go. Tapping **Done** without signal is saved on the phone and syncs when you're back online.
- **Notifications:** turn on **Profile → Import notifications** to hear when a shared reel's places are saved ("3 new places saved to New York") or when it couldn't be read. On iPhone this works once The Travel Edit is on your Home Screen (iOS 16.4 or later).
- **Add without a reel:** the **+** button takes a TikTok/Instagram/YouTube link, a **Google Maps or Apple Maps link**, or a place name to search for. **Choose screenshots** reads screenshots of a post, map or article and finds the places in them.
- **Trips:** places are grouped into one trip per city. Reels about the same city add to the same trip, and duplicates are merged. A place several reels recommend shows a **🔥 3 reels** badge and is listed first.
- **Places home:** the home screen has a **Trips | Places** switch. **Places** lists every saved place across your trips. Filter by **Starred**, **Food**, **Coffee**, **Drinks**, **Hotels**, **Shopping**, **Sights** and **Activities**, narrow to one trip, and sort by **Most popular** (reels that mention it, then Google's rating), **A to Z**, **Closest to me** (asks for your location; the distance is computed on your phone), **Highest rated** or **Recently saved**. Your choices are remembered.
- **Stars:** tap the star on any place to rank it. Starred places are listed first in every list, whatever the sort, and the planner always fits them in. (This replaces the earlier "must-do" flag.)
- **Places:** places are listed by category with what to order and tips from the reel. A place that couldn't be found on the map has an orange dot; open it and tap **Find** to search again.
- **Itinerary:** **Plan my trip** asks Claude to group places by neighborhood and time of day. If Claude can't be reached, an offline planner groups nearby places instead. Tap **Edit** and drag the handles to reorder stops or move them between days (arrow keys work too). **Build it yourself:** tap **Select** in the Places list (on the home screen or inside a trip), tick places, then **Add to itinerary** and choose a day or a new one; or use **Add places** under any day. No chat needed. **Tidy with AI** then keeps your days as they are, orders each day to cut down on travel, suggests times and follows an optional instruction like "make day 2 more relaxed"; without Claude it orders by time of day and distance. Set an **Exact time** on a place for reservations; the itinerary and calendar use it.
- **Photos:** each place gets pictures. Claude picks the frames or slides of the reel that show the place, Google adds its place photos when you have a server key, and landmarks get a Wikimedia Commons photo. Thumbnails appear in the place list and itinerary; a place's page opens with a swipeable photo strip next to its map, and tapping a photo opens it full screen. Places saved before this feature get Google and Wikimedia photos via **••• → Update hours, photos & ratings**; reel frames are only kept for reels shared from now on.
- **Travel times:** in the itinerary, pick **Walk**, **Transit**, **Drive** or **Bike** to see how long each hop takes, with a day total and a **Directions** link for each leg. Tap **From me** to add travel times from where you are; it asks for location permission the first time. A place's page also shows every mode from your location.
- **Place details:** a place's page lists its Google rating (with a **Read reviews** link to Google Maps), website and phone number, tap to open or call. They come from Google when you have a server key and from OpenStreetMap otherwise. Only plain `http(s)` websites are kept. Places saved earlier get them via **••• → Update hours, photos & ratings**.
- **Menus:** restaurants, cafés, bars and sweet shops have an **Overview | Menu** switch on their page. Tap **Find the menu** and The Travel Edit looks on the place's website (the page, PDF or menu image it links to), lets Claude read it, and saves a neat, sectioned menu with prices and dietary marks, plus a filter for vegetarian, vegan, gluten-free and spicy. If the page's HTML has none (many sites draw their menu with JavaScript) it tries the usual addresses (/menu, /food…) and a menu named in the site's data, then Google Maps menu photos when you have a server Google key, and finally opens the site in a real browser, finds the Menu link or tab, clicks it and reads what appears (page text and screenshots), following any PDF links in a pop-up of menus. When a site lists many menu PDFs, Claude picks the restaurant's main ones (food, lunch, dessert, wine, drinks) and skips private dining, events and festive menus. A place saved without a website gets one looked up first. The server is gentle with each site (one request at a time, a pause between, a retry when told to slow down); some sites still refuse automated visits, so **Add a photo or PDF of the menu** reads a menu you photograph or download yourself, and **Add the restaurant's website** sets the address by hand. When no menu is found, **What we tried** lists each step. Looking costs a few cents of Claude the first time; after that the menu is saved, with a **Refresh** button. Menus can be out of date or misread, so the page says to check with the restaurant. each place shows whether it's open now and its weekly hours. With a start date, the itinerary shows that day's hours and warns when a stop is closed or not open at its planned time (e.g. "Closed on Mondays"). Claude also takes hours into account when planning. Use **••• → Update opening hours** to look them up for places saved earlier.
- **Opening hours:** each place shows whether it's open now and its weekly hours. With a start date, the itinerary shows that day's hours and warns when a stop is closed or not open at its planned time (e.g. "Closed on Mondays"). Claude also takes hours into account when planning. Use **••• → Update hours, photos & ratings** to look them up for places saved earlier.
- **Layout:** five tabs along the bottom (Library, Discover, Map, Bookings, Concierge). Every tab's main screen has the **calendar** at top left (showing today's date, with a dot when something is on today) and your **profile** at top right, where taste, home city, imports, notifications and setup live.
- **Library → Saved:** everything you save, from TikTok, Instagram and YouTube posts, screenshots, map links, searches and Discover, in one list. Saving never creates a trip on its own. Search it, and narrow it with type chips (pick several, e.g. Food + Coffee), Starred, and **More filters** (cities, not in a trip yet); sort by popularity, rating, distance, name or date. **Your folders** sit on top: make as many as you like, name them anything, and put a place in several (a cafe can be in *Brunch* and *Date night*). Select places to add them to a folder or a trip in one go.
- **Library → Trips:** **Plan a new trip** in three short steps: pick the city (cities you've saved in are one tap), name it and choose the number of days (start date optional); choose **Plan it for me** (AI groups your places into days by area and time) or **I'll build it myself** (empty days to fill); then tick places from everything saved or from a folder (places in that city start ticked). With AI you can also let it **suggest places for quiet days**: real, well-known places checked on the map, marked *Suggested*, which you can **Keep** (they join Saved) or remove. A trip page has **Add from saved**, and ••• → *Suggest places for quiet days* any time. A place can be in several trips with different days and times; its star, notes and details are shared.
- **Moving to the Library:** on first start after updating, trips you had planned (with days, dates, bookings, a packing list or a share link) stay as trips. Cities The Travel Edit had made into trips automatically become folders of the same name, so nothing is lost.
- **Events:** reels about pop-ups, brand events, classes (pilates, matcha), networking and social nights, markets and shows are saved as **Events**, with their date, time, end date and venue when the post gives them ("this Saturday" is worked out from the post date). Events have their own filter in Places, a date chip on each row, and a **When** card on their page to set or change the date. Events added from What's on are filed the same way.
- **Calendar:** everything dated in one place: saved events, bookings, planned trip days and trips. A month view with colour-coded dots (events, bookings, plans, trip spans) and an agenda below; filter to Events, Bookings or Plans. A planned trip day folds into one row ("New York plan · 7 stops") that opens that day; multi-day events show once, as Ongoing, rather than every day. Events without a date are listed underneath with **Set date**. Each event or booking has **Add to calendar** (Google Calendar, Apple Calendar, or an .ics file for Outlook and others). **Sync** turns on a private subscription link (Apple Calendar, Google Calendar, or copy the link) so new events keep arriving; Google refreshes subscribed calendars every few hours. The link can be turned off, which stops it working.
- **Airport lounges:** a flight booking with a departure airport shows **Lounges at JFK** (also in its tap menu): each lounge's name, terminal, where it is, typical hours and how to get in (Priority Pass, card access, cabin or status, day-pass price). There's no free lounge data feed, so this is Claude's knowledge, listing only lounges it is confident of, labelled as a guide to check before relying on it. Cached for three days.
- **Discover:** a tab of well-rated places near you, near home or near any trip: restaurants, coffee, bars, dessert and things to do. Candidates come from Google Maps (popular places of that kind, 4.2★ or better with enough reviews), ranked for your taste, with a one-line reason from Claude and **Save** to add one to your places. Where Claude is confident a venue holds a recognition (a Michelin star, Bib Gourmand, a 50 Best listing) it shows a badge, labelled as coming from Claude's knowledge rather than a live feed, so check the Michelin Guide before you go. Michelin has no public data feed and Yelp's terms need checking before it is added, so neither is scraped. Needs `GOOGLE_MAPS_API_KEY`; results are cached for 24 hours. Imports live under Profile → Imports.
- **What's on:** a trip with a start date and a few placed stops gets a **What's on** card: concerts, theatre, sport and more near where you'll be, during your days, from the Ticketmaster Discovery API. Events that fit your taste profile (add **Live music**, **Theatre & comedy** or **Sports** to it) are marked **For you** with a short reason, can be filtered by type, and **Add to Day** saves one as a stop with its venue, time and day. **Tickets** opens Ticketmaster, which sells them; The Travel Edit doesn't. Today shows what's on that evening. Coverage is strongest in North America and parts of Europe, and results are kept for 12 hours to stay within the free daily quota. Needs a free key (see below); without one the card stays hidden.
- **Packing list:** open a trip's **Packing list** (on its page, or **•••**) and The Travel Edit writes one for *this* trip: your planned days and stops, the weather on your dates (a forecast within about two weeks, last year's conditions for the same dates when it's further out), any bookings and your taste profile, with a short reason beside anything that isn't obvious ("Light rain on days 1 and 2", "9 km of walking on day 2"). Tick items off, add your own (they stay when you remake the list), switch on **Carry-on only**, and mark what you **didn't use** after the trip so it's left off next time. Items meant for the bag you carry out show under **Today's bag** on the Today view. Without Claude a basic rule-based list is made. Temperatures show in °F for US English and °C otherwise.
- **Bookings:** a **Bookings** tab in the bottom bar holds every booking across trips (flights, hotels, table reservations and car rentals) in one timeline with times, addresses and confirmation numbers, filterable by type and trip, with past bookings tucked away. Each trip page links to its own bookings. Add one from a **screenshot** or **pasted confirmation text** (Claude reads it and shows what it found for you to check before saving, so nothing is saved unseen) or enter it yourself. Times are kept as printed on the booking, in the place's local time. With a trip start date, bookings also appear on their day in the itinerary and in Today. A confirmation number alone can't be looked up with an airline or hotel, so The Travel Edit reads the confirmation itself. Bookings are never included in shared trip links.
- **Book with ChatGPT:** on a restaurant's page, **Book with ChatGPT** asks for the date, time, guests and any notes (your taste profile's notes are filled in), then opens ChatGPT in a new tab with a message already written: the restaurant, address, phone, website and map link, and a request to find real availability on OpenTable, Resy or Yelp and book it once you confirm. The Travel Edit doesn't book anything itself and nothing is sent until you tap **Open ChatGPT**; you need a ChatGPT account, and ChatGPT's own booking coverage applies. When you return, The Travel Edit asks whether you booked, like the Reserve button.
- **Needs a reservation or tickets:** places in the lists show **Reservation required**, **Book ahead**, **Tickets required** or **Book tickets ahead** where it matters, with a short note on the place's page ("Books out weeks ahead"). Claude judges this once per place from what it knows and any tip in the video; places it can't place are left unmarked, and it's a guide, so check with the venue.
- **Reserve:** on a restaurant's page, **Reserve** opens its own page on Resy, OpenTable, Tock or SevenRooms, found by reading links on its website (The Travel Edit doesn't book or see availability). When you come back to the app it asks whether you booked, and saving sets the table's exact time and puts it on that day of your itinerary.
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

> Downloading videos may conflict with TikTok's and Instagram's terms of service. The Travel Edit is meant for personal use on your own server.

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
| `TICKETMASTER_API_KEY` / `EVENTS_RADIUS_KM` | – / `40` | Free key from developer.ticketmaster.com for What's on (default quota about 5,000 calls a day). Add it as a GitHub secret of the same name. Check Ticketmaster's terms before launching publicly |
| `MENU_GOOGLE_PHOTOS` | `true` | When a website has no menu, read menu photos from Google Maps. Google's terms may not allow extracting text from its photos: check them, and set this to `false` if in doubt |
| `WHISPER_MODEL` | `base` | `small` is more accurate but slower on CPU |
| `APNS_KEY` / `APNS_KEY_ID` / `APNS_TEAM_ID` / `APNS_TOPIC` | – | Notifications for the native iOS app (see [Native iOS app](#native-ios-app-optional)). Add them as GitHub secrets of the same names |
| `BACKUP_BUCKET` / `BACKUP_ENDPOINT` / `BACKUP_ACCESS_KEY_ID` / `BACKUP_SECRET_ACCESS_KEY` | – | Backups to Cloudflare R2 (see [Backups](#backups)). Add them as GitHub secrets of the same names |
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

If Google rejects the key, the app falls back to OpenStreetMap and shows a message. **Profile → Maps in the app** shows which one is active.

For better map search on restaurants and shops too, enable **Places API (New)** and put a *second* key (no website restriction, API-restricted to **Places API (New)** and **Routes API**) in `GOOGLE_MAPS_API_KEY`. That one stays on the server.

### Real travel times and better opening hours (optional)

Without Google, travel times are estimates from distance (marked "≈"), there are no transit times for short hops, and opening hours come from OpenStreetMap where it has them. For real routes, transit and fuller hours, use a server-side Google key in `GOOGLE_MAPS_API_KEY` with these APIs enabled in Google Cloud:

- **Routes API**: walking, transit, driving and cycling times. Results are cached for days to keep requests low.
- **Places API (New)**: map search, opening hours, ratings and place photos. Photos are fetched through your server each time they're viewed (Google doesn't allow storing them), and each fetch counts as a Place Photo request. Asking for hours puts searches in Google's "Enterprise" tier, which has a smaller free monthly allowance.

Restrict this key by API (Routes API and Places API (New)), not by website, because it's used from the server. If Google refuses the key, The Travel Edit falls back to estimates automatically. **Profile → Travel times** shows which one is active.

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
| `GET /v1/places/{id}`, `GET /v1/folders`, `POST /v1/folders`, `PATCH/DELETE /v1/folders/{id}`, `POST /v1/folders/{id}/places`, `DELETE /v1/folders/{id}/places/{place_id}` | One saved place with its posts; folders and what's in them (a place can be in many) |
| `POST /v1/trips`, `POST /v1/trips/{id}/places`, `DELETE /v1/trips/{id}/places/{place_id}`, `POST /v1/trips/{id}/places/{place_id}/keep`, `POST /v1/trips/{id}/suggest` | Make a trip from saved places (AI or by hand, optionally with suggestions), add or remove stops, keep a suggestion, fill quiet days |
| `GET/POST /v1/trips/{id}/edits` (`?wait=true` to block), `POST /v1/trips/{id}/edits/{edit_id}/entries/{entry_id}/save`, `POST /v1/trips/{id}/edits/{edit_id}/bookmark` | Edits (refreshed in the background, poll while `refreshing`), save one of an edit's places, save a whole edit as a folder |
| `GET /v1/auth/status`, `POST /v1/auth/signup`, `/login`, `/logout`, `GET/DELETE /v1/me`, `POST /v1/me/password`, `POST /v1/me/import-key`, `/v1/admin/invites`, `/v1/admin/users` | Accounts: sign up with an invite code, sign in (cookie, or `token` for Bearer), your account, Shortcut key, invites and password resets (owner) |
| `GET /v1/bookings` | Every booking across trips, with its trip's name |
| `GET /v1/calendar`, `POST/DELETE /v1/calendar/feed`, `GET /cal/{token}.ics` | Everything dated (events, bookings, planned stops, trips) with Google and .ics links; the private subscription feed |
| `GET /v1/edits`, `GET/POST /v1/trips/{id}/edits` | Curated edits (POST curates or refreshes them) |
| `POST /v1/concierge` `{trip_id?, messages, local_time?}` | Concierge reply, with places to show and proposed changes |
| `POST /v1/trips/{id}/days/{n}/briefing` `{local_date?, refresh?}` | The daily briefing |
| `GET /share?url=…` | Share target used by Android and the simpler Shortcut variant |

## Native iOS app (optional)

`ios/` is a native SwiftUI app for the same server and account. It has a **Share → Travel Edit** button in the share sheet, so you don't need the Shortcut.

**Native screens:**
- Sign in, or join with an invite.
- **Library:**
  - **Saved**: folders, type chips, cities, search, sort, and multi-select to file places in folders or trips.
  - **Trips**: trip cards, today's trip, and the new-trip flow (AI or by hand).
- **Place pages**:
  - photos, map, hours, open now, reserve, maps and directions;
  - folders and trips, the trip day and time, the event date, notes, and the posts it came from.
- **Trips**:
  - places by kind and the trip's edits;
  - the day-by-day plan: drag to reorder, press and hold to move to another day, and walking, transit or driving times between stops;
  - a map for each day, plus re-plan, tidy, quiet-day suggestions, sharing, and name and dates.
- **The Map tab**: Apple Maps with filters.
- **Add**: paste a reel or a maps link, search for a place, or pick screenshots.
- **Profile**: home city, imports, notifications, password, sign out, and delete account.

**Web screens for now:** Discover, Bookings, Concierge, the calendar, edits, packing lists, events, menus and taste.
- They're the web app's own screens inside native ones. The `?embed=1` mode hides the web tab bar.
- Links to screens the app has natively (a place, a trip, a folder, your profile) open the native screen.
- Changes made there refresh the native lists.
- They can be ported to native one at a time.

**Notifications:** the app registers with Apple's push service. When an import finishes, the server sends "3 new places saved in Lisbon". On the server, set the four `APNS_*` settings, all from your developer account:
- `APNS_KEY`: the contents of a key with **Apple Push Notifications service** ticked, from developer.apple.com → **Keys**. A one-line secret with `\n` for the line breaks is fine.
- `APNS_KEY_ID`: that key's ID.
- `APNS_TEAM_ID`: your Team ID.
- `APNS_TOPIC`: the app's bundle ID.

GitHub Actions compiles the app for the simulator on every push, and the **TestFlight** workflow (below) uploads it to TestFlight.

### Getting it on your phone (TestFlight), no Mac needed

The **TestFlight** workflow builds the app on GitHub's Macs, signs it and uploads it to TestFlight.
- It makes a fresh signing certificate through the App Store Connect API on each run and revokes it afterwards, so there's nothing to keep safe between runs.
- Builds already on TestFlight keep working after their certificate is revoked.

**Once, after Apple approves your Developer Program membership.** Everything is done in a web browser.

1. **Identifiers.** Go to [developer.apple.com/account](https://developer.apple.com/account) → **Certificates, IDs & Profiles** → **Identifiers**, and click **+** for each of these:
   - **App Groups:** `group.com.yourname.tripit`. Use your own reverse domain, the same in all three.
   - **App IDs → App:**
     - Bundle ID `com.yourname.tripit`, described as "The Travel Edit".
     - Tick **App Groups**, then **Configure** and choose the group.
     - Tick **Push Notifications**.
   - **App IDs → App:** bundle ID `com.yourname.tripit.share`, described as "Travel Edit Share". Tick **App Groups** and choose the same group.
2. **API key.** Go to [App Store Connect](https://appstoreconnect.apple.com) → **Users and Access** → **Integrations** → **App Store Connect API** → **Team Keys**, then click **+**.
   - Give it the **Admin** role, which can make signing certificates.
   - Download the `.p8` file. You can only download it once.
   - Note the **Key ID** and the **Issuer ID** shown above the list.
3. **The app.** Go to App Store Connect → **Apps** → **+** → **New App**.
   - Choose iOS, then enter the name **The Travel Edit**. Names must be unique on the App Store; if it's taken, Apple says so here.
   - Choose the bundle ID `com.yourname.tripit` and enter any SKU, e.g. `tripit`.
4. **Secrets.** In this GitHub repository, go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, and add:

   | Secret | Value |
   |---|---|
   | `TRIPIT_TEAM_ID` | Your Team ID (developer.apple.com → **Membership details**) |
   | `TRIPIT_BUNDLE_ID` | `com.yourname.tripit` |
   | `ASC_KEY_ID` | The API key's Key ID |
   | `ASC_ISSUER_ID` | The Issuer ID |
   | `ASC_KEY_P8` | The whole `.p8` file, including the BEGIN and END lines |

   If your server isn't `my-tripit.fly.dev`, also add a repository **variable** `TRIPIT_HOST` with its address.

**Each time you want a new build:**
1. Start the workflow. Put `[testflight]` in a commit message and push it (any branch), or go to **Actions** → **TestFlight** → **Run workflow** once the workflow is on the default branch. It takes about 5–15 minutes. You can also re-run any earlier TestFlight run.
2. Apple then processes the build for 10–30 minutes. It appears under **App Store Connect → your app → TestFlight**.
3. **Testers.** The first time, under TestFlight → **Internal Testing**, click **+** to make a group and add yourself. Up to 100 people on your App Store Connect team can be added there and install builds right away.
   - **External testers** are up to 10,000 people, invited by email or a public link.
   - Each build for external testers needs a short beta review first.
4. On your iPhone, install **TestFlight** from the App Store, accept the invite, and install Travel Edit. New builds arrive automatically.

Each run's build number is the workflow's run number. Raise `MARKETING_VERSION` in `ios/project.yml` for a new version (1.1, 2.0…).

**With a Mac (optional).**
1. Copy `ios/Config/Secrets.example.xcconfig` to `ios/Config/Secrets.xcconfig` and fill it in.
2. Run `brew install xcodegen`, then `cd ios && xcodegen generate && open TripIt.xcodeproj`.
3. Sign in under **Xcode → Settings → Accounts** and run it on your phone. Signing is automatic.

### Before an App Store release

- **Review account.** App Review signs in with a test account. Make one with an invite code and put its email and password in **App Review Information**.
- **Account deletion.** Apple requires a way to delete your account inside the app. It's at the bottom of **Profile** (**Delete account**).
- **Privacy.** You need a privacy policy URL and the **App Privacy** answers. The Travel Edit stores your email, the links you share and the places you save, and it sends reels to Claude and Google for processing. There's no tracking or ads.
- **Screenshots and listing.** You need 6.9" iPhone screenshots, a subtitle, a description and keywords. The App Store name is The Travel Edit; the home screen shows "Travel Edit".
- **Native features.** Apple rejects apps that are "just a website" (guideline 4.2). The Travel Edit's main screens, share button, maps and notifications are native, and the remaining web screens sit inside native navigation.
