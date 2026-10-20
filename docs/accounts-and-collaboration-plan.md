# Accounts and collaboration: implementation plan

Status: proposal, written against the code as of this commit. Estimates are days of focused work for one engineer and are rough (see section 8).

## One-page summary

**Where the code is today.** One SQLite file on one Fly machine. Every route is guarded by the single `require_api_key` dependency (`main.py`), and no table has an owner column. Several functions are global by design: `Database.list_trips()`, `list_places()`, `list_reels()`, `find_trip_by_city()`, `reusable_job(url)`, `Push.send_all()`, and the `settings` row `taste_profile`. The signing secret for photo and export URLs is `APP_API_KEY` itself (`photos.py`, `_export_sig`). The native iOS app is a separate, CloudKit-backed SwiftData app that only calls the server for `/v1/jobs` and `/v1/itineraries`. It does not share a data model with the PWA.

**Recommended path.**

1. **Make the server the single source of truth** for trips, including for the future App Store app. CloudKit-backed SwiftData cannot give Wanderlog-style shared trips across Android/web/iOS. Plan on rewriting the iOS data layer as an API client with a local cache. This is the largest single cost in the plan.
2. **Auth:** Sign in with Apple plus email one-time code. Google is deferred. Server-side opaque sessions: an HttpOnly cookie for the PWA, a Bearer token in the Keychain for iOS. The current owner's data becomes the first account through a one-time "claim" that proves possession of `APP_API_KEY`.
3. **Tenancy:** a `trip_members` table (owner/editor/viewer) from day one, even before collaboration ships. Every query goes through a membership check that returns 404 for non-members.
4. **Meter before you charge:** a usage ledger, hard per-user and global spend caps, and an extraction cache come before IAP. Public signup without these is the biggest financial risk.
5. **Billing:** StoreKit 2 plus RevenueCat for v1, with a local `entitlements` table as the source of truth.
6. **Collaboration:** ship invite links, roles and attribution in 1.0, with simple polling. Add live updates over server-sent events (SSE), votes and an activity feed in 1.1.
7. **Database:** stay on SQLite with Litestream backup through launch. Move to Postgres when you need a second machine or a separate import worker, not before.

**Size:** about 55-90 focused days to App Store launch (phases 1-5), plus 5-8 for live collaboration. Phase 1 alone is roughly 10-15 days.

---

## 1. Goals and non-goals

**Goals:** multiple isolated accounts; shared trips with owner/editor/viewer roles; per-user cost limits and paid entitlements; App Store compliance (Sign in with Apple, account deletion); a PWA and an iOS app that see the same data.

**Non-goals (for now):** character-level co-editing or CRDTs; offline structural edits to shared trips; Android native app; web payments; teams/organizations; moving off Fly.io.

## 2. Auth

| Option | Pros | Cons |
|---|---|---|
| Sign in with Apple | One tap on iOS; no email infrastructure; required if any social login is offered | Name and email are only sent on first sign-in. Email may be a private relay address, so key identity on `sub`, never on email. Web flow in an iOS standalone PWA needs real-device testing (prefer the redirect flow over the popup) |
| Email one-time code (6 digits) | Works for PWA, web and Android; invitees without Apple IDs | Needs a mail provider (Resend, Postmark or SES) and SPF/DKIM/DMARC setup. Use a code, not a magic link: a link opens in Safari, which has separate storage from the installed Home Screen PWA |
| Google | Familiar to Android and web users | Triggers Apple's rule (below); extra OAuth client and consent screen |

**Recommendation:** Sign in with Apple plus email code at launch. Google later if there is Android or web demand.

**Apple's rule (Guideline 4.8):** an app that uses a third-party or social login for its primary account must also offer a login service that limits data to name and email, lets users hide their email, and doesn't track. Sign in with Apple satisfies this. An own-account system such as email code is, to my understanding, exempt. Verify the current wording before submission. App Review also needs a demo login. An emailed code can't work for a reviewer, so add a fixed demo account behind an env flag. Apple also requires account deletion in-app (section 6).

**Sessions and tokens.** No JWTs, because revocation matters. Use opaque random tokens, store only a SHA-256 hash in `sessions`, and roll a 90-day expiry. The same `current_user` dependency reads either:
- **PWA:** `Secure; HttpOnly; SameSite=Lax` cookie. This also lets `EventSource` (SSE) authenticate, since it can't send headers. Because cookies invite CSRF, require a custom header (e.g. `X-TripIt: 1`) plus an `Origin` check on non-GET routes.
- **iOS:** `Authorization: Bearer` with the token in the Keychain, using a shared Keychain access group so the Share Extension can use it. This replaces `AppConfig.apiKey` in plain App Group `UserDefaults`.
- **Verifying Apple:** check the identity token against `https://appleid.apple.com/auth/keys`. The audience is the bundle ID (native) or a Services ID (web). Store Apple's refresh token at sign-in, because revoking the grant on account deletion needs it.

**Migrating the owner and `APP_API_KEY`:**
1. The migration creates a `usr_legacy` user with no identity and assigns all existing rows to it (section 3).
2. `POST /v1/auth/claim` accepts a valid session plus the old `X-API-Key`. It attaches the new account's identity to `usr_legacy`'s row (an `INSERT` into `auth_identities`), so no data is rewritten. It works once.
3. While `LEGACY_API_KEY_ENABLED=true`, `X-API-Key` authenticates as `usr_legacy` only, never as anyone else. This keeps the owner's PWA and the iPhone Shortcut (`docs/iphone-shortcut.md`) working during the cutover. Turn it off and remove the Fly secret afterwards.
4. The Shortcut cannot do OAuth. Replace it with per-user **import tokens**: an `api_tokens` table with a scope that allows only `POST /v1/jobs`.
5. Photo and export signatures move to a new `SIGNING_SECRET`. Do this in Phase 1: today, rotating `APP_API_KEY` would break every photo URL.

## 3. Data model

**New tables**

```sql
CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, display_name TEXT, tz TEXT,
                    created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE auth_identities (provider TEXT NOT NULL, subject TEXT NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    apple_refresh_token TEXT, PRIMARY KEY (provider, subject));
CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, device TEXT, created_at TEXT NOT NULL, last_seen_at TEXT, expires_at TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE email_codes (email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE api_tokens (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    scope TEXT NOT NULL DEFAULT 'import', label TEXT, last_used_at TEXT);
CREATE TABLE trip_members (trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('owner','editor','viewer')),
                    added_by TEXT, created_at TEXT NOT NULL, PRIMARY KEY (trip_id, user_id));
CREATE TABLE trip_invites (id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL, email TEXT, created_by TEXT NOT NULL,
                    expires_at TEXT NOT NULL, max_uses INTEGER NOT NULL DEFAULT 5, used INTEGER NOT NULL DEFAULT 0, revoked_at TEXT);
CREATE TABLE place_user_state (place_id TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE, user_id TEXT NOT NULL,
                    visited INTEGER NOT NULL DEFAULT 0, private_note TEXT NOT NULL DEFAULT '', PRIMARY KEY (place_id, user_id));
CREATE TABLE place_votes (place_id TEXT NOT NULL, user_id TEXT NOT NULL, value INTEGER NOT NULL, PRIMARY KEY (place_id, user_id));  -- optional, phase 6
CREATE TABLE trip_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT NOT NULL, user_id TEXT,
                    type TEXT NOT NULL, entity_id TEXT, payload TEXT, created_at TEXT NOT NULL);  -- activity feed AND sync cursor
CREATE TABLE trip_snapshots (id TEXT PRIMARY KEY, trip_id TEXT NOT NULL, data TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL); -- undo for AI re-plan
CREATE TABLE user_settings (user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (user_id, key));
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
```

**Changed tables**

| Table | Change |
|---|---|
| `trips` | add `owner_id` (billing/deletion convenience; `trip_members` is the authority), `version INTEGER NOT NULL DEFAULT 0`, `updated_at`, `updated_by`. Index `share_token` (currently a full scan) |
| `places` | add `added_by`, `updated_by`, `updated_at`, `deleted_at` (soft delete so offline clients can reconcile), `google_place_id` (today only a name search is stored, so every refresh re-runs a text search). `visited` and `user_notes` become per-member in `place_user_state`; `must_do` stays shared (or becomes votes) |
| `reels` | add `imported_by` |
| `jobs` | add `user_id`, `trip_id_target`. `reusable_job(url)` must be scoped per user, otherwise user B receives user A's job and trip |
| `push_subscriptions` | add `user_id`, `kind` (`webpush`/`apns`), `device_token`. `Push.send_all` becomes `send_to_users([...])`; `/v1/push/test` and `notify_import` currently broadcast to everyone |
| `trip_edits`, `briefings` | add `user_id` to the key. They're generated from one person's taste profile (`Curator.profile()`), so a shared cache would show collaborators each other's tastes |
| `settings` | stays global. `taste_profile` moves to `user_settings`; `Curator.profile()/save_profile()` and `_context()` take a `user_id` |
| `route_cache` | stays global (no user data) |

**Migration mechanism.** `MIGRATIONS` in `db.py` only does `ALTER TABLE ADD COLUMN`. It can't backfill, add constraints, or record what ran. It has a trap: `SCHEMA` runs via `executescript` before `_migrate()`, so an index on a newly added column placed in `SCHEMA` crashes startup on existing databases. Plan:
- Add `schema_migrations` and an ordered list of migration functions, each run in a transaction. Keep the old dict as version 1.
- Create indexes inside migrations, not in `SCHEMA`.
- Migration 2 creates `usr_legacy`, backfills `trip_members` (owner), `owner_id`, `added_by`, `jobs.user_id`, `push_subscriptions.user_id`, and copies the `taste_profile` setting.
- Before migrating, copy the database file (`VACUUM INTO '/data/backups/pre-accounts.db'`) and take a Fly volume snapshot.
- Add `Database.transaction()` using `BEGIN IMMEDIATE`. The connection runs in autocommit with a shared `RLock`, so multi-row operations (`move_to`, `apply_plan`) are not atomic today.

**SQLite or Postgres?** Recommendation: **stay on SQLite through launch**, add Litestream continuous backup (the single volume is a single point of failure), and set `min_machines_running = 1` (a cold start of a few seconds is poor for a paid app and for webhooks). SQLite is not the first bottleneck. The first is CPU: each import runs ffmpeg and Whisper on a `shared-cpu-1x` with 1 GB, throttled by `max_concurrent_jobs=2`. Move to Postgres when any of these happens: you need a second machine (availability, or a separate import worker that must share the database); you see lock waits in p95; or you pass a few thousand active users. Keep that move cheap: use IDs as text (already so), put all SQL behind `Database`, and avoid SQLite-only features in new code. Don't combine the Postgres move with the accounts migration.

## 4. Collaboration

**Permissions**

| Action | Viewer | Editor | Owner |
|---|---|---|---|
| Read trip, map, itinerary, export | yes | yes | yes |
| Mark own visited, private note, vote | yes | yes | yes |
| Add/remove/edit places, move in itinerary, import into trip | no | yes | yes |
| Run AI plan/tidy (destructive, spends quota) | no | yes (confirm) | yes |
| Rename trip | no | yes | yes |
| Invite, change roles, public share link, delete trip | no | no | yes |

Invitees join free: collaboration is the growth loop. AI calls spend the *actor's* quota, not the owner's.

**Invites.** `POST /v1/trips/{id}/invites` returns a link with a 128-bit token, a role and an expiry (store only its hash). `GET /v1/invites/{token}` is a public preview (trip name, inviter). `POST /v1/invites/{token}/accept` requires sign-in. Links first; email-targeted invites reuse the OTP mail provider later. On iOS, Universal Links need `/.well-known/apple-app-site-association` in the static mount. A user who installs the app after tapping a link has to tap it again; plan for that.

**Imports into shared trips.** `save_extraction` creates or reuses a trip by city via the global `find_trip_by_city`. Change it to match only among the importing user's **owned** trips by default, and add an optional `trip_id` to `CreateJobRequest` (picker in the share UI, "last used trip" remembered). Otherwise a Tokyo reel silently lands in a friend's Tokyo trip. New places get `added_by`, a `trip_events` row, and a push to the other members.

**Propagation: three options**

| | Pros | Cons |
|---|---|---|
| ETag polling | Trivial; works with the current service worker; no state | Latency of the poll interval; keeps the machine awake on a timer |
| **SSE** | One-way fits the need (writes already use REST); `EventSource` is built in; works through Fly's proxy | Needs 20-25 s heartbeats; a stream counts against `soft_limit = 50` (switch to `type = "connections"` or raise it); the service worker must bypass the stream |
| WebSockets | Bidirectional, presence | More code than the need justifies |

**Recommendation:** in 1.0, `ETag`/`If-None-Match` on `GET /v1/trips/{id}` with a refetch on focus and a 15-20 s poll while visible. In 1.1, SSE at `GET /v1/trips/{id}/events?since=<seq>` that sends only "trip changed at seq N" and lets the client refetch. `trip_events.seq` is the resume cursor after a dropped connection (iOS suspends background streams). The in-process fan-out (an asyncio queue per subscriber) is valid only while there is **one machine and one uvicorn process**; a second machine needs Postgres `LISTEN/NOTIFY` or Redis. Don't add `--workers`.

**Conflicts.** Don't build CRDTs. What I would do:
- **Scalar fields:** the existing `PATCH /v1/places/{id}` already applies only the fields sent (`model_fields_set`), which is per-field last-write-wins. Keep that, stamp `updated_by`/`updated_at`, and show "edited by".
- **Itinerary order is the real problem.** `Library.move_to` and `reorder_day` read the whole day, then rewrite every sibling's `day_order` one `UPDATE` at a time, and `MoveRequest.index` is relative to what the client saw. Two people dragging in the same day will interleave. Fixes: (1) wrap them in `db.transaction()` (Phase 3); (2) change `MoveRequest` to intent-based `after_place_id` rather than a numeric index; (3) optionally move to fractional ordering (`day_order REAL`, midpoint between neighbours) so a move touches one row.
- **`plan_trip` and `tidy_trip` rewrite everything** (`apply_plan` calls `clear_plan` first). In a shared trip that erases collaborators' manual work. Take a `trip_snapshots` row first, bump `trips.version`, require explicit confirmation, and offer undo.
- **Deletes:** soft-delete places. The PWA's outbox (`flushOutbox`) already tolerates a 404.
- Offline writes stay limited to the existing outbox (visited, notes).

**Voting (optional, Phase 6).** `place_votes` with up/down per member, shown as a count on the place card; `must_do` becomes "most voted". Low effort once membership exists.

## 5. Cost control and entitlements

**Metering.** An append-only `usage_events(id, user_id, trip_id, kind, units, cost_micros, created_at)` with an index on `(user_id, kind, created_at)`. Kinds: `import_reel`, `import_screenshot`, `plan`, `tidy`, `curate`, `briefing`, `concierge`, `place_search`, `details_refresh`. Flow: **reserve** before expensive work, **commit** after, **refund** if the job fails before Claude is called. Record real token usage from Claude responses in `cost_micros`. Run for one to two weeks to learn the real cost per import, then set limits from p95 cost; the numbers below are placeholders.

Endpoints that need a metering check: `POST /v1/jobs`, `/v1/jobs/screenshots`, `/v1/jobs/{id}/retry`, `/v1/concierge`, `/v1/trips/{id}/plan|tidy|edits|refresh-details|days/{d}/briefing`, `/v1/places/search`, `/v1/places`, `/v1/places/from-link`, `/v1/itineraries` (stateless Claude call), `/v1/places/{id}/locate`, and the photo proxy for Google photos.

| | Free | Pro (~$35-40/yr, 7-day trial) | Trip Pass (~$9.99) |
|---|---|---|---|
| Reel imports/month | small (e.g. 5-10) | generous (e.g. 100) | Pro limits on that trip |
| Max video length | shorter (e.g. 3 min vs the global 10) | 10 min | 10 min |
| Concierge/plan/tidy | few per month | high cap | high cap on that trip |
| Google enrichment (hours, rating) | basic | full | full |
| Trips / collaborators | few | unlimited | that trip |
| Concurrent jobs | 1 | 2 | 2 |

**Open definition:** what a Trip Pass is (one trip, forever? 30 days? whose Pro features does it unlock for co-travellers?) isn't specified. I'd model it as a consumable applied to one trip (`trip_passes(trip_id, user_id, transaction_id)`), unlocking Pro limits for *all members, on that trip only*. Owner to confirm.

**Server-side only.** Limits are enforced in the API; the client learns them from `GET /v1/me` (`plan`, `limits`, `usage`). Over-limit calls return `402` with a structured `detail` (`{code:"quota_exceeded", kind, resets_at}`). The current `api.js` reads `detail` as a string, so update it.

**Other levers**
- **Global breaker:** a daily Claude/Google spend ceiling in `settings`; when exceeded, imports queue or fail politely. Also set spend limits in the Anthropic console and quotas plus budget alerts in Google Cloud.
- **Per-user fairness:** `asyncio.Semaphore(max_concurrent_jobs)` is global, so one user's 20 queued imports starve everyone. Add a per-user active-job cap.
- **Extraction cache:** key `jobs.result` by normalized reel URL. A second user importing the same public reel skips download, Whisper and Claude and only runs `save_extraction` for their own trip. This is our derived data, and likely the biggest saving. It still counts against the importer's quota.
- **Model tiering:** `claude_model` is one global. Use a cheaper model for concierge/briefing and keep the strong one for extraction; add prompt caching for the long system prompts. Measure before changing.
- **Free-account farming:** Sign in with Apple accounts are cheap. Keep the free quota small, require a verified identity before any AI call, and consider App Attest.

**Shared Google place cache.** What I understand the Google Maps Platform terms to say (**verify the current terms; I can't confirm them from here**): Place IDs may be stored indefinitely (refresh if old); latitude/longitude may be cached only briefly (I recall 30 days); other Places content such as names, addresses, hours, ratings, phone, website and photos generally may **not** be stored or pre-fetched beyond short-lived caching; photos must be fetched through the API with attribution; Google content shown on a map should be on a Google map.

Two existing issues to raise with whoever reviews the terms: the app already persists hours, ratings and photo references per place (`places.opening_hours`, `rating`, `photos`), and the PWA shows Google-derived pins on Leaflet/OpenStreetMap tiles. The OSM tile servers also have a usage policy that doesn't suit a commercial app at scale.

Design that works under either answer: `place_cache(google_place_id PK, lat, lng, coords_expires_at, details JSON, details_expires_at, fetched_at)`. Default configuration is strict: keep the place ID, and keep coordinates for 30 days. Set `details_expires_at` to "now" (don't reuse) until the owner confirms in writing what's allowed, then raise the TTL per field group. Store `google_place_id` on `places` so a refresh becomes a Place Details-by-ID call with a tight field mask, not a text search. Gate the expensive field groups (hours and ratings sit in a pricier SKU tier today, per the comment on `GooglePlacesGeocoder.FIELDS`) to Pro.

**Payments**

| | Direct StoreKit 2 + App Store Server API | RevenueCat |
|---|---|---|
| Effort | Verify signed JWS transactions (Apple's `app-store-server-library`), handle Server Notifications V2 (renewal, expiry, billing retry/grace, refund), reconcile | SDK plus one webhook; handles receipts, trials, grace |
| Cost/risk | No fee; more edge cases (family sharing, refunds, restore) | Fee tied to revenue above a free tier (I recall about 1% above a monthly threshold; verify); one more dependency |
| Future | Android/web needs more code | Same entitlement model for Stripe and Play |

**Recommendation:** RevenueCat for v1, because a solo engineer has bigger risks elsewhere. Keep an `entitlements(user_id, plan, product_id, original_transaction_id, expires_at, auto_renew, environment, updated_at)` table as the local source of truth, fed by `POST /v1/billing/revenuecat/webhook`, so the vendor can be swapped. Set `appAccountToken` to the user's ID at purchase so transactions map to accounts. Offer the 7-day trial as an introductory offer in App Store Connect (Apple limits it to one per subscription group per Apple ID). Don't sell web subscriptions in v1: Apple's rules on linking out from apps have shifted recently and I'm not certain of the current state. Net revenue: Apple's commission is 30%, or 15% under the Small Business Program or after a subscriber's first year; verify eligibility.

## 6. Security and privacy

**Authorization.** Replace `_trip_or_404` and `_place_or_404` with `require_trip(user, trip_id, min_role)` and `require_place(user, place_id, min_role)` (a join through `trip_members`). Non-members get **404**, not 403. Unscoped `Database` methods get a `user_id` argument or are removed from the request path.

| Endpoints | Check |
|---|---|
| `GET /v1/trips`, `/v1/places`, `/v1/reels`, `/v1/edits`, `/v1/jobs` | filter to the user's memberships/jobs |
| `GET /v1/trips/{id}`, `.../legs`, `.../edits`, `.../briefing`, `export-link`, `/v1/concierge` (when `trip_id` set) | viewer |
| `PATCH /trips/{id}`, `plan`, `DELETE plan`, `days/{d}/order`, `move`, `add-to-day`, `tidy`, `refresh-details`, `POST .../edits` | editor |
| `DELETE /trips/{id}`, `POST/DELETE .../share`, invites, roles | owner |
| `PATCH/DELETE /v1/places/{id}`, `.../locate` | editor via the place's trip |
| `POST /v1/places`, `/from-link`, `/places/search` (`trip_id`) | editor on the target trip |
| **`POST /v1/routes/from`** | takes arbitrary `place_ids` today: verify each is in a trip the user can view |
| `/v1/concierge` without `trip_id` | `_context()` lists all trips: scope to the user's |
| `GET /v1/jobs/{id}`, `retry` | job's `user_id` |
| `/v1/push/*` | per-user; `push/test` must not broadcast |

Add a test that enumerates `app.routes` and fails if any `/v1` route lacks an auth dependency, plus a cross-tenant matrix: for every route, user B on user A's resource gets 404.

**Signed links.** Photo URLs are capability URLs signed over `place/index/ref` with no expiry, and the service worker caches them by URL. Keeping them non-expiring preserves offline caching, but a removed collaborator keeps old URLs until the secret rotates. That seems acceptable for place photos; reel frames are more personal, so expire those or serve them with the session. Export links already carry `exp`; keep that, and move both to `SIGNING_SECRET`. Share tokens (128-bit) are fine; add the index.

**Account deletion (required by App Store).** `DELETE /v1/me`:
- Revoke the Apple grant and sessions, and delete identities, `user_settings`, push subscriptions, API tokens and `place_user_state`.
- Sole-owner trips are deleted, including reel photos (`PhotoStore.delete`) and `uploads/`. Trips with other editors go to the oldest editor, or are deleted if the owner chooses.
- Places the user added to others' trips stay, attributed to "a former member".
- Keep only what's legally needed (purchase records), minimized.
- Tell the user to cancel the subscription in Apple settings; we can't do it.

**Data export:** `GET /v1/me/export` builds a ZIP of JSON (trips, places, notes, profile) asynchronously and returns a signed, expiring link. The existing `.ics`/`.kml` exports stay.

**Privacy disclosures.** Reel content, taste-profile notes (which may mention dietary or family details) and place queries go to Anthropic and Google. The App Privacy label and privacy policy must say so. Write the policy before submission.

**Rate limiting.** None exists. Add an in-process token bucket (valid for one machine) keyed by user, and by `Fly-Client-IP` for anonymous routes. Limits: OTP send 5/hour per email and 20/hour per IP, 5 verify attempts per code, invite accept and share-page hits throttled.

**Reel downloader abuse.** Hosts are already allow-listed in `platform_for`. Add per-user job caps, a plan-based max video length, a download size cap, a cap on frames sent to Claude, and a global kill switch. Business risk: downloading with yt-dlp, and Instagram via the owner's personal cookies (`YTDLP_COOKIES`), is fragile and may breach platform terms; a store listing and paying users raise the stakes. The oEmbed/caption and screenshot paths are the more defensible fallback. Get legal advice.

## 7. Impact on the PWA and iOS

**PWA** (`static/js/api.js`, `pwa.js`, `sw.js`, `app.js`)
- Replace the API-key setup route and `getKey/setKey` with sign-in screens; `fetch` uses `credentials: 'include'` and the CSRF header. The `signout` action (`app.js`) already calls `clearOfflineData()`; extend it.
- **Service worker is a cross-account leak risk.** `DATA` caches `/v1/*` and `/s/*` by URL only, and `networkFirst` serves a cached copy after a 6-second stall, even when online. Fix: namespace cache names by user (the page posts `set-user` after `/v1/me`; the SW keeps it), clear on sign-out *and* on sign-in or a user change, send `Cache-Control: private` and `Vary: Cookie` from the API, and purge all `tripit.*` `localStorage` (chat history in `tripit.chat.*`, `tripit.outbox`, saved markers) on sign-out.
- Bypass the SW for the SSE stream; otherwise its timeout race and `cache.put` break it. Add new JS files to `SHELL_FILES`.
- `/v1/config` currently doubles as a key check; split it into a public config and an authenticated `/v1/me`.

**iOS** (`ios/`)
- `TripIt/Models/Models.swift` uses CloudKit-backed SwiftData with its own `Trip/Place/ReelSource`. Move to a server-backed API client; keep SwiftData as a local cache only and drop the CloudKit/iCloud entitlements. If the native app has no external users yet (verify), skip migrating local data.
- `ImportCoordinator` and the Share Extension: authenticate with the Keychain token; the extension can `POST /v1/jobs` directly instead of queueing in the App Group.
- Push: the current Web Push is PWA-only. Native needs APNs (`aps-environment` is `development` now) and `push_subscriptions.kind = 'apns'`.
- A WKWebView wrapper around the PWA would be faster to build but risks rejection under the minimum-functionality guideline (4.2). I don't recommend relying on it.

## 8. Phases

| # | Phase | Scope | Unblocks | Days |
|---|---|---|---|---|
| 1 | **Accounts and tenancy** | `schema_migrations`, `users/identities/sessions/email_codes`, SIWA + OTP, cookie/Bearer auth, `trip_members` (owners only), scope every `Database` call and route, per-user jobs/push/profile/edits, `usr_legacy` + claim, `SIGNING_SECRET`, PWA sign-in, SW per-user caching, auth rate limits | Any real second user, safely | 10-15 |
| 2 | **Metering and cost control** | `usage_events`, limits, `/v1/me`, 402s, per-user job cap, global breaker, extraction cache, `google_place_id` + `place_cache` (strict) | Public signup without runaway spend | 6-9 |
| 3 | **Sharing** | Invites, roles, attribution columns, `place_user_state`, transactions, `after_place_id` moves, snapshots/undo, ETag, import-into-trip, member push | Collaboration 1.0 | 10-15 |
| 4 | **Billing** | `entitlements`, RevenueCat webhook, Trip Pass, plan gating | Revenue | 5-8 |
| 5 | **iOS client and launch** | Server-backed SwiftUI client, Keychain, StoreKit/RC, APNs, deletion, export, privacy policy and label, demo account, Litestream, `min_machines_running=1`, App Review | App Store 1.0 | 25-40 |
| 6 | **Live collaboration** | SSE + `trip_events` feed, activity UI, votes, presence (optional) | Wanderlog parity | 5-8 |

Phases 1-5 total about 56-87 days, plus 5-8 for phase 6. Phase 5 is the least certain: it depends on how much of the SwiftUI app can be reused and on App Review. Phases 4 and 5 interleave, since IAP can't be tested without the app. Treat these as ranges with perhaps a 30% overrun risk, not commitments.

**Testing.** Phase 1: a cross-tenant matrix over every route; the route-enumeration test; migration tests on a copy of a real production database (row counts before and after, legacy claim works once); manual SIWA and OTP on a real iPhone in the installed PWA. Phase 2: concurrency test (parallel imports cannot exceed quota, via reserve/commit/refund); simulated spend breaker. Phase 3: two clients moving places in the same day concurrently, with a deterministic final order; invite expiry and reuse. Phase 4: StoreKit sandbox and TestFlight, with replayed webhooks (renew, expire, refund, grace). Phase 6: SSE reconnect with `since`, behaviour under the Fly proxy and iOS backgrounding.

## 9. Risks and open questions for the owner

| Question | Recommendation |
|---|---|
| Ship collaboration in 1.0? | Basic (invite link, roles, attribution, polling) yes; live SSE, votes and presence in 1.1 |
| Is collaboration free for invitees and for how many members? | Free to join; limit trip count and AI spend for free owners, not collaborator count |
| What exactly is a Trip Pass? | One trip, applied by the buyer, unlocks Pro limits for all members of that trip |
| Free-tier size | Small and cost-based; set after 1-2 weeks of measured per-import cost |
| Google terms: what may we cache and display? | Verify before launch; default to the strict cache; consider replacing OSM tiles and Leaflet with MapKit on iOS and a licensed tile provider on web |
| TikTok/Instagram scraping risk (cookies, ToS) | Get legal advice; invest in the caption/screenshot fallback; never ship personal cookies as the only path |
| Postgres timing | After launch, when a second machine or a worker is needed |
| Android/web payments | Not in v1; revisit with RevenueCat once iOS is stable |
| Existing CloudKit data from the native app | Probably none from outside users; confirm, then drop |
| Support and moderation (invite abuse, reports) | A report/leave-trip button and an admin script; a minimal admin page later |
