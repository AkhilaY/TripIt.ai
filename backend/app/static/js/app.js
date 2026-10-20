import { api, ApiError, getKey, isOffline, setKey } from './api.js';
import { enableDrag } from './drag.js';
import { ICON, hydrateIcons } from './icons.js';
import { dayHours, mondayIndex, nextChange, openStatus, slotConflict } from './hours.js';
import { toJpegDataUrl } from './images.js';
import { configureMaps, destroyMaps, mapProvider, renderMap } from './map.js';
import { clearOfflineData, disablePush, enablePush, pushState, registerServiceWorker } from './pwa.js';

// ---------- Constants & helpers ----------

const CATS = {
  food: 'Food', cafe: 'Cafés', dessert: 'Sweets', drinks: 'Drinks', nightlife: 'Nightlife', attraction: 'Sights',
  activity: 'Things to do', nature: 'Outdoors', shopping: 'Shopping', stay: 'Stay', other: 'Other',
};
const CAT_ORDER = Object.keys(CATS);
const TODS = ['morning', 'lunch', 'afternoon', 'dinner', 'evening'];
const ACTIVE = new Set(['queued', 'downloading', 'transcribing', 'analyzing']);

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');
const cvar = (cat) => `--pc: var(--c-${cat})`;
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const $ = (sel, root = document) => root.querySelector(sel);

/** "19:30" → "7:30 PM" */
function fmtClock(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return `${h % 12 || 12}${m ? `:${String(m).padStart(2, '0')}` : ''} ${h < 12 ? 'AM' : 'PM'}`;
}
const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** The trip happening today (by this phone's date), and which day of it: {trip, day} or null. */
function activeTrip(trips) {
  const today = new Date(`${isoDate(new Date())}T12:00:00`);
  for (const t of trips || []) {
    if (!t.start_date || !t.day_count) continue;
    const day = Math.round((today - new Date(`${t.start_date}T12:00:00`)) / 86400000) + 1;
    if (day >= 1 && day <= t.day_count) return { trip: t, day };
  }
  return null;
}

function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function dayDate(start, day) {
  if (!start) return '';
  const d = new Date(`${start}T12:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  d.setDate(d.getDate() + day - 1);
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function mapsLinks(p, trip) {
  const label = [p.resolved_name || p.name, p.address || p.city || (trip && trip.city)].filter(Boolean).join(', ');
  const q = encodeURIComponent(label);
  const hasCoords = p.latitude != null && p.longitude != null;
  return {
    apple: hasCoords
      ? `https://maps.apple.com/?q=${encodeURIComponent(p.resolved_name || p.name)}&ll=${p.latitude},${p.longitude}`
      : `https://maps.apple.com/?q=${q}`,
    google: safeUrl(p.maps_url) || `https://www.google.com/maps/search/?api=1&query=${q}`,
    appleDir: hasCoords ? `https://maps.apple.com/?daddr=${p.latitude},${p.longitude}` : `https://maps.apple.com/?daddr=${q}`,
    googleDir: `https://www.google.com/maps/dir/?api=1&destination=${hasCoords ? `${p.latitude},${p.longitude}` : q}`,
  };
}

// ---------- State & cached data ----------

const S = {
  trips: null,          // list from /v1/trips
  trip: {},             // id -> TripDetail
  places: null,         // all places (map tab)
  jobs: [],             // recent imports
  config: null,
  newIds: new Set(),    // places from imports that finished during this visit
  sheet: null,
  toast: null,
  editDay: false,
  mapDay: {},           // tripId -> day shown on the trip map (0 = all)
  mapTrip: null,        // trip shown on the Map tab ('all' or an id)
  navigations: 0,
  legs: {},             // `${tripId}:${day}:${ids}` -> DayLegs
  here: null,           // {at, provider, times: {placeId: {walk, transit, drive, bike}}}
  scroll: {},
  offline: false,       // showing the copy saved on this phone
  lastNext: {},         // tripId -> place id shown as "Up next" (to animate when it changes)
  profile: null,        // taste profile
  edits: {},            // tripId -> curated edits
  allEdits: null,       // edits across trips, for the home screen
  curating: {},         // tripId -> true while edits are being curated
  curateTried: {},      // tripId -> already auto-curated this visit
  briefing: {},         // `${tripId}:${day}:${date}` -> daily briefing
  chatTrip: undefined,  // trip the concierge is talking about (null = all trips)
  chatBusy: false,
  taste: null,          // onboarding draft: {step, p}
  home: null,           // home filters: {tab, cat, sort, trip, starred}
  sel: { on: false, picked: new Set() }, // multi-select for building an itinerary
  pos: null,            // {at, latitude, longitude} for "closest to me"
};

const view = $('#view');
const overlay = $('#overlay');
const toasts = $('#toasts');

// Screens render straight from what's already loaded and refresh in the background, so switching
// tabs or going back is instant. A refresh re-renders quietly only if something changed.
const fetchedAt = {};
const inflight = {};
const FRESH_MS = 8000;
const once = (key, fn) => inflight[key] || (inflight[key] = fn().finally(() => { delete inflight[key]; }));
const stale = (key, ms = FRESH_MS) => !fetchedAt[key] || Date.now() - fetchedAt[key] > ms;

function revalidate(key, load) {
  if (!stale(key)) return;
  const hash = location.hash;
  load().then(() => { if (location.hash === hash) render({ quiet: true }); }).catch(() => { /* keep showing what we have */ });
}

const loadTrips = () => once('trips', async () => { S.trips = await api('/v1/trips'); fetchedAt.trips = Date.now(); return S.trips; });
const loadTrip = (id) => once(`trip:${id}`, async () => { S.trip[id] = await api(`/v1/trips/${id}`); fetchedAt[`trip:${id}`] = Date.now(); return S.trip[id]; });
const loadPlaces = () => once('places', async () => { S.places = await api('/v1/places'); fetchedAt.places = Date.now(); return S.places; });
const loadJobs = () => once('jobs', async () => { S.jobs = await api('/v1/jobs?limit=40'); fetchedAt.jobs = Date.now(); return S.jobs; });
const loadProfile = () => once('profile', async () => { S.profile = await api('/v1/profile'); fetchedAt.profile = Date.now(); return S.profile; });
const loadEdits = (id) => once(`edits:${id}`, async () => { S.edits[id] = await api(`/v1/trips/${id}/edits`); fetchedAt[`edits:${id}`] = Date.now(); return S.edits[id]; });
const loadAllEdits = () => once('alledits', async () => { S.allEdits = await api('/v1/edits'); fetchedAt.alledits = Date.now(); return S.allEdits; });

/** For extras that shouldn't hold up a screen: returns what's loaded (refreshing it quietly), or starts loading
 * and re-renders once it arrives. */
function background(value, key, load) {
  if (value == null) load().then(() => render({ quiet: true })).catch(() => {});
  else revalidate(key, load);
  return value;
}

function cachedTrips() {
  if (!S.trips) return loadTrips();
  revalidate('trips', loadTrips);
  return S.trips;
}
function cachedTrip(id) {
  if (!S.trip[id]) return loadTrip(id);
  revalidate(`trip:${id}`, () => loadTrip(id));
  return S.trip[id];
}
function cachedPlaces() {
  if (!S.places) return loadPlaces();
  revalidate('places', loadPlaces);
  return S.places;
}

async function findPlace(id) {
  const known = Object.values(S.trip).find((t) => t.places.some((x) => x.id === id));
  if (known) return cachedTrip(known.id);
  const p = (await loadPlaces()).find((x) => x.id === id);
  if (!p) throw new ApiError('This place was deleted.', 404);
  return loadTrip(p.trip_id);
}

const tripPlace = (trip, id) => trip.places.find((p) => p.id === id);
const stops = (trip, day) => trip.places.filter((p) => p.day_number === day).sort((a, b) => a.day_order - b.day_order);
const allPlaces = () => Object.values(S.trip).flatMap((t) => t.places);

// ---------- Routing & page transitions ----------

function route() {
  const hash = location.hash.replace(/^#/, '') || '/';
  const [path, query = ''] = hash.split('?');
  const parts = path.split('/').filter(Boolean);
  const params = new URLSearchParams(query);
  if (!parts.length) return { name: 'trips', params };
  if (parts[0] === 'trip' && parts[1]) return { name: 'trip', id: parts[1], mode: parts[2] || 'places', params };
  if (parts[0] === 'place' && parts[1]) return { name: 'place', id: parts[1], params };
  if (parts[0] === 'today' && parts[1]) return { name: 'today', id: parts[1], params };
  if (parts[0] === 'edit' && parts[1] && parts[2]) return { name: 'edit', id: parts[1], editId: parts[2], params };
  if (['map', 'imports', 'settings', 'setup', 'add', 'concierge', 'taste'].includes(parts[0])) return { name: parts[0], params };
  return { name: 'trips', params };
}

const TAB_FOR = {
  trips: 'trips', trip: 'trips', place: 'trips', today: 'trips', edit: 'trips', map: 'map', concierge: 'concierge',
  imports: 'imports', settings: 'settings', taste: 'settings', add: 'trips',
};
const TAB_INDEX = { trips: 0, map: 1, concierge: 2, imports: 3, settings: 4 };
const DEPTH = { trip: 1, today: 1, taste: 1, edit: 2, place: 2 };
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let renderToken = 0;
let lastKey = '';
let lastRoute = null;
let lastHtml = '';

/** How to animate from one screen to the next: iOS-style push/pop within a tab, a crossfade between tabs. */
function transitionKind(from, to) {
  if (!from || to.name === 'add' || from.name === 'setup' || to.name === 'setup') return 'none';
  if (TAB_FOR[from.name] !== TAB_FOR[to.name]) return 'fade';
  if (from.name === to.name && from.id === to.id) return from.mode !== to.mode ? 'seg' : 'none';
  const a = DEPTH[from.name] || 0;
  const b = DEPTH[to.name] || 0;
  if (b > a) return 'push';
  if (b < a) return 'pop';
  return 'fade';
}

const editing = () => {
  const el = document.activeElement;
  return el && view.contains(el) && el.matches('input, textarea, select');
};

let navigating = 0; // token of a navigation render still loading its data
let quietPending = false; // a background refresh arrived mid-navigation; repaint once it's done

async function render({ quiet = false } = {}) {
  // Background refreshes never cancel a navigation that's still loading, or a field someone is typing in.
  if (quiet && navigating) { quietPending = true; return; }
  if (quiet && editing()) return;
  const r = route();
  const token = ++renderToken;
  const key = location.hash;
  if (!quiet) navigating = token;
  if (!quiet && key !== lastKey) { if (S.sel.keep) S.sel.keep = false; else resetSel(); }
  try {
    await paint(r, token, key, quiet);
  } finally {
    if (navigating === token) {
      navigating = 0;
      if (quietPending) { quietPending = false; setTimeout(() => render({ quiet: true }), 0); }
    }
  }
}

async function paint(r, token, key, quiet) {
  if (lastKey && !quiet) S.scroll[lastKey] = window.scrollY;
  if (!view.firstChild) view.innerHTML = '<div class="loading"><span class="spinner"></span></div>';

  let html;
  let after = () => {};
  try {
    const out = await VIEWS[r.name](r);
    html = typeof out === 'string' ? out : out.html;
    if (out.after) after = out.after;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { location.hash = '#/setup'; return; }
    if (quiet) return;
    html = `${navbar('', {})}<div class="error" role="alert">${esc(e.message || 'Something went wrong')}</div>
      <div class="section"><button class="btn tint" data-act="reload">Try again</button></div>`;
  }
  if (token !== renderToken) return; // a newer render started
  if (quiet && (key !== lastKey || html === lastHtml)) return;

  const kind = quiet ? 'none' : transitionKind(lastRoute, r);
  const thumbs = {};
  view.querySelectorAll('[data-flip]').forEach((el) => { thumbs[el.dataset.flip] = el.style.getPropertyValue('--i'); });
  const scrollTo = key === lastKey ? window.scrollY : (S.scroll[key] || 0);

  const swap = () => {
    const tab = TAB_FOR[r.name];
    const tabbar = $('#tabbar');
    document.querySelectorAll('.tab').forEach((t) => {
      const on = t.dataset.tab === tab;
      t.classList.toggle('on', on);
      if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
    });
    if (tab in TAB_INDEX) tabbar.style.setProperty('--i', TAB_INDEX[tab]);
    tabbar.hidden = r.name === 'setup' || r.name === 'taste';
    const app = $('.app');
    app.classList.toggle('fullbleed', r.name === 'map' || (r.name === 'trip' && r.mode === 'map'));
    app.classList.toggle('notabs', r.name === 'setup' || r.name === 'taste');
    app.classList.toggle('chat', r.name === 'concierge');

    destroyMaps();
    view.innerHTML = html;
    hydrateIcons(view);
    carryThumbs(thumbs);
    window.scrollTo(0, scrollTo);
    updateScroll();
    try {
      const done = after();
      if (done && done.catch) done.catch(() => {});
    } catch (e) { console.warn(e); }
    if (S.focusHandle) {
      const handle = view.querySelector(`[data-drag-id="${S.focusHandle}"] .handle`);
      S.focusHandle = null;
      if (handle) handle.focus({ preventScroll: true });
    }
  };

  lastKey = key;
  lastRoute = r;
  lastHtml = html;
  if (kind !== 'none' && document.startViewTransition && !reducedMotion.matches) {
    const root = document.documentElement;
    root.dataset.vt = kind;
    const vt = document.startViewTransition(swap);
    vt.finished.finally(() => { if (root.dataset.vt === kind) delete root.dataset.vt; });
    await vt.updateCallbackDone.catch(() => {}); // the swap runs a frame later; stay "navigating" until it has
  } else {
    swap();
  }
}

/** Starts each segmented-control thumb where it was on the previous render, so it slides to its new spot. */
function carryThumbs(before) {
  view.querySelectorAll('[data-flip]').forEach((el) => {
    const old = before[el.dataset.flip];
    const now = el.style.getPropertyValue('--i');
    if (old == null || old === '' || old === now) return;
    el.style.setProperty('--i', old);
    el.getBoundingClientRect();
    el.style.setProperty('--i', now);
  });
}

function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

window.addEventListener('hashchange', () => {
  S.navigations++;
  S.editDay = false;
  if (S.sheet) closeSheet(); // e.g. the back gesture while a sheet is up
  render();
});

// Nav bar state: the bar's backdrop fades in once content scrolls under it, and the small title appears
// once the large title (or the place's name) has scrolled away.
let scrollQueued = false;
function updateScroll() {
  scrollQueued = false;
  const nav = view.querySelector('.navbar');
  const navBottom = nav ? nav.getBoundingClientRect().bottom : 0;
  const hero = view.querySelector('.hero');
  const anchor = view.querySelector('[data-anchor]');
  document.body.classList.toggle('scrolled', hero ? hero.getBoundingClientRect().bottom < navBottom : window.scrollY > 4);
  document.body.classList.toggle('past', anchor ? anchor.getBoundingClientRect().bottom < navBottom : true);
}
window.addEventListener('scroll', () => {
  if (!scrollQueued) { scrollQueued = true; requestAnimationFrame(updateScroll); }
}, { passive: true });

// Gallery page dots follow the swipe.
document.addEventListener('scroll', (ev) => {
  const g = ev.target;
  if (!(g instanceof Element) || !g.classList.contains('gallery')) return;
  const i = Math.round(g.scrollLeft / Math.max(1, g.clientWidth));
  g.parentElement.querySelectorAll('.dots i').forEach((d, j) => d.classList.toggle('on', j === i));
}, { capture: true, passive: true });

// Start loading a trip as soon as a finger lands on it.
document.addEventListener('pointerdown', (ev) => {
  const a = ev.target.closest && ev.target.closest('a[href^="#/trip/"]');
  if (!a) return;
  const id = a.getAttribute('href').split('/')[2];
  if (id && !S.trip[id]) loadTrip(id).catch(() => {});
}, { passive: true });

// ---------- Shared pieces ----------

function navbar(title, { back, backLabel, right = '' } = {}) {
  const backHtml = back
    ? `<a class="gbtn" href="${back}" data-act="back" data-fallback="${back}" aria-label="Back to ${esc(backLabel || 'previous screen')}">${ICON.back}</a>`
    : '';
  return `<header class="navbar"><div class="left">${backHtml}</div>
    <div class="title" aria-hidden="true">${esc(title)}</div><div class="right">${right}</div></header>`;
}

const tile = (color, icon, cls = '') => `<span class="tile ${cls}" style="--pc: var(--c-${color})">${ICON[icon] || ICON.other}</span>`;
const catTile = (cat, cls = '') => tile(cat, ICON[cat] ? cat : 'other', cls);
const photoUrl = (photo, width) => `${photo.url}${photo.url.includes('?') ? '&' : '?'}w=${width}`;

function platformOf(reelOrUrl) {
  const s = String(reelOrUrl || '').toLowerCase();
  if (s.startsWith('upload:') || s === 'screenshot') return 'screenshot';
  if (s.includes('tiktok')) return 'tiktok';
  if (s.includes('instagram')) return 'instagram';
  if (s.includes('youtu')) return 'youtube';
  return 'link';
}
const PLATFORM_NAMES = { tiktok: 'TikTok', instagram: 'Instagram', youtube: 'YouTube', screenshot: 'Screenshots' };
const platformName = (p) => PLATFORM_NAMES[String(p || '').toLowerCase()] || cap(p);
function platformTile(platform, cls = '') {
  if (platform === 'tiktok') return `<span class="tile tt ${cls}">${ICON.note}</span>`;
  if (platform === 'instagram') return `<span class="tile ig ${cls}">${ICON.camera}</span>`;
  if (platform === 'youtube') return `<span class="tile ${cls}" style="--pc:#FF0033">${ICON.play}</span>`;
  if (platform === 'screenshot') return tile('pink', 'photo', cls);
  return tile('gray', 'link', cls);
}

/** Photo thumbnail over the category tile, so a missing or failed image still shows something. */
function thumb(p, size = 56) {
  const photo = p.photos && p.photos[0];
  return `<span class="thumb" style="--s:${size}px">${catTile(p.category)}${photo
    ? `<img src="${esc(photoUrl(photo, 240))}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ''}</span>`;
}
const isNew = (p) => (S.newIds.has(p.id) ? '<span class="chip-new">NEW</span>' : '');
const starMark = (p) => (p.must_do ? `<span class="star-inline" title="Starred" aria-label="Starred">${ICON.star}</span>` : '');
const hotChip = (p) => (p.mention_count >= 2 ? `<span class="hot" title="Recommended in ${p.mention_count} saved reels">${ICON.flame}${p.mention_count} reels</span>` : '');
/** Starred places first, then places more reels recommend; otherwise keeps the saved order. */
const byPriority = (a, b) => (b.must_do - a.must_do) || ((b.mention_count || 0) - (a.mention_count || 0));

// ---------- Filters, sorting and starring (home "Places") ----------

/** The chips on the home screen: friendlier groups of the app's categories. */
const GROUPS = [
  { id: 'food', label: 'Food', cats: ['food', 'dessert'] },
  { id: 'coffee', label: 'Coffee', cats: ['cafe'] },
  { id: 'drinks', label: 'Drinks', cats: ['drinks', 'nightlife'] },
  { id: 'stay', label: 'Hotels', cats: ['stay'] },
  { id: 'shopping', label: 'Shopping', cats: ['shopping'] },
  { id: 'sights', label: 'Sights', cats: ['attraction', 'nature'] },
  { id: 'activities', label: 'Activities', cats: ['activity'] },
  { id: 'other', label: 'Other', cats: ['other'] },
];
const GROUP_OF = Object.fromEntries(GROUPS.flatMap((g) => g.cats.map((c) => [c, g.id])));

function meters(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * rad) / 2) ** 2
    + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.sqrt(a));
}
const distanceTo = (p) => (S.pos && p.latitude != null && p.longitude != null ? meters(S.pos.latitude, S.pos.longitude, p.latitude, p.longitude) : Infinity);
const gap = (x, y) => (x === y ? 0 : x - y);

const SORTS = {
  popular: { label: 'Most popular', cmp: (a, b) => (b.mention_count || 0) - (a.mention_count || 0) || (b.rating || 0) - (a.rating || 0) || (b.rating_count || 0) - (a.rating_count || 0) },
  name: { label: 'A to Z', cmp: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) },
  closest: { label: 'Closest to me', cmp: (a, b) => gap(distanceTo(a), distanceTo(b)) },
  rating: { label: 'Highest rated', cmp: (a, b) => (b.rating || 0) - (a.rating || 0) || (b.rating_count || 0) - (a.rating_count || 0) },
  recent: { label: 'Recently saved', cmp: (a, b) => String(b.created_at).localeCompare(String(a.created_at)) },
};

const HOME_KEY = 'tripit.home';
function loadHome() {
  const home = { tab: 'trips', cat: 'all', sort: 'popular', trip: 'all', starred: false };
  try {
    const saved = JSON.parse(localStorage.getItem(HOME_KEY) || '{}');
    if (saved.tab === 'places') home.tab = 'places';
    if (saved.cat === 'all' || GROUPS.some((g) => g.id === saved.cat)) home.cat = saved.cat;
    if (SORTS[saved.sort] && saved.sort !== 'closest') home.sort = saved.sort; // that one needs a fresh location
  } catch { /* private mode or bad data: use the defaults */ }
  return home;
}
function saveHome() {
  try { localStorage.setItem(HOME_KEY, JSON.stringify({ tab: S.home.tab, cat: S.home.cat, sort: S.home.sort })); } catch { /* ignore */ }
}
S.home = loadHome();

/** Starred places always come first; the chosen sort orders each half. */
function sortPlaces(list, sort) {
  const { cmp } = SORTS[sort] || SORTS.popular;
  return [...list].sort((a, b) => (Number(b.must_do) - Number(a.must_do)) || cmp(a, b) || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

async function getPosition() {
  if (S.pos && Date.now() - S.pos.at < 5 * 60 * 1000) return S.pos;
  if (!navigator.geolocation) throw new ApiError('This browser can’t share your location.', 0);
  const pos = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {
    enableHighAccuracy: false, timeout: 15000, maximumAge: 5 * 60 * 1000,
  })).catch((e) => {
    throw new ApiError(e.code === 1
      ? 'Location access is off. Allow it for TripIt in Settings → Privacy & Security → Location Services → Safari Websites.'
      : 'Couldn’t get your location. Try again outside or with Wi-Fi on.', 0);
  });
  S.pos = { at: Date.now(), latitude: pos.coords.latitude, longitude: pos.coords.longitude };
  return S.pos;
}

const fmtCount = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '')}k` : String(n));
const ratingChip = (p) => (p.rating ? `<span class="rating" title="Google rating">${ICON.star}${p.rating.toFixed(1)}${p.rating_count ? `<span class="rc">(${fmtCount(p.rating_count)})</span>` : ''}</span>` : '');
const dayChip = (p) => (p.day_number ? `<span class="daychip">Day ${p.day_number}</span>` : '');
const starButton = (p) => `<button class="starbtn${p.must_do ? ' on' : ''}" data-act="star" data-id="${p.id}" aria-pressed="${!!p.must_do}"
  aria-label="${p.must_do ? 'Remove the star from' : 'Star'} ${esc(p.name)}">${p.must_do ? ICON.star : ICON.starO}</button>`;

// Selecting places to build an itinerary by hand.
const resetSel = () => { S.sel = { on: false, picked: new Set() }; };
const findAnyPlace = (id) => allPlaces().find((x) => x.id === id) || (S.places || []).find((x) => x.id === id);
const selTripId = () => {
  const first = [...S.sel.picked][0];
  const p = first && findAnyPlace(first);
  return p ? p.trip_id : null;
};

function segControl(key, items) {
  const i = Math.max(0, items.findIndex((x) => x.on));
  return `<nav class="seg${key.startsWith('modes') ? ' modes' : ''}" data-flip="${esc(key)}" style="--n:${items.length};--i:${i}">
    <span class="seg-thumb" aria-hidden="true"></span><span class="seg-items">${items.map((x) => x.html).join('')}</span></nav>`;
}

function placeRow(p, { home = false } = {}) {
  const sub = [home ? CATS[p.category] : null, p.neighborhood, p.city].filter(Boolean);
  const dist = home && S.home.sort === 'closest' && S.pos && distanceTo(p) !== Infinity
    ? `<span class="distchip">${fmtDistance(distanceTo(p))} away</span>` : '';
  const body = `${thumb(p, 56)}
    <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${isNew(p)}${p.latitude == null ? ' <span class="flag" title="Not on the map yet">●</span>' : ''}</span>
    <span class="s">${esc(sub.join(' · '))}${ratingChip(p)}${hotChip(p)}${dayChip(p)}${dist}</span>
    ${p.recommended_items.length ? `<span class="s clip">Try: ${esc(p.recommended_items.join(', '))}</span>` : ''}
    ${hoursLine(p)}${hereChip(p)}</span>`;
  if (S.sel.on) {
    const picked = S.sel.picked.has(p.id);
    const tripId = selTripId();
    const blocked = tripId && p.trip_id !== tripId;
    return `<button class="row prow sel${picked ? ' picked' : ''}${blocked ? ' blocked' : ''}" data-act="pick" data-id="${p.id}" aria-pressed="${picked}">
      <span class="check" aria-hidden="true">${picked ? ICON.done : ''}</span>${body}</button>`;
  }
  return `<div class="row prow"><a class="rowlink" href="#/place/${p.id}">${body}</a>${starButton(p)}</div>`;
}

function jobRow(job) {
  const active = ACTIVE.has(job.status);
  const title = active ? (job.message || 'Waiting to process…') : job.status === 'failed' ? (job.message || 'Import failed') : (job.message || 'Done');
  const inner = `${platformTile(platformOf(job.url))}<span class="main"><span class="t" style="font-size:16px${job.status === 'failed' ? ';color:var(--warn)' : ''}">${esc(title)}</span>
    <span class="s clip">${esc(job.url.startsWith('upload:') ? 'Screenshots' : job.url.replace(/^https?:\/\/(www\.)?/, ''))} · ${timeAgo(job.created_at)}</span>
    ${(job.warnings || []).map((w) => `<span class="s" style="color:var(--warn)">${esc(w)}</span>`).join('')}</span>`;
  if (active) return `<div class="row">${inner}<span class="spinner"></span></div>`;
  if (job.status === 'done' && job.trip_id) return `<a class="row" href="#/trip/${job.trip_id}">${inner}${ICON.chev}</a>`;
  if (job.status === 'failed') return `<div class="row">${inner}<button class="btn tint small" data-act="retry" data-id="${job.id}">Retry</button></div>`;
  return `<div class="row">${inner}</div>`;
}

function emptyState(color, icon, title, text, extra = '') {
  return `<div class="empty">${tile(color, icon, 'xl')}<h3>${title}</h3><p>${text}</p>${extra}</div>`;
}

function tripCard(t, i) {
  const cats = t.categories.length ? t.categories : ['other'];
  const g2 = cats[1] ? `var(--c-${cats[1]})` : 'var(--c-indigo)';
  const meta = [t.country, plural(t.place_count, 'place')].filter(Boolean).join(' · ');
  const cover = t.cover_photo
    ? `<img src="${esc(photoUrl(t.cover_photo, 900))}" alt="" ${i > 1 ? 'loading="lazy"' : ''} decoding="async" onerror="this.remove()">` : '';
  return `<a class="card" href="#/trip/${t.id}" style="--g1: var(--c-${cats[0]}); --g2: ${g2}">
    <span class="card-glyph" aria-hidden="true">${ICON[cats[0]] || ICON.other}</span>${cover}
    <span class="card-top">${t.day_count ? `<span class="pill">${ICON.calendar}${plural(t.day_count, 'day')}</span>` : '<span></span>'}
      <span class="cats" aria-hidden="true">${t.categories.slice(0, 4).map((c) => catTile(c, 'sm')).join('')}</span></span>
    <span class="card-body"><h3>${esc(t.name)}</h3><span class="meta">${esc(meta)}</span></span></a>`;
}

// ---------- Travel times ----------

const MODES = [
  ['walk', 'Walk', 'walking', 'w'],
  ['transit', 'Transit', 'transit', 'r'],
  ['drive', 'Drive', 'driving', 'd'],
  ['bike', 'Bike', 'bicycling', null],
];

function travelMode() {
  try { return localStorage.getItem('tripit.mode') || 'walk'; } catch { return 'walk'; }
}
function setTravelMode(mode) {
  try { localStorage.setItem('tripit.mode', mode); } catch { /* remembered for this visit only */ }
  S.mode = mode;
}
const currentMode = () => S.mode || travelMode();

function fmtDuration(sec) {
  const m = Math.max(1, Math.round(sec / 60));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h${m % 60 ? ` ${m % 60} min` : ''}`;
}
function fmtDistance(m) {
  const km = m / 1000;
  return km < 1 ? `${Math.round(m / 10) * 10} m` : `${km < 10 ? km.toFixed(1) : Math.round(km)} km`;
}
const located = (p) => p && p.latitude != null && p.longitude != null;

/** Picks the time for the chosen mode; for short hops with no transit time, falls back to walking. */
function pickTime(times, mode) {
  if (!times) return null;
  if (times[mode]) return { mode, time: times[mode] };
  if (mode === 'transit' && times.walk) return { mode: 'walk', time: times.walk, fallback: true };
  return null;
}

function directionsUrl(from, to, mode) {
  const m = MODES.find((x) => x[0] === mode) || MODES[0];
  const origin = from ? `&origin=${from.latitude},${from.longitude}` : '';
  return `https://www.google.com/maps/dir/?api=1${origin}&destination=${to.latitude},${to.longitude}&travelmode=${m[2]}`;
}

function legHtml(leg, from, to, mode) {
  const picked = pickTime(leg && leg.times, mode);
  if (!picked) return `<span class="s">No ${mode} route found</span>`;
  const { time } = picked;
  const approx = time.estimated ? '≈ ' : '';
  const note = picked.fallback ? ' <span class="s">(short walk)</span>' : '';
  return `${tile(picked.mode, picked.mode)}<span class="leg-t">${approx}${fmtDuration(time.duration_s)} · ${fmtDistance(time.distance_m)}${note}</span>
    <a class="leg-dir" href="${esc(directionsUrl(from, to, picked.mode))}" target="_blank" rel="noopener">Directions</a>`;
}

function legsKey(trip, day) {
  return `${trip.id}:${day}:${stops(trip, day).filter(located).map((p) => p.id).join(',')}`;
}

async function loadLegs(trip) {
  const mode = currentMode();
  const jobs = [];
  for (let d = 1; d <= trip.day_count; d++) {
    const key = legsKey(trip, d);
    if (key.split(':')[2].split(',').filter(Boolean).length < 2) continue;
    const fill = (data) => fillLegs(trip, d, data, mode);
    if (S.legs[key]) { fill(S.legs[key]); continue; }
    jobs.push(api(`/v1/trips/${trip.id}/days/${d}/legs`).then((data) => { S.legs[key] = data; fill(data); })
      .catch(() => document.querySelectorAll(`.leg[data-day="${d}"]`).forEach((el) => { el.innerHTML = '<span class="s">Travel time unavailable</span>'; })));
  }
  await Promise.all(jobs);
}

function fillLegs(trip, day, data, mode) {
  const byPair = new Map(data.legs.map((l) => [`${l.from_place_id}>${l.to_place_id}`, l]));
  let total = 0;
  let anyEstimate = false;
  document.querySelectorAll(`.leg[data-day="${day}"]`).forEach((el) => {
    const leg = byPair.get(`${el.dataset.from}>${el.dataset.to}`);
    const from = tripPlace(trip, el.dataset.from);
    const to = tripPlace(trip, el.dataset.to);
    el.innerHTML = legHtml(leg, from, to, mode);
    const picked = pickTime(leg && leg.times, mode);
    if (picked) { total += picked.time.duration_s; anyEstimate = anyEstimate || picked.time.estimated; }
  });
  const totalEl = document.querySelector(`.daytravel[data-day="${day}"]`);
  if (totalEl && total) totalEl.textContent = `${anyEstimate ? '≈ ' : ''}${fmtDuration(total)} travel`;
  const note = document.getElementById('travel-note');
  if (note) note.hidden = data.provider !== 'estimate';
}

function hereTimes(placeId) {
  return S.here && S.here.times[placeId];
}

async function locateMe(places) {
  const here = await getPosition();
  const pos = { coords: here };
  const ids = places.filter(located).map((p) => p.id).slice(0, 50);
  if (!ids.length) throw new ApiError('None of these places are on the map yet.', 0);
  const res = await api('/v1/routes/from', { method: 'POST', body: { latitude: pos.coords.latitude, longitude: pos.coords.longitude, place_ids: ids } });
  const times = { ...(S.here ? S.here.times : {}) };
  res.legs.forEach((l) => { times[l.to_place_id] = l.times; });
  S.here = { at: Date.now(), provider: res.provider, coords: { latitude: pos.coords.latitude, longitude: pos.coords.longitude }, times };
}

function hereChip(p) {
  const picked = pickTime(hereTimes(p.id), currentMode());
  if (!picked) return '';
  return `<span class="herechip">${ICON[picked.mode]}${picked.time.estimated ? '≈ ' : ''}${fmtDuration(picked.time.duration_s)} from you</span>`;
}

function hoursLine(p) {
  const st = openStatus(p.opening_hours);
  return st ? `<span class="s hours-${st.state}">${esc(st.label)}</span>` : '';
}

function dayIndexFor(trip, day) {
  if (!trip.start_date) return null;
  const d = new Date(`${trip.start_date}T12:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  d.setDate(d.getDate() + day - 1);
  return mondayIndex(d);
}

// ---------- Today ----------

/** "Closes in 35 min" / "Opens in 1 h" style status for right now, or the hours that day. */
function liveStatus(p, isToday, dayIdx) {
  if (!isToday) {
    const h = dayIdx != null ? dayHours(p.opening_hours, dayIdx) : null;
    return h ? `<span class="s">${ICON.clock.replace('<svg', '<svg class="inline-ic"')}${esc(h)}</span>` : '';
  }
  const change = nextChange(p.opening_hours);
  const st = openStatus(p.opening_hours);
  if (!change || !st) return '';
  if (change.open && change.minutes <= 90) return `<span class="status hours-closing">Closes in ${fmtDuration(change.minutes * 60)}</span>`;
  if (!change.open && change.minutes <= 120) return `<span class="status hours-closing">Opens in ${fmtDuration(change.minutes * 60)}</span>`;
  return `<span class="status hours-${st.state}">${esc(st.label)}</span>`;
}

function startsIn(p, isToday) {
  if (!p.start_time) return p.time_of_day ? cap(p.time_of_day) : '';
  if (!isToday) return fmtClock(p.start_time);
  const [h, m] = p.start_time.split(':').map(Number);
  const now = new Date();
  const mins = h * 60 + m - (now.getHours() * 60 + now.getMinutes());
  return mins > 0 && mins <= 180 ? `${fmtClock(p.start_time)} · in ${fmtDuration(mins * 60)}` : fmtClock(p.start_time);
}

function todayCard({ trip: t, day }) {
  const detail = S.trip[t.id];
  const list = detail ? stops(detail, day) : [];
  const next = list.find((p) => !p.visited);
  const done = list.filter((p) => p.visited).length;
  let inner;
  if (!detail) inner = '<span class="s">Loading today’s plan…</span>';
  else if (!list.length) inner = '<span class="s">Nothing planned today. Open the itinerary to add stops.</span>';
  else if (!next) inner = `<span class="today-next">${tile('green', 'done', 'md')}<span class="main"><span class="t b">All done for today</span><span class="s">${plural(done, 'stop')} visited</span></span>${ICON.chev}</span>`;
  else {
    inner = `<span class="today-next">${thumb(next, 52)}<span class="main"><span class="s">Up next${startsIn(next, true) ? ` · ${esc(startsIn(next, true))}` : ''}</span>
      <span class="t b">${esc(next.name)}</span>${liveStatus(next, true)}</span>${ICON.chev}</span>`;
  }
  return `<a class="todaycard" href="#/today/${t.id}">
    <span class="today-top"><span class="today-label">${ICON.sun}Today · Day ${day} of ${t.day_count}</span><span class="today-city">${esc(t.name)}</span></span>
    ${list.length ? `<span class="progress" aria-label="${done} of ${list.length} stops done"><i style="width:${Math.round((done / list.length) * 100)}%"></i></span>` : ''}
    ${inner}</a>`;
}

function nextCard(trip, p, n, total, isToday, dayIdx) {
  const photo = p.photos && p.photos[0];
  const changed = S.lastNext[trip.id] && S.lastNext[trip.id] !== p.id;
  S.lastNext[trip.id] = p.id;
  return `<div class="nextcard${changed ? ' enter' : ''}" style="${cvar(p.category)}">
    ${photo ? `<a class="next-photo" href="#/place/${p.id}"><img src="${esc(photoUrl(photo, 1000))}" alt="" decoding="async" onerror="this.parentElement.remove()"></a>` : ''}
    <div class="next-body">
      <div class="next-label">${isToday ? 'Up next' : 'First up'} · stop ${n} of ${total}</div>
      <h2><a href="#/place/${p.id}">${esc(p.name)}</a>${starMark(p)}</h2>
      <div class="s">${esc([startsIn(p, isToday), CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</div>
      ${liveStatus(p, isToday, dayIdx)}
      ${p.day_note ? `<div class="daynote">${esc(p.day_note)}</div>` : ''}
      <div class="next-travel" id="next-travel"></div>
      <div class="next-actions">
        <button class="btn" data-act="todaydir" data-id="${p.id}">${ICON.route}Directions</button>
        <button class="btn tint" data-act="done" data-id="${p.id}">${ICON.done}Done</button>
      </div>
    </div></div>`;
}

/** Fills "12 min walk from Devoción" (or from your location) under the Up next card. */
async function fillNextTravel(trip, day, next, prev) {
  const el = document.getElementById('next-travel');
  if (!el) return;
  const mode = currentMode();
  const fromYou = pickTime(hereTimes(next.id), mode);
  if (fromYou) {
    el.innerHTML = `${tile(fromYou.mode, fromYou.mode)}<span>${fromYou.time.estimated ? '≈ ' : ''}${fmtDuration(fromYou.time.duration_s)} from you</span>`;
    return;
  }
  if (!prev || !located(prev) || !located(next)) return;
  const key = legsKey(trip, day);
  try {
    const data = S.legs[key] || (S.legs[key] = await api(`/v1/trips/${trip.id}/days/${day}/legs`));
    const leg = data.legs.find((l) => l.from_place_id === prev.id && l.to_place_id === next.id);
    const picked = pickTime(leg && leg.times, mode);
    if (picked && document.getElementById('next-travel') === el) {
      el.innerHTML = `${tile(picked.mode, picked.mode)}<span>${picked.time.estimated ? '≈ ' : ''}${fmtDuration(picked.time.duration_s)} from ${esc(prev.name)}</span>`;
    }
  } catch { /* travel time is a nice-to-have */ }
}

// ---------- Taste, edits, briefings, concierge ----------

const TASTE_STEPS = [
  { key: 'pace', q: 'How do you like to travel?', single: true, options: [
    ['slow', 'Slow & savoured', 'Fewer places, longer lunches'], ['balanced', 'Balanced', 'A rhythm of plans and wandering'],
    ['packed', 'See it all', 'Every hour well spent']] },
  { key: 'budget', q: 'When it comes to spending…', single: true, options: [
    ['value', 'Hidden gems', 'Good value and local favourites'], ['mix', 'A considered mix', 'Save here, splurge there'],
    ['splurge', 'Worth the splurge', 'The best table in town']] },
  { key: 'food', q: 'What do you look for at the table?', options: ['Fine dining', 'Neighbourhood favourites', 'Street food',
    'Cafés & bakeries', 'Natural wine', 'Cocktail bars', 'Seafood', 'Vegetarian-friendly'] },
  { key: 'interests', q: 'What makes a trip for you?', options: ['Design & architecture', 'Art & museums', 'Fashion & boutiques',
    'Views & nature', 'Wellness & spas', 'Nightlife', 'History', 'Markets'] },
  { key: 'mornings', q: 'And your mornings?', single: true, notes: true, options: [
    ['early', 'Early riser', 'First in line, golden light'], ['late', 'Late starts', 'Nothing before ten']] },
];

function tasteSummary(p) {
  if (!p || !p.updated_at) return '';
  const label = (key) => {
    const step = TASTE_STEPS.find((x) => x.key === key);
    const opt = step.options.find((o) => o[0] === p[key]);
    return opt ? opt[1] : '';
  };
  return [label('pace'), label('budget'), ...(p.interests || []).slice(0, 2)].filter(Boolean).join(' · ');
}

function tasteInvite() {
  const p = background(S.profile, 'profile', loadProfile);
  let dismissed = false;
  try { dismissed = localStorage.getItem('tripit.tasteInvite') === 'no'; } catch { /* fine */ }
  if (!p || p.updated_at || dismissed) return '';
  return `<div class="section"><div class="invite"><div class="eyebrow">Personalise</div><h2>Tell us how you travel</h2>
    <p>Five quick questions, and every edit, briefing and suggestion is tailored to you.</p>
    <div class="invite-actions"><a class="btn" href="#/taste">Begin</a><button class="linkbtn" data-act="dismissinvite">Not now</button></div></div></div>`;
}

function editCard(te, e) {
  const cover = e.cover_photo ? `<img src="${esc(photoUrl(e.cover_photo, 640))}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : '';
  return `<a class="editcard" href="#/edit/${te.trip_id}/${e.id}">${cover}<span class="editcard-body">
    <span class="eyebrow">The Edit · ${esc(te.trip_name)}</span><span class="editcard-title">${esc(e.title)}</span>
    <span class="editcard-meta">${plural(e.entries.length, 'place')}</span></span></a>`;
}

function homeEdits(tripCount) {
  if (!tripCount) return '';
  const all = background(S.allEdits, 'alledits', loadAllEdits);
  if (!all || !all.length) return '';
  const cards = all.flatMap((te) => te.edits.slice(0, 3).map((e) => editCard(te, e))).slice(0, 9);
  return `<div class="railhead"><h2 class="section-title">The Edits</h2><span class="eyebrow">Curated for you</span></div>
    <div class="rail">${cards.join('')}</div><div class="railhead"><h2 class="section-title">Your trips</h2></div>`;
}

function editsSection(trip) {
  if (S.curating[trip.id]) {
    return `<div class="railhead"><h2 class="section-title">The Edits</h2><span class="eyebrow">Curating…</span></div>
      <div class="rail">${'<div class="editcard skeleton"></div>'.repeat(3)}</div>`;
  }
  const te = background(S.edits[trip.id], `edits:${trip.id}`, () => loadEdits(trip.id));
  if (!te) return '';
  if (!te.edits.length) {
    if (trip.places.length < 3) return '';
    if (trip.places.length >= 4 && !S.curateTried[trip.id] && !isOffline()) setTimeout(() => curate(trip.id, true), 0);
    return `<div class="section"><div class="invite"><div class="eyebrow">The Edits</div><h2>Curate this trip</h2>
      <p>Editorial lists from your saved places, tailored to your taste: date nights, slow mornings, one perfect afternoon.</p>
      <div class="invite-actions"><button class="btn" data-act="curate" data-id="${trip.id}">Curate</button></div></div></div>`;
  }
  const profileNewer = S.profile && S.profile.updated_at && te.created_at && new Date(S.profile.updated_at) > new Date(te.created_at);
  const aside = te.stale || profileNewer
    ? `<button class="linkbtn" data-act="curate" data-id="${trip.id}">${profileNewer ? 'Refresh for your taste' : 'Refresh'}</button>`
    : `<span class="eyebrow">${te.curated_by === 'claude' ? 'Curated for you' : 'From your saves'}</span>`;
  return `<div class="railhead"><h2 class="section-title">The Edits</h2>${aside}</div>
    <div class="rail">${te.edits.map((e) => editCard(te, e)).join('')}</div>`;
}

async function curate(tripId, auto = false) {
  if (S.curating[tripId]) return;
  S.curating[tripId] = true;
  S.curateTried[tripId] = true;
  render({ quiet: auto });
  try {
    S.edits[tripId] = await api(`/v1/trips/${tripId}/edits`, { method: 'POST' });
    fetchedAt[`edits:${tripId}`] = Date.now();
    S.allEdits = null;
  } catch (e) {
    if (!auto) toast(e.message, true);
  } finally {
    S.curating[tripId] = false;
    render({ quiet: true });
  }
}

function briefingHtml(b) {
  return `<div class="brief-top"><span class="eyebrow">Your briefing</span>
      <button class="brief-refresh" data-act="briefrefresh" aria-label="Refresh briefing">${ICON.sparkle}</button></div>
    <h2 class="brief-head">${esc(b.headline)}</h2>
    <ul class="brief-points">${b.points.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>`;
}

async function loadBriefing(tripId, day, date, key, refresh = false) {
  if (S.briefing[key] && !refresh) return;
  try {
    const b = await api(`/v1/trips/${tripId}/days/${day}/briefing`, { method: 'POST', body: { local_date: date, refresh } });
    S.briefing[key] = b;
    const el = document.getElementById('briefing');
    if (el) el.innerHTML = briefingHtml(b);
  } catch {
    const el = document.getElementById('briefing');
    if (el && !S.briefing[key]) el.closest('.section').remove();
  }
}

const CHAT_PROMPTS = ['Plan my evening', 'Where should I eat near my next stop?', 'What’s worth booking ahead?',
  'Make tomorrow more relaxed', 'Rainy day ideas from my saves'];
const chatKey = (tripId) => `tripit.chat.${tripId || 'all'}`;
function readChat(tripId) {
  try { return JSON.parse(localStorage.getItem(chatKey(tripId))) || []; } catch { return []; }
}
function writeChat(tripId, msgs) {
  try { localStorage.setItem(chatKey(tripId), JSON.stringify(msgs.slice(-40))); } catch { /* kept for this visit only */ }
}
function localIso() {
  const d = new Date();
  return `${isoDate(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function chatWelcome() {
  return `<div class="welcome"><div class="eyebrow">At your service</div>
    <p class="welcome-text">Ask about your saved places, plan an evening, or rework a day. I suggest changes; nothing moves until you confirm.</p>
    <div class="prompts">${CHAT_PROMPTS.map((q) => `<button class="prompt" data-act="chatprompt" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div></div>`;
}

function chatMessage(m, i, tripId) {
  if (m.role === 'user') return `<div class="msg me"><p>${esc(m.content)}</p></div>`;
  const trip = tripId ? S.trip[tripId] : null;
  const paras = esc(m.content).split(/\n{2,}/).map((t) => `<p>${t.replace(/\n/g, '<br>')}</p>`).join('');
  const places = (m.place_ids || []).map((id) => trip && tripPlace(trip, id)).filter(Boolean);
  const cards = places.length ? `<div class="msg-places">${places.map((p) => `<a class="msg-place" href="#/place/${p.id}">${thumb(p, 44)}
    <span class="main"><span class="t">${esc(p.name)}</span><span class="s">${esc([CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</a>`).join('')}</div>` : '';
  const acts = m.actions && m.actions.length ? `<div class="proposal"><div class="eyebrow">Proposed changes</div>
    <ul>${m.actions.map((a) => `<li>${esc(a.label)}</li>`).join('')}</ul>
    ${m.applied ? '<span class="s">Applied to your trip</span>' : m.dismissed ? '<span class="s">Left as it was</span>'
      : `<div class="proposal-actions"><button class="btn small" data-act="chatapply" data-index="${i}">Apply</button>
        <button class="linkbtn" data-act="chatdismiss" data-index="${i}">Not now</button></div>`}</div>` : '';
  return `<div class="msg ai${m.error ? ' error' : ''}"><div class="ai-name">${m.error ? 'Couldn’t answer' : 'Concierge'}</div>${paras}${cards}${acts}</div>`;
}

function renderChatLog(typing = false) {
  const log = document.getElementById('chatlog');
  if (!log) return;
  const msgs = readChat(S.chatTrip);
  log.innerHTML = (msgs.length ? msgs.map((m, i) => chatMessage(m, i, S.chatTrip)).join('') : chatWelcome())
    + (typing ? '<div class="msg ai typing" aria-label="Concierge is typing"><span></span><span></span><span></span></div>' : '');
  hydrateIcons(log);
  requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: reducedMotion.matches ? 'auto' : 'smooth' }));
}

async function sendChat(text) {
  text = text.trim();
  if (!text || S.chatBusy) return;
  const tripId = S.chatTrip;
  const msgs = readChat(tripId);
  msgs.push({ role: 'user', content: text });
  writeChat(tripId, msgs);
  S.chatBusy = true;
  renderChatLog(true);
  try {
    const coords = S.here && S.here.coords;
    const reply = await api('/v1/concierge', { method: 'POST', body: {
      trip_id: tripId || null, local_time: localIso(),
      latitude: coords ? coords.latitude : null, longitude: coords ? coords.longitude : null,
      messages: msgs.filter((m) => !m.error).slice(-20).map(({ role, content }) => ({ role, content })),
    } });
    msgs.push({ role: 'assistant', content: reply.reply, place_ids: reply.place_ids, actions: reply.actions });
  } catch (e) {
    msgs.push({ role: 'assistant', content: e.message || 'Something went wrong', error: true });
  }
  writeChat(tripId, msgs);
  S.chatBusy = false;
  renderChatLog();
}

async function applyChatActions(index) {
  const tripId = S.chatTrip;
  const msgs = readChat(tripId);
  const m = msgs[index];
  if (!m || !m.actions || m.applied || !tripId) return;
  try {
    for (const a of m.actions) {
      if (a.type === 'move') await api(`/v1/trips/${tripId}/move`, { method: 'POST', body: { place_id: a.place_id, day: a.day, index: a.index ?? 999 } });
      else if (a.type === 'must_do') await api(`/v1/places/${a.place_id}`, { method: 'PATCH', body: { must_do: a.value } });
      else if (a.type === 'visited') await api(`/v1/places/${a.place_id}`, { method: 'PATCH', body: { visited: a.value } });
      else if (a.type === 'set_time') await api(`/v1/places/${a.place_id}`, { method: 'PATCH', body: a.time ? { start_time: a.time } : { clear_start_time: true } });
    }
    m.applied = true;
    writeChat(tripId, msgs);
    await loadTrip(tripId);
    fetchedAt.trips = 0;
    toast('Your trip is updated');
  } catch (e) {
    toast(e.message, true);
  }
  renderChatLog();
}

// Keep the composer above the on-screen keyboard.
if (window.visualViewport) {
  const kb = () => document.documentElement.style.setProperty('--kb', `${Math.max(0, innerHeight - visualViewport.height - visualViewport.offsetTop)}px`);
  visualViewport.addEventListener('resize', kb);
  visualViewport.addEventListener('scroll', kb);
}

// ---------- Views ----------

const addButton = `<button class="gbtn tint" data-act="add" aria-label="Add a reel">${ICON.plus}</button>`;

/** Trips | Places switch under the home title. */
const homeSwitch = () => segControl('home', [['trips', 'Trips'], ['places', 'Places']].map(([k, label]) => ({
  on: S.home.tab === k,
  html: `<button class="${S.home.tab === k ? 'on' : ''}" data-act="hometab" data-tab="${k}" aria-pressed="${S.home.tab === k}">${label}</button>`,
})));

async function placesHome(trips) {
  const places = await cachedPlaces();
  const h = S.home;
  if (h.trip !== 'all' && !trips.some((t) => t.id === h.trip)) h.trip = 'all';
  const tripName = Object.fromEntries(trips.map((t) => [t.id, t.name]));
  const inTrip = places.filter((p) => h.trip === 'all' || p.trip_id === h.trip);
  const base = inTrip.filter((p) => !h.starred || p.must_do);
  const counts = {};
  base.forEach((p) => { counts[GROUP_OF[p.category] || 'other'] = (counts[GROUP_OF[p.category] || 'other'] || 0) + 1; });
  if (h.cat !== 'all' && !counts[h.cat]) h.cat = 'all';
  const list = sortPlaces(base.filter((p) => h.cat === 'all' || (GROUP_OF[p.category] || 'other') === h.cat), h.sort);
  const starredCount = inTrip.filter((p) => p.must_do).length;

  const chip = (id, label, n, on) => `<button class="fchip${on ? ' on' : ''}" data-act="homecat" data-cat="${id}" aria-pressed="${on}">${label}<span class="n">${n}</span></button>`;
  const chips = `<div class="fchips" role="group" aria-label="Filter by type">
    <button class="fchip star${h.starred ? ' on' : ''}" data-act="homestarred" aria-pressed="${h.starred}">${ICON.star}Starred<span class="n">${starredCount}</span></button>
    ${chip('all', 'All', base.length, h.cat === 'all')}
    ${GROUPS.filter((g) => counts[g.id]).map((g) => chip(g.id, g.label, counts[g.id], h.cat === g.id)).join('')}</div>`;
  const controls = `<div class="homectl">
    ${trips.length > 1 ? `<button class="pillbtn" data-act="hometrip">${esc(h.trip === 'all' ? 'All trips' : tripName[h.trip])}</button>` : ''}
    <button class="pillbtn" data-act="homesort" aria-label="Sort: ${esc(SORTS[h.sort].label)}">${esc(SORTS[h.sort].label)}</button>
    <button class="pillbtn${S.sel.on ? ' on' : ''}" data-act="selecttoggle">${S.sel.on ? 'Done' : 'Select'}</button></div>`;

  const group = (items) => `<div class="group thumbs">${items.map((p) => placeRow(p, { home: true })).join('')}</div>`;
  const starred = list.filter((p) => p.must_do);
  const rest = list.filter((p) => !p.must_do);
  let body;
  if (!places.length) {
    body = emptyState('accent', 'pin', 'No places yet', 'Places from the reels you save appear here, ready to filter, star and add to an itinerary.',
      `<button class="btn" data-act="add">${ICON.link}Paste a link</button>`);
  } else if (!list.length) {
    body = emptyState('gray', 'pinslash', 'Nothing matches', 'Try another filter.',
      '<button class="btn tint" data-act="homeclear">Clear filters</button>');
  } else if (starred.length && rest.length) {
    body = `<div class="section"><div class="section-h">${ICON.star}Starred</div>${group(starred)}</div>
      <div class="section"><div class="section-h">${CATS_OF_FILTER()}</div>${group(rest)}</div>`;
  } else {
    body = `<div class="section">${group(list)}</div>`;
  }
  const subtitle = `${plural(places.length, 'place')} across ${plural(trips.length, 'trip')}`;
  return `${navbar('Places', { right: addButton })}<h1 class="largetitle" data-anchor>Places</h1>
    <div class="subtitle"><span>${esc(subtitle)}</span></div>${homeSwitch()}${places.length ? chips + controls : ''}${body}${selBar()}`;
}
const CATS_OF_FILTER = () => (S.home.cat === 'all' ? 'More places' : esc(GROUPS.find((g) => g.id === S.home.cat).label));

/** Floating bar while selecting places. */
function selBar() {
  if (!S.sel.on) return '';
  const n = S.sel.picked.size;
  return `<div class="selbar" role="region" aria-label="Selected places"><span class="selcount">${n ? `${plural(n, 'place')} selected` : 'Tap places to select them'}</span>
    <button class="btn small" data-act="selectadd" ${n ? '' : 'disabled'}>${ICON.calendarPlus}Add to itinerary</button></div>`;
}

const VIEWS = {
  async trips() {
    const trips = await cachedTrips();
    if (S.home.tab === 'places') return placesHome(trips);
    const inflightJobs = S.jobs.filter((j) => ACTIVE.has(j.status));
    const body = !trips.length && !inflightJobs.length
      ? emptyState('accent', 'plane', 'No trips yet',
        'Share a travel reel from TikTok or Instagram to TripIt, or paste a link. The places land here, pinned on a map.',
        `<button class="btn" data-act="add">${ICON.link}Paste a link</button><a class="linkbtn" href="#/settings">Set up the share button</a>`)
      : `${inflightJobs.length ? `<div class="section"><div class="group tiles">${inflightJobs.map(jobRow).join('')}</div></div>` : ''}
         ${trips.length ? `<div class="cards">${trips.map(tripCard).join('')}</div>` : ''}`;
    const active = activeTrip(trips);
    if (active && !S.trip[active.trip.id]) loadTrip(active.trip.id).then(() => render({ quiet: true })).catch(() => {});
    return {
      html: `${navbar('Trips', { right: addButton })}<h1 class="largetitle" data-anchor>Trips</h1>${homeSwitch()}${active ? todayCard(active) : ''}
        ${tasteInvite()}${homeEdits(trips.length)}${body}`,
      // Warm the cache so opening a trip is instant.
      after: () => setTimeout(() => trips.slice(0, 8).forEach((t) => { if (!S.trip[t.id]) loadTrip(t.id).catch(() => {}); }), 400),
    };
  },

  async trip(r) {
    const trip = await cachedTrip(r.id);
    const mode = ['places', 'itinerary', 'map'].includes(r.mode) ? r.mode : 'places';
    const right = `<span class="gcluster"><button class="gbtn" data-act="sharetrip" data-id="${trip.id}" aria-label="Share trip">${ICON.share}</button>
      <button class="gbtn" data-act="tripmenu" data-id="${trip.id}" aria-label="More">${ICON.more}</button></span>`;
    const seg = segControl(`seg:${trip.id}`, ['places', 'itinerary', 'map'].map((m) => ({
      on: m === mode,
      html: `<a href="#/trip/${trip.id}${m === 'places' ? '' : `/${m}`}" class="${m === mode ? 'on' : ''}" ${m === mode ? 'aria-current="page"' : ''}>${cap(m)}</a>`,
    })));
    const meta = [trip.country, plural(trip.places.length, 'place'), trip.day_count ? `${trip.day_count}-day plan` : ''].filter(Boolean).join(' · ');
    const cats = [...new Set(trip.places.map((p) => p.category))].sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b));
    const head = `${navbar(trip.name, { back: '#/', backLabel: 'Trips', right })}
      <h1 class="largetitle" data-anchor>${esc(trip.name)}</h1>
      <div class="subtitle"><span>${esc(meta)}</span><span class="tiles-inline" aria-hidden="true">${cats.slice(0, 6).map((c) => catTile(c, 'sm')).join('')}</span>
        ${trip.share_token ? `<button class="chip-shared" data-act="sharetrip" data-id="${trip.id}">${ICON.link}Shared</button>` : ''}</div>${seg}`;

    if (mode === 'places') return head + editsSection(trip) + placesList(trip);
    if (mode === 'itinerary') return { html: head + itinerary(trip), after: () => loadLegs(trip) };

    const day = S.mapDay[trip.id] || 0;
    const shown = day ? stops(trip, day) : trip.places;
    const chips = trip.day_count
      ? `<div class="mapchips">${[0, ...Array.from({ length: trip.day_count }, (_, i) => i + 1)].map((d) =>
          `<button class="mapchip ${d === day ? 'on' : ''}" data-act="mapday" data-trip="${trip.id}" data-day="${d}" aria-pressed="${d === day}">${d ? `Day ${d}` : 'All'}</button>`).join('')}</div>`
      : '';
    const missing = shown.filter((p) => p.latitude == null).length;
    return {
      html: `${head}<div class="map fill"><div id="trip-map" style="position:absolute;inset:0"></div>${chips}
        ${missing ? `<div class="mapnote">${plural(missing, 'place')} not on the map yet</div>` : ''}</div>`,
      after: () => renderMap($('#trip-map'), shown, { route: !!day, popup: popupHtml, newIds: S.newIds, pad: { top: chips ? 70 : 40, bottom: 120 } }),
    };
  },

  async today(r) {
    const trip = await cachedTrip(r.id);
    const active = activeTrip([trip]);
    const head = (title) => navbar(title, { back: '#/', backLabel: 'Trips',
      right: `<a class="gbtn" href="#/trip/${trip.id}/itinerary" aria-label="Full itinerary">${ICON.calendar}</a>` });
    if (!trip.day_count) {
      return `${head(trip.name)}<h1 class="largetitle" data-anchor>${esc(trip.name)}</h1>
        ${emptyState('indigo', 'calendar', 'No itinerary yet', 'Plan the trip first, then this page walks you through each day.',
          `<button class="btn" data-act="plan" data-id="${trip.id}">${ICON.sparkle}Plan my trip</button>`)}`;
    }
    const day = Math.min(Math.max(1, Number(r.params.get('day')) || (active ? active.day : 1)), trip.day_count);
    const isToday = !!active && active.day === day;
    const dayIdx = dayIndexFor(trip, day);
    const list = stops(trip, day);
    const next = list.find((p) => !p.visited);
    const done = list.filter((p) => p.visited);
    const later = list.filter((p) => !p.visited && p !== next);
    const prev = next ? [...list.slice(0, list.indexOf(next))].reverse().find(located) : null;
    const title = isToday ? 'Today' : `Day ${day}`;
    const briefDate = isToday ? isoDate(new Date()) : null;
    const briefKey = `${trip.id}:${day}:${briefDate || ''}`;
    const pills = trip.day_count > 1 ? `<div class="daypills" role="tablist">${Array.from({ length: trip.day_count }, (_, i) => i + 1).map((d) =>
      `<a class="daypill${d === day ? ' on' : ''}" href="#/today/${trip.id}?day=${d}" data-replace role="tab" aria-selected="${d === day}">${active && active.day === d ? 'Today' : `Day ${d}`}</a>`).join('')}</div>` : '';
    const row = (p) => {
      const inner = `<span class="stopnum" style="${cvar(p.category)}">${list.indexOf(p) + 1}</span>${thumb(p, 48)}
        <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${starMark(p)}</span>
        <span class="s">${esc([startsIn(p, isToday), CATS[p.category]].filter(Boolean).join(' · '))}</span></span>`;
      return p.visited
        ? `<div class="row"><a class="rowlink" href="#/place/${p.id}">${inner}</a><button class="linkbtn" data-act="undone" data-id="${p.id}" aria-label="Mark ${esc(p.name)} not visited">Undo</button></div>`
        : `<a class="row" href="#/place/${p.id}">${inner}${ICON.chev}</a>`;
    };
    const html = `${head(title)}<h1 class="largetitle" data-anchor>${title}</h1>
      <div class="subtitle"><span>${esc([dayDate(trip.start_date, day), trip.name, trip.day_titles[day - 1]].filter(Boolean).join(' · '))}</span></div>
      ${pills}
      <div class="section"><div class="progress big" aria-label="${done.length} of ${list.length} stops done"><i style="width:${list.length ? Math.round((done.length / list.length) * 100) : 0}%"></i></div>
        <div class="section-f">${done.length} of ${plural(list.length, 'stop')} done</div></div>
      ${list.length ? `<div class="section"><div class="briefing" id="briefing">${S.briefing[briefKey] ? briefingHtml(S.briefing[briefKey]) : '<div class="brief-skel"></div>'}</div></div>` : ''}
      ${!list.length ? emptyState('gray', 'calendar', 'Nothing planned', 'Open a place and move it to this day.')
        : next ? `<div class="section">${nextCard(trip, next, list.indexOf(next) + 1, list.length, isToday, dayIdx)}</div>`
        : `<div class="section"><div class="group donecard">${tile('green', 'done', 'lg')}<div><h3>Day complete</h3><p class="s">You visited all ${plural(list.length, 'stop')}.${day < trip.day_count ? ` Day ${day + 1} is next.` : ''}</p></div></div></div>`}
      ${later.length ? `<div class="section"><h2 class="section-title">Later${isToday ? ' today' : ''}<span class="count">${later.length}</span></h2><div class="group thumbs">${later.map(row).join('')}</div></div>` : ''}
      ${done.length ? `<div class="section"><h2 class="section-title">Done<span class="count">${done.length}</span></h2><div class="group thumbs">${done.map(row).join('')}</div></div>` : ''}`;
    return { html, after: () => { if (next) fillNextTravel(trip, day, next, prev); if (list.length) loadBriefing(trip.id, day, briefDate, briefKey); } };
  },

  async place(r) {
    const trip = await findPlace(r.id);
    const p = tripPlace(trip, r.id);
    if (!p) throw new ApiError('This place was deleted.', 404);
    const links = mapsLinks(p, trip);
    const reelIds = p.reel_ids && p.reel_ids.length ? p.reel_ids : [p.reel_id].filter(Boolean);
    const reels = reelIds.map((id) => trip.reels.find((x) => x.id === id)).filter(Boolean);
    const isLocated = located(p);
    const photos = p.photos || [];
    const pages = photos.map((ph, i) => `<button class="gimg" data-act="viewphoto" data-id="${p.id}" data-index="${i}" aria-label="Open photo ${i + 1} of ${photos.length}">
        <img src="${esc(photoUrl(ph, 1000))}" alt="${esc(p.name)}" ${i ? 'loading="lazy"' : ''} decoding="async" onerror="this.closest('.gimg').remove()">
        <span class="gcap">${esc(photoCaption(ph))}</span></button>`).join('')
      + (isLocated ? '<div class="gimg gmap"><div id="mini-map" style="position:absolute;inset:0"></div></div>' : '');
    const pageCount = photos.length + (isLocated ? 1 : 0);
    const hero = pageCount ? `<div class="hero${photos.length ? '' : ' maponly'}">
        <div class="gallery" aria-label="Photos of ${esc(p.name)}">${pages}</div>
        ${pageCount > 1 ? `<div class="dots" aria-hidden="true">${Array.from({ length: pageCount }, (_, i) => `<i class="${i ? '' : 'on'}"></i>`).join('')}</div>` : ''}</div>` : '';
    const st = openStatus(p.opening_hours);

    const dayRows = trip.day_count ? `
      <div class="row">${tile('red', 'calendar')}<label class="main" for="day-select"><span class="t">Day</span></label>
        <select class="select" id="day-select" data-act="setday" data-id="${p.id}">
          <option value="0">Not scheduled</option>
          ${Array.from({ length: trip.day_count }, (_, i) => `<option value="${i + 1}" ${p.day_number === i + 1 ? 'selected' : ''}>Day ${i + 1}</option>`).join('')}
        </select></div>
      <div class="row">${tile('indigo', 'clock')}<label class="main" for="tod-select"><span class="t">Time</span></label>
        <select class="select" id="tod-select" data-act="settod" data-id="${p.id}">
          <option value="">Any time</option>
          ${TODS.map((x) => `<option value="${x}" ${p.time_of_day === x ? 'selected' : ''}>${cap(x)}</option>`).join('')}
        </select></div>
      <div class="row">${tile('orange', 'calendarPlus')}<label class="main" for="time-input"><span class="t">Exact time</span>
          <span class="s">For a reservation or a tour</span></label>
        <input class="datefield" type="time" id="time-input" data-act="settime" data-id="${p.id}" value="${esc(p.start_time || '')}">
        ${p.start_time ? `<button class="linkbtn" data-act="cleartime" data-id="${p.id}" aria-label="Clear exact time">Clear</button>` : ''}</div>` : '';

    const star = `<button class="gbtn star${p.must_do ? ' on' : ''}" data-act="star" data-id="${p.id}" aria-pressed="${p.must_do}" aria-label="${p.must_do ? 'Remove the star' : 'Star this place'}">${p.must_do ? ICON.star : ICON.starO}</button>`;
    const html = `${navbar(p.name, { back: `#/trip/${trip.id}`, backLabel: trip.name, right: star })}
      ${hero}
      <div class="ph" style="${cvar(p.category)}">
        <span class="cat">${catTile(p.category, 'sm')}${CATS[p.category]}</span>
        <h1 data-anchor>${esc(p.name)}${isNew(p)}</h1>
        <span class="loc">${esc([p.neighborhood, p.city].filter(Boolean).join(' · '))}</span>
        ${p.must_do ? `<span class="mustline">${ICON.star}Starred: first in your lists, and the planner always fits it in</span>` : ''}
        ${p.mention_count >= 2 ? `<span class="hotline">${ICON.flame}Recommended in ${p.mention_count} of your saved reels</span>` : ''}
        ${st ? `<span class="status hours-${st.state}">${esc(st.label)}</span>` : ''}
        ${p.resolved_name ? `<span class="s">On maps as ${esc(p.resolved_name)}</span>` : ''}
        ${p.confidence === 'low' ? '<span class="flag">The name was hard to make out in the reel; double-check it.</span>' : ''}
      </div>
      ${p.summary ? `<p class="para">${esc(p.summary)}</p>` : ''}

      <div class="quick">
        <a class="qbtn" href="${esc(links.apple)}" target="_blank" rel="noopener">${tile('green', 'map')}Apple Maps</a>
        <a class="qbtn" href="${esc(links.google)}" target="_blank" rel="noopener">${tile('blue', 'globe')}Google Maps</a>
        <button class="qbtn" data-act="directions" data-id="${p.id}">${tile('orange', 'route')}Directions</button>
      </div>

      ${isLocated ? '' : `<div class="section"><div class="section-h">Not on the map yet</div><div class="group">
        <form class="row" data-form="locate" data-id="${p.id}"><span class="inline-form">
          <input class="field" id="locate-q" name="q" placeholder="Search, e.g. ${esc(p.name)}, ${esc(p.city)}" value="${esc(`${p.name}, ${p.neighborhood ? `${p.neighborhood}, ` : ''}${p.city}`)}" autocomplete="off">
          <button class="btn small" type="submit">Find</button></span></form>
        </div><div class="section-f">Add a street or neighborhood if the first search didn’t find it.</div></div>`}

      ${hoursSection(p)}
      ${gettingThere(p)}

      ${(p.recommended_items.length || p.tips || p.price_hint) ? `<div class="section"><div class="section-h">From the reel</div><div class="group tiles">
        ${p.recommended_items.map((i) => `<div class="row"><span class="tile" style="--pc:#FFCC00">${ICON.star}</span><span class="main"><span class="t">${esc(i)}</span></span></div>`).join('')}
        ${p.price_hint ? `<div class="row">${tile('green', 'tag')}<span class="main"><span class="s">Price</span><span class="t">${esc(p.price_hint)}</span></span></div>` : ''}
        ${p.tips ? `<div class="row">${tile('pink', 'sparkle')}<span class="main"><span class="s">Tip</span><span class="t">${esc(p.tips)}</span></span></div>` : ''}
      </div></div>` : ''}

      <div class="section"><div class="section-h">Details</div><div class="group tiles">
        ${p.address ? `<div class="row">${tile('gray', 'pin')}<span class="main"><span class="s">Address</span><span class="t">${esc(p.address)}</span></span></div>` : ''}
        <label class="row" for="visited-toggle">${tile('green', 'done')}<span class="main"><span class="t">Visited</span></span>
          <input class="switch" type="checkbox" id="visited-toggle" data-act="visited" data-id="${p.id}" ${p.visited ? 'checked' : ''}></label>
        ${dayRows}
        <div class="row">${catTile(p.category)}<label class="main" for="cat-select"><span class="t">Category</span></label>
          <select class="select" id="cat-select" data-act="setcat" data-id="${p.id}">
            ${CAT_ORDER.map((c) => `<option value="${c}" ${p.category === c ? 'selected' : ''}>${CATS[c]}</option>`).join('')}
          </select></div>
        ${isLocated ? `<button class="row" data-act="relocate" data-id="${p.id}">${tile('teal', 'locate')}<span class="main"><span class="t link">Wrong pin? Search again</span></span></button>` : ''}
      </div></div>

      <div class="section"><div class="section-h">My notes</div><div class="group"><div class="row">
        <textarea class="notes" id="notes" data-act="notes" data-id="${p.id}" placeholder="Add a note" rows="3" aria-label="My notes">${esc(p.user_notes)}</textarea>
      </div></div></div>

      ${reels.length ? `<div class="section"><div class="section-h">Saved from</div><div class="group tiles">${reels.map((reel) => `
        ${safeUrl(reel.url) ? `<a class="row" href="${esc(reel.url)}" target="_blank" rel="noopener">` : '<div class="row">'}
        ${platformTile(platformOf(reel.platform || reel.url))}
        <span class="main"><span class="t">${esc(reel.title)}</span>
        <span class="s">${esc([platformName(reel.platform), reel.creator ? `@${reel.creator}` : ''].filter(Boolean).join(' · '))}</span></span>
        ${safeUrl(reel.url) ? `${ICON.chev}</a>` : '</div>'}`).join('')}</div></div>` : ''}

      <div class="section"><div class="group"><button class="row destructive" data-act="askdeleteplace" data-id="${p.id}" data-trip="${trip.id}">Delete place</button></div></div>`;
    return {
      html,
      after: () => { if (isLocated) renderMap($('#mini-map'), [p], { interactive: false, zoom: 15 }); },
    };
  },

  async edit(r) {
    const trip = await cachedTrip(r.id);
    const te = S.edits[r.id] || await loadEdits(r.id);
    const e = te.edits.find((x) => x.id === r.editId);
    if (!e) throw new ApiError('This edit was refreshed. Open the trip to see the latest ones.', 404);
    const entries = e.entries.map((en) => ({ ...en, p: tripPlace(trip, en.place_id) })).filter((en) => en.p);
    const html = `${navbar(e.title, { back: `#/trip/${trip.id}`, backLabel: trip.name })}
      <header class="edithead">${e.cover_photo ? `<div class="edithero"><img src="${esc(photoUrl(e.cover_photo, 1200))}" alt="" decoding="async" onerror="this.parentElement.remove()"></div>` : ''}
        <div class="eyebrow">The Edit · ${esc(trip.name)}</div>
        <h1 class="edittitle" data-anchor>${esc(e.title)}</h1>
        <p class="dek">${esc(e.dek)}</p>
        <div class="byline">${te.curated_by === 'claude' ? 'Curated for you' : 'From your saves'} · ${plural(entries.length, 'place')}</div></header>
      <ol class="editlist">${entries.map(({ p, note }, i) => {
        const photo = p.photos && p.photos[0] && !(e.cover_photo && p.photos[0].url === e.cover_photo.url) ? p.photos[0] : null;
        const st = openStatus(p.opening_hours);
        return `<li><a class="editentry" href="#/place/${p.id}">
          ${photo ? `<span class="ee-photo"><img src="${esc(photoUrl(photo, 900))}" alt="" loading="lazy" decoding="async" onerror="this.parentElement.remove()"></span>` : ''}
          <span class="ee-body"><span class="ee-num">${String(i + 1).padStart(2, '0')}</span>
            <span class="eyebrow">${esc([CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</span>
            <span class="ee-name">${esc(p.name)}${starMark(p)}</span>
            ${note ? `<span class="ee-note">${esc(note)}</span>` : ''}
            ${st ? `<span class="s hours-${st.state}">${esc(st.label)}</span>` : ''}</span></a></li>`;
      }).join('')}</ol>
      <div class="section"><a class="btn tint wide" href="#/trip/${trip.id}/map">${ICON.map}See them on the map</a></div>`;
    return html;
  },

  async concierge() {
    const trips = await cachedTrips();
    if (S.chatTrip === undefined || (S.chatTrip && !trips.some((t) => t.id === S.chatTrip))) {
      const active = activeTrip(trips);
      S.chatTrip = active ? active.trip.id : (trips[0] ? trips[0].id : null);
    }
    const tripId = S.chatTrip;
    if (tripId && !S.trip[tripId]) loadTrip(tripId).then(() => renderChatLog()).catch(() => {});
    const msgs = readChat(tripId);
    const chips = trips.length ? `<div class="daypills">${[...trips.map((t) => ({ id: t.id, name: t.name })), { id: '', name: 'All trips' }].map((t) =>
      `<button class="daypill${(t.id || null) === tripId ? ' on' : ''}" data-act="chattrip" data-id="${t.id}">${esc(t.name)}</button>`).join('')}</div>` : '';
    return {
      html: `${navbar('Concierge', { right: msgs.length ? `<button class="gbtn" data-act="chatnew" aria-label="New conversation">${ICON.plus}</button>` : '' })}
        <h1 class="largetitle" data-anchor>Concierge</h1>
        <div class="subtitle"><span>Your personal travel assistant</span></div>${chips}
        <div class="chatlog" id="chatlog">${msgs.length ? msgs.map((m, i) => chatMessage(m, i, tripId)).join('') : chatWelcome()}</div>
        <form class="composer" data-form="chat"><textarea id="chat-input" rows="1" placeholder="Ask your concierge…" aria-label="Message to your concierge" enterkeyhint="send"></textarea>
          <button class="sendbtn" type="submit" aria-label="Send">${ICON.send}</button></form>`,
      after: () => { if (msgs.length) window.scrollTo(0, document.body.scrollHeight); },
    };
  },

  async taste() {
    if (!S.taste) S.taste = { step: 0, dir: 1, p: { ...(S.profile || await loadProfile()) } };
    const { step, p } = S.taste;
    const q = TASTE_STEPS[step];
    const last = step === TASTE_STEPS.length - 1;
    const chosen = (v) => (q.single ? p[q.key] === v : (p[q.key] || []).includes(v));
    const opts = q.options.map((o) => {
      const [value, label, hint] = Array.isArray(o) ? o : [o, o, ''];
      return `<button class="opt${chosen(value) ? ' on' : ''}" data-act="tastepick" data-value="${esc(value)}" aria-pressed="${chosen(value)}">
        <span class="opt-label">${esc(label)}</span>${hint ? `<span class="opt-hint">${esc(hint)}</span>` : ''}</button>`;
    }).join('');
    return `<div class="taste">
      <header class="tastehead"><button class="gbtn" data-act="tasteback" aria-label="Back">${ICON.back}</button>
        <span class="eyebrow">${step + 1} of ${TASTE_STEPS.length}</span><button class="linkbtn" data-act="tastenext" data-skip="1">Skip</button></header>
      <div class="tasteprog"><i style="width:${((step + 1) / TASTE_STEPS.length) * 100}%"></i></div>
      <div class="tastebody enter-${S.taste.dir > 0 ? 'fwd' : 'back'}">
        <h1 class="tasteq">${esc(q.q)}</h1><p class="s tastehint">${q.single ? 'Choose one' : 'Choose as many as you like'}</p>
        <div class="tasteopts${q.single ? ' single' : ''}">${opts}</div>
        ${q.notes ? `<label class="tastenotes"><span class="eyebrow">Anything else?</span>
          <textarea id="taste-notes" rows="3" data-act="tastenotes" placeholder="Dietary needs, who you travel with, things you love or avoid">${esc(p.notes || '')}</textarea></label>` : ''}
      </div>
      <div class="tastefoot"><button class="btn wide" data-act="tastenext">${last ? 'Save my taste' : 'Continue'}</button></div></div>`;
  },

  async map() {
    const [trips, places] = await Promise.all([cachedTrips(), cachedPlaces()]);
    if (!S.mapTrip || (S.mapTrip !== 'all' && !trips.some((t) => t.id === S.mapTrip))) S.mapTrip = trips[0] ? trips[0].id : 'all';
    const shown = S.mapTrip === 'all' ? places : places.filter((p) => p.trip_id === S.mapTrip);
    const chips = `<div class="mapchips top">${[{ id: 'all', name: 'All' }, ...trips].map((t) =>
      `<button class="mapchip ${S.mapTrip === t.id ? 'on' : ''}" data-act="maptrip" data-id="${t.id}" aria-pressed="${S.mapTrip === t.id}">${esc(t.name)}${t.place_count != null ? ` · ${t.place_count}` : ''}</button>`).join('')}</div>`;
    return {
      html: `<h1 class="vh">All places</h1><div class="map fill"><div id="all-map" style="position:absolute;inset:0"></div>${trips.length ? chips : ''}
        ${!places.length ? '<div class="mapnote">No places yet. Share a reel to start.</div>' : ''}</div>`,
      after: () => renderMap($('#all-map'), shown, { popup: popupHtml, newIds: S.newIds, pad: { top: 90, bottom: 120 } }),
    };
  },

  async imports() {
    revalidate('jobs', loadJobs);
    schedulePoll();
    return `${navbar('Imports', { right: addButton })}
      <h1 class="largetitle" data-anchor>Imports</h1>
      ${S.jobs.length ? `<div class="section"><div class="group tiles">${S.jobs.map(jobRow).join('')}</div>
        <div class="section-f">Tap a finished import to open its trip.</div></div>`
        : emptyState('blue', 'tray', 'Nothing imported yet', 'Reels you share to TripIt show up here while they’re processed.')}`;
  },

  async settings() {
    if (!S.config) { S.config = await api('/v1/config'); configureMaps({ googleMapsKey: S.config.google_maps_key }); }
    if (!S.profile) await loadProfile().catch(() => {});
    const origin = location.origin;
    const key = getKey();
    const geocoder = { google: 'Google Places', openstreetmap: 'OpenStreetMap', none: 'Off' }[S.config.geocoder] || S.config.geocoder;
    const copyLine = (value, label) => `<div class="copyline"><code>${esc(value)}</code><button class="copybtn" data-act="copy" data-value="${esc(value)}" aria-label="Copy ${label}">Copy</button></div>`;
    const push = await pushState();
    const pushNote = {
      install: 'On iPhone, notifications work once TripIt is on your Home Screen (see below). Open it from there, then turn this on.',
      denied: 'Notifications are blocked for TripIt. Turn them on in Settings → Notifications → TripIt.',
      unsupported: 'This browser can’t show notifications from TripIt.',
      off: 'Get a notification when a reel you shared has been turned into places, or if it couldn’t be read.',
      on: 'You’ll get a notification when each shared reel’s places are saved.',
    }[push];
    return `${navbar('Settings')}<h1 class="largetitle" data-anchor>Settings</h1>

      <div class="section"><div class="section-h">Personal</div><div class="group tiles">
        <a class="row" href="#/taste">${tile('gold', 'sparkle')}<span class="main"><span class="t">Your travel taste</span>
          <span class="s">${esc(tasteSummary(S.profile) || 'Tailors your edits, briefings and concierge')}</span></span>${ICON.chev}</a>
      </div></div>

      <div class="section"><div class="section-h">Notifications</div><div class="group tiles">
        <label class="row" for="push-toggle">${tile('red', 'bell')}<span class="main"><span class="t">Import notifications</span></span>
          <input class="switch" type="checkbox" id="push-toggle" data-act="pushtoggle" ${push === 'on' ? 'checked' : ''} ${['on', 'off'].includes(push) ? '' : 'disabled'}></label>
        ${push === 'on' ? `<button class="row" data-act="pushtest">${tile('gray', 'bell')}<span class="main"><span class="t link">Send a test notification</span></span></button>` : ''}
      </div><div class="section-f">${pushNote}</div></div>

      <div class="section"><div class="section-h">Offline</div><div class="group tiles">
        <div class="row">${tile('teal', 'offline')}<span class="main"><span class="t">Works without signal</span>
          <span class="s">Trips you open are kept on this phone, with their photos and the map areas you’ve viewed. Today’s trip is saved automatically.</span></span></div>
      </div><div class="section-f">To save a whole trip before you go, open it and choose ••• → Save for offline.</div></div>

      <div class="section"><div class="section-h">Share from TikTok &amp; Instagram</div><div class="group">
        <div class="row">${tile('indigo', 'share', 'md')}<span class="main"><span class="t b">iPhone share button</span><span class="s">A one-time shortcut in the Shortcuts app</span></span></div>
        <ol class="steps">
          <li>Open the <b>Shortcuts</b> app, tap <b>+</b> and name the shortcut <b>TripIt</b>.</li>
          <li>Tap the <b>ⓘ</b> button (or the name at the top) and turn on <b>Show in Share Sheet</b>. Tap <b>Done</b>.</li>
          <li>At the top it now says “Receive <i>Any</i> input from Share Sheet”. Tap <i>Any</i> and keep only <b>URLs</b> and <b>Text</b>.</li>
          <li>Add the action <b>Get Contents of URL</b>. Set the URL to the address below.</li>
          <li>Tap the <b>›</b> arrow on that action: set <b>Method</b> to <b>POST</b>; under <b>Headers</b> add <span class="kbd">X-API-Key</span> with your key below; set <b>Request Body</b> to <b>JSON</b> and add a <b>Text</b> field named <span class="kbd">url</span> whose value is the <b>Shortcut Input</b> variable.</li>
          <li>Optional: add <b>Show Notification</b> with the text “Saved to TripIt”.</li>
          <li>In TikTok tap <b>Share → More (•••)</b>, or in Instagram tap the <b>paper plane → Share to…</b>, then choose <b>TripIt</b>. The first time, you may need to scroll the app row and add TripIt to your favorites.</li>
        </ol>
        <div class="sublabel">Shortcut URL</div>${copyLine(`${origin}/v1/jobs`, 'shortcut URL')}
        <div class="sublabel">X-API-Key</div>${key ? copyLine(key, 'API key') : '<div class="copyline"><span class="s">This server doesn’t require a key.</span></div>'}
      </div>
      <div class="section-f">Simpler but opens TripIt each time: make the shortcut a single <b>Open URLs</b> action with <span class="kbd">${esc(origin)}/share?url=</span> followed by the <b>Shortcut Input</b> variable. It opens in Safari, so sign in there once too.</div></div>

      <div class="section"><div class="section-h">Home Screen</div><div class="group">
        <div class="row">${tile('blue', 'home', 'md')}<span class="main"><span class="t b">Add TripIt to your Home Screen</span><span class="s">Opens full screen, like an app</span></span></div>
        <ol class="steps">
          <li>Open this page in <b>Safari</b>.</li>
          <li>Tap the <b>Share</b> button, then <b>Add to Home Screen</b>.</li>
          <li>On Android, use Chrome’s <b>Install app</b> and TripIt appears in the share sheet automatically.</li>
        </ol></div></div>

      <div class="section"><div class="section-h">Server</div><div class="group tiles">
        <div class="row">${tile('gray', 'server')}<span class="main"><span class="s">Address</span><span class="t">${esc(origin)}</span></span></div>
        <div class="row">${tile('green', 'pin')}<span class="main"><span class="t">Finding places</span></span><span class="val">${esc(geocoder)}</span></div>
        <div class="row">${tile('orange', 'route')}<span class="main"><span class="t">Travel times</span></span><span class="val">${S.config.routing === 'google' ? 'Google Routes' : 'Estimated'}</span></div>
        <div class="row">${tile('blue', 'map')}<span class="main"><span class="t">Maps in the app</span></span><span class="val">${mapProvider() === 'google' ? 'Google Maps' : 'OpenStreetMap'}</span></div>
        ${key ? `<button class="row" data-act="signout">${tile('red', 'signout')}<span class="main"><span class="t" style="color:var(--danger)">Sign out on this device</span></span></button>` : ''}
      </div></div>`;
  },

  async setup() {
    return `${emptyState('accent', 'map', 'Welcome to TripIt', 'Enter the API key you set as <span class="kbd">APP_API_KEY</span> on your server. You only do this once per device.')}
      <div class="section"><div class="group"><form class="row" data-form="setkey"><span class="inline-form">
        <input class="field" id="key-input" name="key" type="password" placeholder="API key" autocomplete="current-password" aria-label="API key" required>
        <button class="btn small" type="submit">Continue</button></span></form></div>
        <div class="section-f" id="setup-error" role="alert"></div></div>`;
  },

  async add(r) {
    // #/add?url=… lets other apps or shortcuts hand a link to TripIt.
    const url = r.params.get('url') || r.params.get('text') || '';
    if (url) await submitLink(url, r.params.get('text'));
    location.replace('#/');
    return '';
  },
};

function photoCaption(ph) {
  if (ph.source === 'reel') return ph.attribution || 'From the reel';
  if (ph.source === 'google') return ph.attribution ? `Google · ${ph.attribution}` : 'Google';
  return ph.attribution || 'Wikimedia Commons';
}

function hoursSection(p) {
  const h = p.opening_hours;
  if (!h || !h.text || !h.text.length) {
    return `<div class="section"><div class="section-h">Hours</div><div class="group tiles"><div class="row">${tile('orange', 'clock')}
      <span class="s">No opening hours found for this place. Check Google Maps before you go.</span></div></div></div>`;
  }
  const st = openStatus(h);
  const today = mondayIndex(new Date());
  return `<div class="section"><div class="section-h">Hours</div><div class="group tiles">
    ${st ? `<div class="row">${tile('orange', 'clock')}<span class="main"><span class="t hours-${st.state}" style="font-weight:600">${esc(st.label)}</span><span class="s">By this device’s clock</span></span></div>` : ''}
    <div class="row"><span class="main hourlist">${h.text.map((line, i) => `<span class="${h.weekly && i === today ? 'today' : ''}">${esc(line)}</span>`).join('')}</span></div>
  </div><div class="section-f">From ${h.source === 'google' ? 'Google' : 'OpenStreetMap'}. Hours change, so check before you go.</div></div>`;
}

function gettingThere(p) {
  if (!located(p)) return '';
  const times = hereTimes(p.id);
  if (!times) {
    return `<div class="section"><div class="section-h">Getting there</div><div class="group tiles">
      <button class="row" data-act="herePlace" data-id="${p.id}">${tile('blue', 'locate')}<span class="main"><span class="t link">Travel times from my location</span></span></button></div></div>`;
  }
  const rows = MODES.map(([m, label, , apple]) => {
    const t = times[m];
    const value = t ? `${t.estimated ? '≈ ' : ''}${fmtDuration(t.duration_s)} · ${fmtDistance(t.distance_m)}` : (m === 'transit' ? 'Walk instead' : 'No route');
    const links = `<a class="leg-dir" href="${esc(directionsUrl(S.here.coords, p, m))}" target="_blank" rel="noopener">Google</a>${apple ? ` <a class="leg-dir" href="https://maps.apple.com/?saddr=${S.here.coords.latitude},${S.here.coords.longitude}&daddr=${p.latitude},${p.longitude}&dirflg=${apple}" target="_blank" rel="noopener">Apple</a>` : ''}`;
    return `<div class="row">${tile(m, m)}<span class="main"><span class="t" style="font-size:16px">${label}</span><span class="s">${value}</span></span>${links}</div>`;
  }).join('');
  const est = Object.values(times).some((t) => t && t.estimated);
  return `<div class="section"><div class="section-h">Getting there</div><div class="group tiles">${rows}
    <button class="row" data-act="herePlace" data-id="${p.id}">${tile('gray', 'locate')}<span class="main"><span class="t link" style="font-size:16px">Update from my location</span></span></button></div>
    ${est ? '<div class="section-f">Estimates from distance; Directions shows the real route.</div>' : ''}</div>`;
}

function placesList(trip) {
  if (!trip.places.length) return emptyState('gray', 'pinslash', 'No places', 'Places you save from reels appear here.');
  const bar = `<div class="planbar"><span class="planned-by">${S.sel.on ? 'Tick places, then add them to a day' : 'Star the places you love'}</span>
    <button class="linkbtn" data-act="selecttoggle">${S.sel.on ? 'Done' : 'Select'}</button></div>`;
  return bar + CAT_ORDER.filter((c) => trip.places.some((p) => p.category === c)).map((c) => {
    const list = trip.places.filter((p) => p.category === c).sort(byPriority);
    return `<div class="section"><h2 class="section-title">${catTile(c)}${CATS[c]}<span class="count">${list.length}</span></h2>
      <div class="group thumbs">${list.map(placeRow).join('')}</div></div>`;
  }).join('')
    + (trip.reels.length ? `<div class="section"><h2 class="section-title">Saved from</h2><div class="group tiles">${trip.reels.map((r) => `
      ${safeUrl(r.url) ? `<a class="row" href="${esc(r.url)}" target="_blank" rel="noopener">` : '<div class="row">'}${platformTile(platformOf(r.platform || r.url))}
      <span class="main"><span class="t" style="font-size:16px">${esc(r.title)}</span>
      <span class="s">${esc([platformName(r.platform), r.creator ? `@${r.creator}` : '', plural(r.place_count, 'place')].filter(Boolean).join(' · '))}</span></span>${safeUrl(r.url) ? `${ICON.chev}</a>` : '</div>'}`).join('')}</div></div>` : '')
    + selBar();
}

function itinerary(trip) {
  if (!trip.day_count) {
    return emptyState('indigo', 'calendar', 'No itinerary yet',
      `Build it yourself from your ${plural(trip.places.length, 'saved place')}, or let Claude group them by neighborhood and time of day. You can ask Claude to tidy your own plan later.`,
      `<button class="btn" data-act="buildown" data-id="${trip.id}" ${trip.places.length ? '' : 'disabled'}>${ICON.calendarPlus}Build it myself</button>
       <button class="btn tint" data-act="plan" data-id="${trip.id}" ${trip.places.length ? '' : 'disabled'}>${ICON.sparkle}Plan with Claude</button>`);
  }
  const by = trip.planned_by === 'claude'
    ? `<span class="planned-by">${ICON.sparkle}Planned with Claude</span>`
    : trip.planned_by === 'offline' ? '<span class="planned-by">Quick plan grouped by location</span>' : '<span class="planned-by">Your itinerary</span>';
  const active = activeTrip([trip]);
  let html = `${active ? `<a class="todaylink" href="#/today/${trip.id}">${ICON.sun}<span>Day ${active.day} is today. Open the day view</span>${ICON.chev}</a>` : ''}
    <div class="planbar">${by}
    <span class="planlinks"><button class="linkbtn" data-act="tidy" data-id="${trip.id}">Tidy with AI</button>
    <button class="linkbtn" data-act="plan" data-id="${trip.id}">Re-plan</button>
    <button class="linkbtn" data-act="editday">${S.editDay ? 'Done' : 'Edit'}</button></span></div>
    ${S.editDay ? '<div class="section"><div class="section-f" style="padding-top:0">Drag the handles to reorder stops or move them between days.</div></div>' : ''}`;
  if (trip.plan_notes) html += `<div class="section"><div class="group"><div class="notecard">${esc(trip.plan_notes)}</div></div></div>`;
  const mode = currentMode();
  html += `<div class="travelbar">${segControl(`modes:${trip.id}`, MODES.map(([m, label]) => ({
    on: m === mode,
    html: `<button class="${m === mode ? 'on' : ''}" data-act="mode" data-mode="${m}" aria-pressed="${m === mode}" style="--mc: var(--c-${m})">${ICON[m]}<span>${label}</span></button>`,
  })))}
    <button class="gbtn ${S.here ? 'on' : ''}" data-act="fromhere" data-id="${trip.id}" aria-label="${S.here ? 'Update travel times from my location' : 'Travel times from my location'}">${ICON.locate}</button></div>`;
  for (let d = 1; d <= trip.day_count; d++) {
    const list = stops(trip, d);
    const date = dayDate(trip.start_date, d);
    const dayIdx = dayIndexFor(trip, d);
    const locatedList = list.filter(located);
    html += `<div class="section"><div class="dayhead"><div>${date ? `<div class="date">${date}</div>` : ''}<div class="d">Day ${d}</div>
      ${trip.day_titles[d - 1] && trip.day_titles[d - 1] !== `Day ${d}` ? `<div class="dt">${esc(trip.day_titles[d - 1])}</div>` : ''}</div><span class="daytravel" data-day="${d}"></span></div>
      <div class="group${S.editDay ? ' droplist' : ''}" data-day="${d}">${list.map((p, i) => {
        const conflict = slotConflict(p.opening_hours, dayIdx, p.time_of_day, p.start_time);
        const todays = dayIdx != null ? dayHours(p.opening_hours, dayIdx) : null;
        const inner = `<span class="stopnum" style="${cvar(p.category)}">${i + 1}</span>
          ${thumb(p, 52)}
          <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${starMark(p)}${isNew(p)}</span>
          <span class="s">${esc([p.start_time ? fmtClock(p.start_time) : cap(p.time_of_day || ''), CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</span>
          ${todays && !conflict ? `<span class="s">${ICON.clock.replace('<svg', '<svg class="inline-ic"')}${esc(todays)}</span>` : ''}
          ${conflict ? `<span class="warnline">${ICON.warn}${esc(conflict)}${todays && todays !== 'Closed' ? ` (${esc(todays)})` : ''}</span>` : ''}
          ${p.day_note ? `<span class="daynote">${esc(p.day_note)}</span>` : ''}
          ${hereChip(p)}</span>`;
        const next = locatedList[locatedList.indexOf(p) + 1];
        const legRow = located(p) && next && !S.editDay
          ? `<div class="leg" data-day="${d}" data-from="${p.id}" data-to="${next.id}"><span class="spinner" style="width:14px;height:14px"></span></div>` : '';
        return (S.editDay ? dragRow(p, inner) : `<a class="row" href="#/place/${p.id}">${inner}${ICON.chev}</a>`) + legRow;
      }).join('') || `<div class="row dropempty"><span class="s">${S.editDay ? 'Drop a place here' : 'Nothing planned yet.'}</span></div>`}${S.editDay ? '' : `<button class="row addrow" data-act="daypick" data-day="${d}" data-id="${trip.id}"><span class="addic">${ICON.plus}</span><span class="t link">Add places</span></button>`}</div></div>`;
  }
  if (!S.editDay && trip.day_count < 21) {
    html += `<div class="section"><button class="btn tint wide" data-act="daypick" data-day="0" data-id="${trip.id}">${ICON.plus}Add a day</button></div>`;
  }
  html += '<div class="section" id="travel-note" hidden><div class="section-f">Travel times are estimates from distance. Real routes and transit times need a Google key with the Routes API (see the README).</div></div>';
  if (!trip.start_date && trip.places.some((p) => p.opening_hours && p.opening_hours.weekly)) {
    html += '<div class="section"><div class="section-f">Set a start date when you re-plan to check each stop is open on the day it’s scheduled.</div></div>';
  }
  const un = trip.places.filter((p) => p.day_number == null).sort(byPriority);
  if (S.editDay) {
    html += `<div class="section"><h2 class="section-title">Not scheduled<span class="count">${un.length}</span></h2>
      <div class="group droplist" data-day="0">${un.map((p) => dragRow(p, `${thumb(p, 52)}<span class="main"><span class="t">${esc(p.name)}${starMark(p)}</span>
        <span class="s">${esc(CATS[p.category])}</span></span>`)).join('')}<div class="row dropempty"><span class="s">Drag here to take a stop off the plan</span></div></div></div>`;
  } else if (un.length) {
    html += `<div class="section"><h2 class="section-title">Not scheduled<span class="count">${un.length}</span></h2><div class="group thumbs">${un.map(placeRow).join('')}</div></div>`;
  }
  html += '<div class="section"><div class="section-f">Open a place to set an exact time, like a reservation.</div></div>';
  return html;
}

function dragRow(p, inner) {
  return `<div class="row dragrow" data-drag-id="${p.id}">${inner}
    <button class="handle" aria-label="Reorder ${esc(p.name)}. Use the up and down arrow keys to move it.">${ICON.grip}</button></div>`;
}

/** Called by drag.js when a stop is dropped in a new spot (day 0 = not scheduled). */
async function onItineraryDrop(placeId, day, index) {
  const r = route();
  if (r.name !== 'trip') return;
  try {
    S.trip[r.id] = await api(`/v1/trips/${r.id}/move`, { method: 'POST', body: { place_id: placeId, day, index } });
    fetchedAt.trips = 0;
    S.focusHandle = placeId;
    render();
  } catch (e) {
    toast(e.message, true);
    render();
  }
}

function popupHtml(p) {
  return `<strong>${esc(p.name)}</strong><br><span style="color:var(--secondary);font-size:13px">${esc(CATS[p.category])}${p.neighborhood ? ` · ${esc(p.neighborhood)}` : ''}</span>
    <a class="popup-link" href="#/place/${p.id}">Details ›</a>`;
}

// ---------- Sheets & toasts ----------

function renderOverlay() {
  const sh = S.sheet;
  let html = '';
  if (sh) {
    const enter = sh.shown ? '' : ' enter';
    if (sh.type === 'photos') {
      const photos = sh.place.photos;
      const ph = photos[sh.index];
      html = `<div class="viewer${enter}" role="dialog" aria-label="Photos of ${esc(sh.place.name)}">
        <img src="${esc(photoUrl(ph, 1600))}" alt="${esc(sh.place.name)}">
        <div class="viewer-top"><span>${sh.index + 1} / ${photos.length}</span><button class="viewer-btn" data-act="close" aria-label="Close">${ICON.close}</button></div>
        ${photos.length > 1 ? `<button class="viewer-btn viewer-prev" data-act="photostep" data-d="-1" aria-label="Previous photo">${ICON.back}</button>
          <button class="viewer-btn viewer-next" data-act="photostep" data-d="1" aria-label="Next photo">${ICON.fwd}</button>` : ''}
        <div class="viewer-cap">${esc(sh.place.name)} · ${esc(photoCaption(ph))}</div></div>`;
    } else if (sh.type === 'actions') {
      html = `<div class="dim${enter}" data-act="close"></div><div class="actionsheet${enter}" role="dialog" aria-label="${esc(sh.title || 'Actions')}">
        <div class="group">${sh.title ? `<div class="head">${esc(sh.title)}</div>` : ''}
        ${sh.actions.map((a, i) => `<button class="row ${a.destructive ? 'destructive' : ''}" data-act="action" data-index="${i}">${esc(a.label)}</button>`).join('')}</div>
        <div class="group"><button class="row cancel" data-act="close">Cancel</button></div></div>`;
    } else {
      html = `<div class="dim${enter}" data-act="close"></div><div class="sheet${enter}" role="dialog" aria-label="${esc(sh.title)}"><div class="grab"></div>
        <div class="sheet-head"><button class="gbtn" data-act="close" aria-label="Cancel">${ICON.close}</button>
        <div class="title">${esc(sh.title)}</div>
        ${sh.busy ? '<span class="spinner"></span>' : sh.confirm ? `<button class="gbtn tint" data-act="sheetok" aria-label="${esc(sh.confirm)}">${ICON.done}</button>` : '<span></span>'}</div>
        <div class="sheet-body">${sh.body()}</div></div>`;
    }
  }
  overlay.innerHTML = html;
  if (sh) sh.shown = true;
  const first = overlay.querySelector('.sheet input:not([type=checkbox]), .sheet textarea');
  if (first && sh && !sh.focused) { first.focus(); sh.focused = true; }
}

/** Moves the nodes that are going away into a layer of their own that animates out and removes itself. */
function animateOut(nodes, ms = 320) {
  if (!nodes.length) return;
  if (reducedMotion.matches) { nodes.forEach((n) => n.remove()); return; }
  const ghost = document.createElement('div');
  ghost.className = 'ghost';
  ghost.setAttribute('aria-hidden', 'true');
  nodes.forEach((n) => ghost.appendChild(n));
  document.body.appendChild(ghost);
  setTimeout(() => ghost.remove(), ms);
}

function openSheet(sheet) { S.sheet = sheet; renderOverlay(); }
function closeSheet() {
  animateOut([...overlay.children]);
  S.sheet = null;
  renderOverlay();
}

let toastTimer;
function toast(text, error = false) {
  animateOut([...toasts.children]);
  toasts.innerHTML = `<div class="toast ${error ? 'err' : ''}" role="status">${error ? ICON.warn : ICON.check}<span>${esc(text)}</span></div>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => animateOut([...toasts.children]), error ? 4000 : 2600);
}

const REEL_LINK = /^https?:\/\/([a-z0-9-]+\.)*(tiktok\.com|instagram\.com|instagr\.am|youtube\.com|youtu\.be)\//i;
const MAP_LINK = /^https?:\/\/((www\.|maps\.)?google\.[a-z.]+\/maps|maps\.app\.goo\.gl\/|goo\.gl\/maps|maps\.apple\.com\/|maps\.apple\/)/i;
const findLink = (text) => (text.match(/https?:\/\/[^\s<>"']+/) || [null])[0];

/** One sheet for every way to add: a reel link, a Google/Apple Maps link, a place name, or screenshots. */
function addSheet({ tripId = '' } = {}) {
  const st = { text: '', trip: tripId, results: '', hint: '' };
  openSheet({
    type: 'form', title: 'Add', confirm: 'Add', st,
    body: () => `<div class="section"><div class="group"><label class="row searchrow" for="add-input">${ICON.search}
        <input class="field" id="add-input" type="text" data-act="addinput" value="${esc(st.text)}" placeholder="Paste a link or search for a place"
          autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go" aria-label="Link or place name"></label></div>
        <div class="section-f" id="add-hint">${st.hint || 'TikTok, Instagram and YouTube links find every place in the video. Google Maps and Apple Maps links add that place.'}</div></div>
      <div id="add-results">${st.results}</div>
      <div class="section"><div class="group tiles">
        <label class="row" for="add-trip">${tile('blue', 'trips')}<span class="main"><span class="t">Trip</span></span>
          <select class="select" id="add-trip" data-act="addtrip">
            <option value="">Choose by location</option>
            ${(S.trips || []).map((t) => `<option value="${t.id}" ${t.id === st.trip ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}
          </select></label>
        <button class="row" data-act="pickshots">${tile('pink', 'photo')}<span class="main"><span class="t">Choose screenshots</span>
          <span class="s">Of a post, a map or an article</span></span>${ICON.chev}</button>
      </div><input type="file" id="shots-input" data-act="shots" accept="image/*" multiple hidden></div>`,
    async ok() {
      const text = st.text.trim();
      const link = findLink(text);
      if (link && REEL_LINK.test(link)) { closeSheet(); await submitLink(text); go('#/'); return; }
      if (link && MAP_LINK.test(link)) { await addPlace('/v1/places/from-link', { url: link, trip_id: st.trip || null }); return; }
      if (link) { toast('That link isn’t from TikTok, Instagram, YouTube or a maps app', true); return; }
      const first = $('#add-results [data-act="addresult"]');
      if (first) await addPlace('/v1/places', { candidate_id: first.dataset.id, trip_id: st.trip || null });
      else if (text) await addByName(text, st.trip);
    },
  });
}

let searchSeq = 0;
let searchTimer;
function addInputChanged(value) {
  const st = S.sheet && S.sheet.st;
  if (!st) return;
  st.text = value;
  const text = value.trim();
  const link = findLink(text);
  const show = (results, hint) => {
    st.results = results;
    if (hint !== undefined) st.hint = hint;
    const box = $('#add-results');
    if (box) box.innerHTML = results;
    const hintEl = $('#add-hint');
    if (hintEl && hint !== undefined) hintEl.innerHTML = hint || 'TikTok, Instagram and YouTube links find every place in the video. Google Maps and Apple Maps links add that place.';
  };
  clearTimeout(searchTimer);
  searchSeq++;
  if (!text) { show('', ''); return; }
  if (link) {
    const reel = REEL_LINK.test(link);
    const map = MAP_LINK.test(link);
    const label = reel ? `Find the places in this ${platformName(platformOf(link))} post` : map ? 'Add the place from this map link' : '';
    show(label ? `<div class="section"><div class="group tiles"><button class="row" data-act="sheetok">${reel ? platformTile(platformOf(link)) : tile('green', 'map')}
      <span class="main"><span class="t">${label}</span><span class="s clip">${esc(link.replace(/^https?:\/\/(www\.)?/, ''))}</span></span>${ICON.chev}</button></div></div>` : '',
    label ? '' : 'That link isn’t from TikTok, Instagram, YouTube or a maps app.');
    return;
  }
  if (text.length < 2) return;
  const seq = searchSeq;
  searchTimer = setTimeout(async () => {
    show(`<div class="section"><div class="group"><div class="row"><span class="spinner"></span><span class="s">Searching…</span></div></div></div>`);
    let found = [];
    let error = '';
    try {
      found = await api('/v1/places/search', { method: 'POST', body: { query: text, trip_id: st.trip || null } });
    } catch (e) { error = e.message; }
    if (seq !== searchSeq || !S.sheet || S.sheet.st !== st) return;
    const rows = found.map((c) => `<button class="row" data-act="addresult" data-id="${esc(c.candidate_id)}">${catTile(c.category)}
      <span class="main"><span class="t">${esc(c.name)}</span>${c.address ? `<span class="s clip">${esc(c.address)}</span>` : ''}</span>${ICON.plus.replace('<svg', '<svg class="addplus"')}</button>`).join('');
    show(`<div class="section"><div class="group tiles">${rows}
      <button class="row" data-act="addname">${tile('gray', 'pin')}<span class="main"><span class="t">Add “${esc(text)}”</span>
        <span class="s">${found.length ? 'None of these: add it by name' : error ? esc(error) : 'No matches on the map. Add it by name and pin it later.'}</span></span></button></div></div>`);
  }, 350);
}

async function addPlace(path, body) {
  S.sheet.busy = true; renderOverlay();
  try {
    const res = await api(path, { method: 'POST', body });
    const trip = await loadTrip(res.place.trip_id);
    fetchedAt.trips = 0;
    closeSheet();
    toast(res.created ? `Added ${res.place.name} to ${trip.name}` : `${res.place.name} is already in ${trip.name}`);
    go(`#/place/${res.place.id}`);
  } catch (e) {
    if (S.sheet) { S.sheet.busy = false; renderOverlay(); }
    toast(e.message, true);
  }
}

function addByName(name, tripId) {
  if (tripId) return addPlace('/v1/places', { name, trip_id: tripId });
  closeSheet();
  openSheet({
    type: 'form', title: `Add ${name}`, confirm: 'Add', st: { city: '' },
    body: () => `<div class="section"><div class="section-h">Which city is it in?</div><div class="group"><div class="row">
      <input class="field" id="add-city" placeholder="e.g. Lisbon" autocomplete="off" aria-label="City"></div></div>
      <div class="section-f">It joins that city’s trip, or starts a new one. Pick a trip in the Add sheet to skip this.</div></div>`,
    async ok() {
      const city = $('#add-city').value.trim();
      if (city) await addPlace('/v1/places', { name, city });
    },
  });
}

async function addScreenshots(files) {
  const list = [...files].slice(0, 10);
  if (!list.length) return;
  const note = S.sheet && S.sheet.st && !findLink(S.sheet.st.text) ? S.sheet.st.text.trim() : '';
  closeSheet();
  toast(`Reading ${plural(list.length, 'screenshot')}…`);
  try {
    const images = [];
    for (const f of list) images.push(await toJpegDataUrl(f));
    const job = await api('/v1/jobs/screenshots', { method: 'POST', body: { images, note: note || null } });
    S.jobs = [job, ...S.jobs.filter((j) => j.id !== job.id)];
    schedulePoll(true);
    go('#/imports');
  } catch (e) {
    toast(e.message, true);
  }
}

function planSheet(trip) {
  const st = {
    days: trip.day_count || Math.max(1, Math.min(7, Math.ceil(trip.places.length / 4))),
    hasStart: !!trip.start_date,
    start: trip.start_date || nextFriday(),
    prefs: '',
  };
  openSheet({
    type: 'form', title: trip.day_count ? 'Re-plan trip' : 'Plan my trip', confirm: 'Plan', st,
    body: () => `<div class="section"><div class="group tiles">
        <div class="row">${tile('indigo', 'calendar')}<span class="main"><span class="t">${plural(st.days, 'day')}</span></span>
          <span class="stepper"><button type="button" data-act="days" data-d="-1" aria-label="Fewer days">−</button><button type="button" data-act="days" data-d="1" aria-label="More days">+</button></span></div>
        <label class="row" for="start-toggle">${tile('red', 'clock')}<span class="main"><span class="t">Set start date</span></span>
          <input class="switch" type="checkbox" id="start-toggle" data-act="starttoggle" ${st.hasStart ? 'checked' : ''}></label>
        ${st.hasStart ? `<div class="row">${tile('orange', 'plane')}<label class="main" for="start-date"><span class="t">Start</span></label><input class="datefield" type="date" id="start-date" data-act="startdate" value="${st.start}"></div>` : ''}
      </div><div class="section-f">${plural(trip.places.length, 'saved place')} in ${esc(trip.city)}. Claude groups nearby places and puts meals at sensible times. It can take up to a minute.</div></div>
      <div class="section"><div class="section-h">Anything to keep in mind?</div><div class="group"><div class="row">
        <input class="field" id="prefs" data-act="prefs" placeholder="e.g. slow mornings, vegetarian, museums on day 1" value="${esc(st.prefs)}" aria-label="Preferences"></div></div></div>`,
    async ok() {
      S.sheet.busy = true; renderOverlay();
      try {
        const res = await api(`/v1/trips/${trip.id}/plan`, {
          method: 'POST',
          body: { days: st.days, start_date: st.hasStart ? st.start : null, preferences: st.prefs || null },
        });
        S.trip[trip.id] = res;
        S.mapDay[trip.id] = 0;
        fetchedAt.trips = 0;
        closeSheet();
        toast(res.planned_by === 'claude' ? `Planned ${plural(res.day_count, 'day')} with Claude` : 'Made a quick plan by location (Claude unavailable)');
        go(`#/trip/${trip.id}/itinerary`);
      } catch (e) {
        S.sheet.busy = false; renderOverlay();
        toast(e.message, true);
      }
    },
  });
}

/** Brings a trip's places into the caches after the itinerary changed on the server. */
function syncTrip(res) {
  S.trip[res.id] = res;
  if (S.places) {
    const fresh = new Map(res.places.map((p) => [p.id, p]));
    S.places = S.places.map((p) => fresh.get(p.id) || p);
  }
  fetchedAt.trips = 0;
}

async function addToDay(tripId, ids, day) {
  const res = await api(`/v1/trips/${tripId}/add-to-day`, { method: 'POST', body: { place_ids: ids, day } });
  syncTrip(res);
  toast(`Added ${plural(ids.length, 'place')} to Day ${day || res.day_count}`);
  resetSel();
  render();
}

/** After ticking places in a list: which day do they go on? */
async function addSelectedSheet() {
  const ids = [...S.sel.picked];
  const tripId = selTripId();
  if (!ids.length || !tripId) return;
  const trip = await cachedTrip(tripId);
  const title = (d) => (trip.day_titles[d - 1] && trip.day_titles[d - 1] !== `Day ${d}` ? ` · ${trip.day_titles[d - 1]}` : '');
  const actions = Array.from({ length: trip.day_count }, (_, i) => i + 1).map((d) => ({
    label: `Day ${d}${title(d)} (${plural(stops(trip, d).length, 'stop')})`,
    run: () => addToDay(trip.id, ids, d),
  }));
  if (trip.day_count < 21) actions.push({ label: trip.day_count ? `New day (Day ${trip.day_count + 1})` : 'Day 1', run: () => addToDay(trip.id, ids, null) });
  openSheet({ type: 'actions', title: `Add ${plural(ids.length, 'place')} to…`, actions });
}

/** From the itinerary: tick places to put on a day (day 0 = a new day at the end). */
function pickPlacesSheet(trip, day) {
  const target = day || trip.day_count + 1;
  const st = { picked: new Set() };
  const candidates = trip.places.filter((p) => p.day_number !== target)
    .sort((a, b) => (a.day_number != null) - (b.day_number != null) || (Number(b.must_do) - Number(a.must_do)) || byPriority(a, b)
      || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
  openSheet({
    type: 'form', title: day ? `Add to Day ${day}` : `New day ${target}`, confirm: 'Add', st,
    body: () => (candidates.length
      ? `<div class="section"><div class="group thumbs">${candidates.map((p) => `
        <button class="row prow sel" data-act="sheetpick" data-id="${p.id}" aria-pressed="false"><span class="check" aria-hidden="true"></span>${thumb(p, 44)}
          <span class="main"><span class="t">${esc(p.name)}${starMark(p)}</span>
          <span class="s">${esc([CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}${dayChip(p)}</span></span></button>`).join('')}</div>
        <div class="section-f">Places already on another day move to this one.</div></div>`
      : '<div class="section"><div class="section-f">Every saved place is already on this day.</div></div>'),
    async ok() {
      closeSheet();
      if (st.picked.size) await addToDay(trip.id, [...st.picked], day || null);
    },
  });
}

const TIDY_IDEAS = ['Group stops by neighborhood', 'Make it more relaxed', 'Put meals at mealtimes', 'Start later in the morning'];
function tidySheet(trip) {
  const st = { text: '' };
  openSheet({
    type: 'form', title: 'Tidy with AI', confirm: 'Tidy', st,
    body: () => `<div class="section"><div class="section-h">What should change? (optional)</div><div class="group"><div class="row">
        <input class="field" id="tidy-text" data-act="tidytext" placeholder="e.g. make day 2 more relaxed" value="${esc(st.text)}" aria-label="What should change"></div></div>
      <div class="fchips wrap">${TIDY_IDEAS.map((t) => `<button class="fchip" data-act="tidysuggest" data-text="${esc(t)}">${esc(t)}</button>`).join('')}</div>
      <div class="section-f">Keeps each place on the day you chose, orders the stops to cut down on travel and suggests times. It can take up to a minute.</div></div>`,
    async ok() {
      S.sheet.busy = true; renderOverlay();
      try {
        const res = await api(`/v1/trips/${trip.id}/tidy`, { method: 'POST', body: { instruction: st.text.trim() || null } });
        syncTrip(res);
        closeSheet();
        toast(res.planned_by === 'claude' ? 'Tidied with Claude' : 'Ordered by location and time (Claude unavailable)');
        render();
      } catch (e) {
        S.sheet.busy = false; renderOverlay();
        toast(e.message, true);
      }
    },
  });
}

function shareText(trip) {
  const link = (p) => mapsLinks(p, trip).google;
  const line = (p) => `• ${p.name} (${CATS[p.category]}) ${link(p)}`;
  const lines = [`${trip.name} — saved with TripIt`, ''];
  if (trip.day_count) {
    for (let d = 1; d <= trip.day_count; d++) {
      const list = stops(trip, d);
      if (!list.length) continue;
      lines.push(`Day ${d}: ${trip.day_titles[d - 1] || ''}`);
      list.forEach((p) => lines.push(line(p)));
      lines.push('');
    }
    const un = trip.places.filter((p) => p.day_number == null);
    if (un.length) { lines.push('Also saved'); un.forEach((p) => lines.push(line(p))); }
  } else trip.places.forEach((p) => lines.push(line(p)));
  return lines.join('\n').trim();
}

async function shareTrip(trip) {
  const text = shareText(trip);
  if (navigator.share) {
    try { await navigator.share({ title: trip.name, text }); return; } catch (e) { if (e.name === 'AbortError') return; }
  }
  openSheet({
    type: 'form', title: `Share ${trip.name}`, confirm: 'Copy',
    body: () => `<div class="section"><div class="group"><pre id="share-text" style="margin:0;padding:14px 16px;white-space:pre-wrap;font-family:var(--mono);font-size:12px;line-height:1.5;overflow-wrap:anywhere">${esc(text)}</pre></div>
      <div class="section-f">Each place links to Google Maps, so friends can save it there.</div></div>`,
    async ok() { await copy(text, $('#share-text')); closeSheet(); },
  });
}

function shareMenu(t) {
  const url = t.share_token ? `${location.origin}/s/${t.share_token}` : null;
  const actions = [
    url
      ? { label: 'Share link', run: () => shareUrl(t, url) }
      : { label: 'Create a share link', run: () => createShareLink(t) },
    { label: 'Send as text', run: () => shareTrip(t) },
    { label: 'Add to Calendar', run: () => exportTrip(t, 'ics') },
    { label: 'Google My Maps file (.kml)', run: () => exportTrip(t, 'kml') },
  ];
  if (url) {
    actions.push({ label: 'Turn off share link', destructive: true, run: async () => {
      await api(`/v1/trips/${t.id}/share`, { method: 'DELETE' });
      t.share_token = null;
      fetchedAt.trips = 0;
      toast('Share link turned off');
      render();
    } });
  }
  openSheet({ type: 'actions', title: url ? 'Anyone with the link can see this trip, but not your notes.' : `Share ${t.name}`, actions });
}

/** Must run straight from a tap: Safari only opens the share sheet for a user gesture. */
function shareUrl(t, url) {
  if (navigator.share) {
    navigator.share({ title: t.name, text: `${t.name}: my trip on TripIt`, url }).catch((e) => {
      if (e.name !== 'AbortError') copy(url);
    });
  } else {
    copy(url);
  }
}

async function createShareLink(t) {
  try {
    const res = await api(`/v1/trips/${t.id}/share`, { method: 'POST' });
    t.share_token = res.token;
    fetchedAt.trips = 0;
    const url = location.origin + res.path;
    render();
    // The tap that started this has been used up by the request, so ask for one more to share.
    openSheet({
      type: 'form', title: 'Share link ready', confirm: navigator.share ? 'Share' : 'Copy',
      body: () => `<div class="section"><div class="group">${tile('green', 'link', 'lg').replace('class="tile', 'class="tile centered-tile')}
        <div class="copyline"><code>${esc(url)}</code><button class="copybtn" data-act="copy" data-value="${esc(url)}" aria-label="Copy link">Copy</button></div></div>
        <div class="section-f">Friends see the map, the itinerary and each place, but not your notes. Turn the link off any time from Share.</div></div>`,
      ok() { closeSheet(); shareUrl(t, url); },
    });
  } catch (e) {
    toast(e.message, true);
  }
}

async function exportTrip(t, format) {
  // Open the tab during the tap so it isn't blocked, then point it at the file once the link is ready.
  const win = format === 'ics' ? window.open('', '_blank') : null;
  try {
    const { url } = await api(`/v1/trips/${t.id}/export-link?format=${format}`, { method: 'POST' });
    if (win) { win.location.href = url; return; }
    if (format === 'ics') { location.href = url; return; }
    const a = document.createElement('a');
    a.href = url;
    a.download = `${t.name}.kml`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast('Import it at mymaps.google.com → Create a new map → Import');
  } catch (e) {
    if (win) win.close();
    toast(e.message, true);
  }
}

/** Fetches a trip, its travel times and photos so the service worker keeps them for offline use. */
async function saveOffline(tripId, quiet = false) {
  if (!('serviceWorker' in navigator) || !navigator.serviceWorker.controller) {
    if (!quiet) toast('Offline saving needs TripIt opened from the Home Screen or a recent browser', true);
    return;
  }
  const trip = await loadTrip(tripId);
  const urls = [];
  if (trip.cover_photo) urls.push(photoUrl(trip.cover_photo, 900));
  trip.places.forEach((p) => (p.photos || []).forEach((ph, i) => {
    if (i === 0) urls.push(photoUrl(ph, 240));
    urls.push(photoUrl(ph, 1000));
  }));
  for (let d = 1; d <= trip.day_count; d++) urls.push(`/v1/trips/${tripId}/days/${d}/legs`);
  if (!quiet) toast(`Saving ${trip.name} for offline…`);
  let failed = 0;
  for (let i = 0; i < urls.length; i += 6) {
    await Promise.all(urls.slice(i, i + 6).map((u) => fetch(u, u.startsWith('/v1/trips/') ? { headers: { 'X-API-Key': getKey() } } : {})
      .then((r) => { if (!r.ok && r.type !== 'opaque') failed++; }).catch(() => { failed++; })));
  }
  try { localStorage.setItem(`tripit.saved.${tripId}`, String(Date.now())); } catch { /* fine */ }
  if (!quiet) toast(failed ? `Saved ${trip.name}, but ${plural(failed, 'item')} couldn’t be downloaded` : `${trip.name} is ready offline`, failed > 0);
}

function autoSaveToday() {
  const active = activeTrip(S.trips);
  if (!active || isOffline()) return;
  let last = 0;
  try { last = Number(localStorage.getItem(`tripit.saved.${active.trip.id}`)) || 0; } catch { /* fine */ }
  if (Date.now() - last > 12 * 3600 * 1000) saveOffline(active.trip.id, true).catch(() => {});
}

// "Visited" taps made without signal wait here and sync when the connection is back.
const OUTBOX = 'tripit.outbox';
function readOutbox() {
  try { return JSON.parse(localStorage.getItem(OUTBOX)) || {}; } catch { return {}; }
}
function writeOutbox(box) {
  try { localStorage.setItem(OUTBOX, JSON.stringify(box)); } catch { /* kept for this visit only */ }
}
let flushing = false;
async function flushOutbox() {
  const box = readOutbox();
  if (flushing || !Object.keys(box).length) return;
  flushing = true;
  try {
    for (const [id, body] of Object.entries(box)) {
      try {
        await api(`/v1/places/${id}`, { method: 'PATCH', body });
      } catch (e) {
        if (e.status === 0) return; // still offline; try again later
      }
      delete box[id];
      writeOutbox(box);
    }
  } finally {
    flushing = false;
  }
}

function applyLocally(id, changes) {
  for (const t of Object.values(S.trip)) t.places = t.places.map((p) => (p.id === id ? { ...p, ...changes } : p));
  if (S.places) S.places = S.places.map((p) => (p.id === id ? { ...p, ...changes } : p));
}

function renameSheet(trip) {
  openSheet({
    type: 'form', title: 'Rename trip', confirm: 'Save',
    body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="rename" value="${esc(trip.name)}" maxlength="120" aria-label="Trip name"></div></div></div>`,
    async ok() {
      const name = $('#rename').value.trim();
      if (!name) return;
      S.trip[trip.id] = await api(`/v1/trips/${trip.id}`, { method: 'PATCH', body: { name } });
      fetchedAt.trips = 0;
      closeSheet();
      render();
    },
  });
}

async function copy(text, fallbackEl) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copied');
  } catch {
    if (fallbackEl) {
      const range = document.createRange();
      range.selectNodeContents(fallbackEl);
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    }
    toast('Select the text and copy it', true);
  }
}

function nextFriday() {
  const d = new Date();
  d.setDate(d.getDate() + (((5 - d.getDay() + 7) % 7) || 7));
  return d.toISOString().slice(0, 10);
}

// ---------- Imports & polling ----------

async function submitLink(text, sharedText) {
  try {
    const job = await api('/v1/jobs', { method: 'POST', body: { url: text, shared_text: sharedText || null } });
    S.jobs = [job, ...S.jobs.filter((j) => j.id !== job.id)];
    if (job.status === 'done') toast('Already saved. Opening its trip.');
    else toast('Saved. Finding places…');
    schedulePoll(true);
    if (job.status === 'done' && job.trip_id) setTimeout(() => go(`#/trip/${job.trip_id}`), 400);
    return job;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

let pollTimer = null;
function schedulePoll(now = false) {
  if (pollTimer) return;
  if (!now && !S.jobs.some((j) => ACTIVE.has(j.status))) return;
  pollTimer = setTimeout(poll, now ? 1500 : 3000);
}

async function poll() {
  pollTimer = null;
  const before = new Map(S.jobs.map((j) => [j.id, j.status]));
  try {
    await loadJobs();
  } catch {
    pollTimer = setTimeout(poll, 8000); // offline for a moment; keep trying slowly
    return;
  }
  const finished = S.jobs.filter((j) => before.has(j.id) && ACTIVE.has(before.get(j.id)) && !ACTIVE.has(j.status));
  for (const job of finished) {
    if (job.status === 'done') {
      if (job.trip_id) {
        delete fetchedAt[`trip:${job.trip_id}`];
        const trip = await loadTrip(job.trip_id).catch(() => null);
        if (trip) trip.places.filter((p) => new Date(p.created_at) >= new Date(job.created_at)).forEach((p) => S.newIds.add(p.id));
      }
      toast(job.added_places ? `${job.message} · ${plural(job.added_places, 'new place')}` : job.message || 'Import finished');
    } else {
      toast(job.message || 'Import failed', true);
    }
  }
  if (finished.length) {
    await Promise.all([loadTrips(), S.places ? loadPlaces() : null].filter(Boolean)).catch(() => {});
  }
  const r = route();
  if (['trips', 'imports'].includes(r.name) || (finished.length && ['trip', 'map'].includes(r.name))) render({ quiet: true });
  if (S.jobs.some((j) => ACTIVE.has(j.status))) pollTimer = setTimeout(poll, 3000);
}

// ---------- Events ----------

let notesTimer;

async function onAction(act, el) {
  switch (act) {
    case 'back': {
      if (S.navigations > 0) history.back();
      else go(el.dataset.fallback);
      return;
    }
    case 'reload': render(); return;
    case 'add': { const r = route(); addSheet({ tripId: ['trip', 'today'].includes(r.name) ? r.id : '' }); return; }
    case 'addtrip': S.sheet.st.trip = el.value; if (S.sheet.st.text) addInputChanged(S.sheet.st.text); return;
    case 'addresult': await addPlace('/v1/places', { candidate_id: el.dataset.id, trip_id: S.sheet.st.trip || null }); return;
    case 'addname': await addByName(S.sheet.st.text.trim(), S.sheet.st.trip); return;
    case 'pickshots': $('#shots-input').click(); return;
    case 'shots': await addScreenshots(el.files); return;
    case 'close': closeSheet(); return;
    case 'sheetok': if (S.sheet && S.sheet.ok) await S.sheet.ok(); return;
    case 'action': { const a = S.sheet.actions[Number(el.dataset.index)]; closeSheet(); await a.run(); return; }
    case 'days': S.sheet.st.days = Math.max(1, Math.min(14, S.sheet.st.days + Number(el.dataset.d))); renderOverlay(); return;
    case 'starttoggle': S.sheet.st.hasStart = el.checked; renderOverlay(); return;
    case 'startdate': S.sheet.st.start = el.value; return;
    case 'prefs': S.sheet.st.prefs = el.value; return;

    case 'tripmenu': {
      const t = S.trip[el.dataset.id];
      const actions = [
        { label: t.day_count ? 'Re-plan trip' : 'Plan my trip', run: () => planSheet(t) },
        { label: 'Add a place', run: () => addSheet({ tripId: t.id }) },
        { label: 'Save for offline', run: () => saveOffline(t.id) },
        { label: 'Rename', run: () => renameSheet(t) },
        { label: 'Update hours, photos & ratings', run: async () => {
          toast('Looking up hours, photos and ratings…');
          S.trip[t.id] = await api(`/v1/trips/${t.id}/refresh-details`, { method: 'POST' });
          fetchedAt.trips = 0;
          toast('Hours, photos and ratings updated');
          render();
        } },
      ];
      if (t.day_count) actions.push({ label: 'Clear itinerary', destructive: true, run: async () => { S.trip[t.id] = await api(`/v1/trips/${t.id}/plan`, { method: 'DELETE' }); fetchedAt.trips = 0; render(); } });
      actions.push({ label: 'Delete trip', destructive: true, run: () => openSheet({
        type: 'actions', title: `Delete ${t.name} and its ${plural(t.places.length, 'place')}?`,
        actions: [{ label: 'Delete trip', destructive: true, run: async () => {
          await api(`/v1/trips/${t.id}`, { method: 'DELETE' });
          delete S.trip[t.id];
          if (S.trips) S.trips = S.trips.filter((x) => x.id !== t.id);
          fetchedAt.trips = 0;
          toast('Trip deleted');
          go('#/');
        } }],
      }) });
      openSheet({ type: 'actions', actions });
      return;
    }
    case 'plan': planSheet(S.trip[el.dataset.id]); return;
    case 'sharetrip': shareMenu(S.trip[el.dataset.id]); return;
    case 'editday': S.editDay = !S.editDay; render(); return;
    case 'mode': setTravelMode(el.dataset.mode); render(); return;
    case 'dismissinvite': try { localStorage.setItem('tripit.tasteInvite', 'no'); } catch { /* fine */ } render(); return;
    case 'curate': await curate(el.dataset.id); return;
    case 'briefrefresh': {
      const r = route();
      const trip = S.trip[r.id];
      if (!trip) return;
      const active = activeTrip([trip]);
      const day = Math.min(Math.max(1, Number(r.params.get('day')) || (active ? active.day : 1)), trip.day_count);
      const date = active && active.day === day ? isoDate(new Date()) : null;
      el.classList.add('spinning');
      await loadBriefing(trip.id, day, date, `${trip.id}:${day}:${date || ''}`, true);
      return;
    }
    case 'chatprompt': await sendChat(el.dataset.q); return;
    case 'chatnew': writeChat(S.chatTrip, []); render(); return;
    case 'chattrip': S.chatTrip = el.dataset.id || null; render(); return;
    case 'chatapply': await applyChatActions(Number(el.dataset.index)); return;
    case 'chatdismiss': {
      const msgs = readChat(S.chatTrip);
      if (msgs[Number(el.dataset.index)]) msgs[Number(el.dataset.index)].dismissed = true;
      writeChat(S.chatTrip, msgs);
      renderChatLog();
      return;
    }
    case 'tastepick': {
      const { p, step } = S.taste;
      const q = TASTE_STEPS[step];
      const v = el.dataset.value;
      if (q.single) p[q.key] = p[q.key] === v ? null : v;
      else p[q.key] = (p[q.key] || []).includes(v) ? p[q.key].filter((x) => x !== v) : [...(p[q.key] || []), v];
      render();
      return;
    }
    case 'tasteback':
      if (S.taste && S.taste.step > 0) { S.taste.step--; S.taste.dir = -1; render(); return; }
      S.taste = null;
      if (S.navigations > 0) history.back(); else go('#/settings');
      return;
    case 'tastenext': {
      if (S.taste.step < TASTE_STEPS.length - 1) { S.taste.step++; S.taste.dir = 1; render(); return; }
      const notes = $('#taste-notes');
      if (notes) S.taste.p.notes = notes.value.trim() || null;
      const { food, interests, pace, budget, mornings } = S.taste.p;
      S.profile = await api('/v1/profile', { method: 'PUT', body: { food: food || [], interests: interests || [], pace, budget, mornings, notes: S.taste.p.notes } });
      fetchedAt.profile = Date.now();
      S.taste = null;
      toast('Your taste is saved');
      if (S.navigations > 0) history.back(); else go('#/');
      return;
    }
    case 'star': {
      const place = findAnyPlace(el.dataset.id);
      if (!place) return;
      await patchPlace(el.dataset.id, { must_do: !place.must_do });
      toast(place.must_do ? 'Star removed' : 'Starred. It stays at the top of your lists');
      return;
    }
    case 'hometab': S.home.tab = el.dataset.tab; resetSel(); saveHome(); render(); return;
    case 'homecat': S.home.cat = el.dataset.cat; saveHome(); render(); return;
    case 'homestarred': S.home.starred = !S.home.starred; render(); return;
    case 'homeclear': S.home.cat = 'all'; S.home.starred = false; S.home.trip = 'all'; saveHome(); render(); return;
    case 'hometrip': {
      const mark = (on) => (on ? '✓ ' : '');
      openSheet({ type: 'actions', title: 'Show places from', actions: [
        { label: `${mark(S.home.trip === 'all')}All trips`, run: () => { S.home.trip = 'all'; render(); } },
        ...(S.trips || []).map((t) => ({ label: `${mark(S.home.trip === t.id)}${t.name}`, run: () => { S.home.trip = t.id; render(); } })),
      ] });
      return;
    }
    case 'homesort':
      openSheet({ type: 'actions', title: 'Sort by', actions: Object.entries(SORTS).map(([key, { label }]) => ({
        label: `${S.home.sort === key ? '✓ ' : ''}${label}`,
        run: async () => {
          if (key === 'closest') { toast('Finding your location…'); await getPosition(); }
          S.home.sort = key; saveHome(); render();
        },
      })) });
      return;
    case 'selecttoggle': S.sel = { on: !S.sel.on, picked: new Set() }; render(); return;
    case 'pick': {
      const p = findAnyPlace(el.dataset.id);
      if (!p) return;
      if (S.sel.picked.has(p.id)) S.sel.picked.delete(p.id);
      else if (selTripId() && p.trip_id !== selTripId()) { toast('Pick places from one trip at a time', true); return; }
      else S.sel.picked.add(p.id);
      render();
      return;
    }
    case 'selectadd': await addSelectedSheet(); return;
    case 'buildown': resetSel(); S.sel.on = true; S.sel.keep = true; go(`#/trip/${el.dataset.id}`); toast('Tick the places for your first day'); return;
    case 'daypick': pickPlacesSheet(S.trip[el.dataset.id], Number(el.dataset.day)); return;
    case 'sheetpick': {
      const { st } = S.sheet;
      const on = !st.picked.has(el.dataset.id);
      if (on) st.picked.add(el.dataset.id); else st.picked.delete(el.dataset.id);
      el.classList.toggle('picked', on);
      el.setAttribute('aria-pressed', String(on));
      el.querySelector('.check').innerHTML = on ? ICON.done : '';
      return;
    }
    case 'tidy': tidySheet(S.trip[el.dataset.id]); return;
    case 'tidysuggest': S.sheet.st.text = el.dataset.text; renderOverlay(); return;
    case 'settime': await patchPlace(el.dataset.id, el.value ? { start_time: el.value } : { clear_start_time: true }); return;
    case 'cleartime': await patchPlace(el.dataset.id, { clear_start_time: true }); return;
    case 'done': {
      if (navigator.vibrate) navigator.vibrate(10);
      await patchPlace(el.dataset.id, { visited: true });
      return;
    }
    case 'undone': await patchPlace(el.dataset.id, { visited: false }); return;
    case 'todaydir': {
      const place = allPlaces().find((x) => x.id === el.dataset.id);
      const m = MODES.find((x) => x[0] === currentMode()) || MODES[0];
      const dest = located(place) ? `${place.latitude},${place.longitude}` : encodeURIComponent(`${place.name}, ${place.city}`);
      openSheet({
        type: 'actions', title: `${m[1]} to ${place.name}`,
        actions: [
          { label: 'Apple Maps', run: () => window.open(`https://maps.apple.com/?daddr=${dest}${m[3] ? `&dirflg=${m[3]}` : ''}`, '_blank', 'noopener') },
          { label: 'Google Maps', run: () => window.open(`https://www.google.com/maps/dir/?api=1&destination=${dest}&travelmode=${m[2]}`, '_blank', 'noopener') },
        ],
      });
      return;
    }
    case 'pushtoggle': {
      try {
        const state = el.checked ? await enablePush(S.config.push_public_key) : (await disablePush(), 'off');
        if (state === 'on') toast('Notifications are on');
        else if (state === 'denied') toast('Notifications are blocked. Allow them in Settings → Notifications → TripIt.', true);
      } catch (e) {
        toast(e.message || 'Couldn’t turn on notifications', true);
      }
      render();
      return;
    }
    case 'pushtest': {
      const { sent } = await api('/v1/push/test', { method: 'POST' });
      toast(sent ? 'Test sent. It should arrive in a few seconds.' : 'No devices are signed up for notifications', !sent);
      return;
    }
    case 'directions': {
      const place = allPlaces().find((x) => x.id === el.dataset.id);
      const trip = place && S.trip[place.trip_id];
      if (!place) return;
      const links = mapsLinks(place, trip);
      openSheet({
        type: 'actions', title: `Directions to ${place.name}`,
        actions: [
          { label: 'Apple Maps', run: () => window.open(links.appleDir, '_blank', 'noopener') },
          { label: 'Google Maps', run: () => window.open(links.googleDir, '_blank', 'noopener') },
        ],
      });
      return;
    }
    case 'viewphoto': {
      const place = allPlaces().find((x) => x.id === el.dataset.id);
      if (place) openSheet({ type: 'photos', place, index: Number(el.dataset.index) });
      return;
    }
    case 'photostep': {
      const n = S.sheet.place.photos.length;
      S.sheet.index = (S.sheet.index + Number(el.dataset.d) + n) % n;
      renderOverlay();
      return;
    }
    case 'fromhere': {
      const t = S.trip[el.dataset.id];
      el.innerHTML = '<span class="spinner" style="width:16px;height:16px"></span>';
      try {
        await locateMe(t.places);
        toast('Travel times from your location added');
      } finally {
        render();
      }
      return;
    }
    case 'herePlace': {
      const place = allPlaces().find((x) => x.id === el.dataset.id);
      el.querySelector('.t').textContent = 'Locating…';
      try { await locateMe([place]); } finally { render(); }
      return;
    }
    case 'mapday': S.mapDay[el.dataset.trip] = Number(el.dataset.day); render(); return;
    case 'maptrip': S.mapTrip = el.dataset.id; render(); return;

    case 'visited': await patchPlace(el.dataset.id, { visited: el.checked }, false); return;
    case 'setday': await patchPlace(el.dataset.id, { day_number: Number(el.value) }); return;
    case 'settod': await patchPlace(el.dataset.id, el.value ? { time_of_day: el.value } : { clear_time_of_day: true }); return;
    case 'setcat': await patchPlace(el.dataset.id, { category: el.value }); return;
    case 'notes':
      clearTimeout(notesTimer);
      notesTimer = setTimeout(() => patchPlace(el.dataset.id, { user_notes: el.value }, false), 600);
      return;
    case 'relocate': {
      const place = allPlaces().find((p) => p.id === el.dataset.id);
      openSheet({
        type: 'form', title: 'Search again', confirm: 'Find',
        body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="relocate-q" value="${esc(`${place.name}, ${place.city}`)}" aria-label="Search"></div></div>
          <div class="section-f">Add the street or neighborhood to find the right spot.</div></div>`,
        async ok() { const q = $('#relocate-q').value.trim(); closeSheet(); await locate(place.id, q); },
      });
      return;
    }
    case 'askdeleteplace':
      openSheet({
        type: 'actions', title: 'Delete this place?',
        actions: [{ label: 'Delete place', destructive: true, run: async () => {
          await api(`/v1/places/${el.dataset.id}`, { method: 'DELETE' });
          const t = S.trip[el.dataset.trip];
          if (t) t.places = t.places.filter((p) => p.id !== el.dataset.id);
          if (S.places) S.places = S.places.filter((p) => p.id !== el.dataset.id);
          fetchedAt.trips = 0;
          toast('Place deleted');
          go(`#/trip/${el.dataset.trip}`);
        } }],
      });
      return;
    case 'retry': {
      const job = await api(`/v1/jobs/${el.dataset.id}/retry`, { method: 'POST' });
      S.jobs = S.jobs.map((j) => (j.id === job.id ? job : j));
      schedulePoll(true);
      render();
      return;
    }
    case 'copy': await copy(el.dataset.value, el.previousElementSibling); return;
    case 'signout': setKey(''); S.config = null; clearOfflineData(); go('#/setup'); return;
    default:
  }
}

async function patchPlace(id, body, rerender = true) {
  try {
    const place = await api(`/v1/places/${id}`, { method: 'PATCH', body });
    const t = S.trip[place.trip_id];
    if (t) {
      t.places = t.places.map((p) => (p.id === id ? place : p));
      if ('day_number' in body) await loadTrip(place.trip_id); // day count may have changed
    }
    if (S.places) S.places = S.places.map((p) => (p.id === id ? place : p));
    if ('category' in body || 'must_do' in body) fetchedAt.trips = 0;
    if (rerender) render();
  } catch (e) {
    if (e.status === 0 && Object.keys(body).every((k) => k === 'visited')) {
      writeOutbox({ ...readOutbox(), [id]: body });
      applyLocally(id, body);
      toast('Saved on this phone. It syncs when you’re back online.');
      if (rerender) render();
      return;
    }
    toast(e.message, true);
  }
}

async function locate(id, query) {
  try {
    const place = await api(`/v1/places/${id}/locate`, { method: 'POST', body: { query } });
    const t = S.trip[place.trip_id];
    if (t) t.places = t.places.map((p) => (p.id === id ? place : p));
    if (S.places) S.places = S.places.map((p) => (p.id === id ? place : p));
    toast('Pinned on the map');
    render();
  } catch (e) {
    toast(e.message, true);
  }
}

document.addEventListener('click', (ev) => {
  // Segmented controls swap the view in place; they shouldn't stack up history for Back to walk through.
  const segLink = ev.target.closest('.seg-items a[href], a[data-replace]');
  if (segLink) {
    ev.preventDefault();
    const href = segLink.getAttribute('href');
    if (location.hash !== href) location.replace(href);
    return;
  }
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return;
  if (el.tagName === 'A' && el.dataset.act !== 'back') return;
  ev.preventDefault();
  onAction(el.dataset.act, el).catch((e) => toast(e.message || 'Something went wrong', true));
});

document.addEventListener('change', (ev) => {
  const el = ev.target;
  if (el.dataset && el.dataset.act && ['INPUT', 'SELECT'].includes(el.tagName) && el.type !== 'text') {
    onAction(el.dataset.act, el).catch((e) => toast(e.message, true));
  }
});

document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (el.dataset && ['notes', 'prefs'].includes(el.dataset.act)) onAction(el.dataset.act, el);
  if (el.dataset && el.dataset.act === 'addinput') addInputChanged(el.value);
  if (el.dataset && el.dataset.act === 'tastenotes' && S.taste) S.taste.p.notes = el.value;
  if (el.dataset && el.dataset.act === 'tidytext' && S.sheet && S.sheet.st) S.sheet.st.text = el.value;
  if (el.id === 'chat-input') { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
});

document.addEventListener('submit', async (ev) => {
  const form = ev.target.closest('[data-form]');
  if (!form) return;
  ev.preventDefault();
  if (form.dataset.form === 'chat') {
    const input = $('#chat-input');
    const text = input.value;
    input.value = '';
    input.style.height = 'auto';
    await sendChat(text);
    return;
  }
  if (form.dataset.form === 'locate') {
    await locate(form.dataset.id, new FormData(form).get('q'));
  } else if (form.dataset.form === 'setkey') {
    const key = String(new FormData(form).get('key') || '').trim();
    setKey(key);
    try {
      S.config = await api('/v1/config');
      configureMaps({ googleMapsKey: S.config.google_maps_key });
      await start();
    } catch (e) {
      setKey('');
      $('#setup-error').textContent = e.status === 401 ? 'That key didn’t work. Check APP_API_KEY on the server.' : e.message;
    }
  }
});

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing && ev.target.id === 'chat-input') {
    ev.preventDefault();
    ev.target.form.requestSubmit();
    return;
  }
  if (ev.key === 'Escape' && S.sheet) closeSheet();
  if (S.sheet && S.sheet.type === 'photos' && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
    const n = S.sheet.place.photos.length;
    S.sheet.index = (S.sheet.index + (ev.key === 'ArrowRight' ? 1 : -1) + n) % n;
    renderOverlay();
  }
  if (ev.key === 'Enter' && S.sheet && S.sheet.ok && !S.sheet.busy && ev.target.matches('.sheet input.field')) { ev.preventDefault(); S.sheet.ok(); }
});

// Swipe left/right in the photo viewer.
let touchX = null;
document.addEventListener('touchstart', (ev) => {
  touchX = S.sheet && S.sheet.type === 'photos' ? ev.touches[0].clientX : null;
}, { passive: true });
document.addEventListener('touchend', (ev) => {
  if (touchX == null || !S.sheet || S.sheet.type !== 'photos') return;
  const dx = ev.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(dx) < 40) return;
  const n = S.sheet.place.photos.length;
  S.sheet.index = (S.sheet.index + (dx < 0 ? 1 : -1) + n) % n;
  renderOverlay();
}, { passive: true });

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && route().name !== 'setup') { schedulePoll(true); }
});

// ---------- Boot ----------

async function start() {
  // Android share target lands on /share?url=…&text=…
  if (location.pathname === '/share') {
    const params = new URLSearchParams(location.search);
    const shared = params.get('url') || params.get('text') || '';
    history.replaceState(null, '', '/#/');
    if (shared) await submitLink(shared, params.get('text'));
  }
  try { await loadJobs(); } catch { /* shown by the views */ }
  schedulePoll();
  flushOutbox();
  if (route().name === 'setup') location.hash = '#/';
  else render();
  setTimeout(() => { if (S.trips) autoSaveToday(); }, 3000);
}

window.addEventListener('tripit:network', (ev) => {
  S.offline = ev.detail.offline;
  $('#netpill').hidden = !S.offline;
  if (!S.offline) flushOutbox();
});
window.addEventListener('online', () => { flushOutbox(); render({ quiet: true }); });
enableDrag(view, onItineraryDrop);
registerServiceWorker();
// On first launch, what loaded before the service worker took over isn't saved yet: fetch it again through it.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!getKey() && S.config === null) return;
    ['/v1/config', '/v1/trips', '/v1/jobs?limit=40', '/v1/places'].forEach((u) => fetch(u, { headers: { 'X-API-Key': getKey() } }).catch(() => {}));
    autoSaveToday();
  }, { once: true });
}

document.addEventListener('tripit:maps-fallback', () => {
  toast('Google Maps rejected the API key, so OpenStreetMap is shown. Check the key’s website restrictions.', true);
  render();
});

hydrateIcons(document.getElementById('tabbar'));
hydrateIcons(document.getElementById('netpill'));
(async () => {
  try {
    S.config = await api('/v1/config');
    configureMaps({ googleMapsKey: S.config.google_maps_key });
  } catch (e) {
    if (e.status === 401) { location.hash = '#/setup'; render(); return; }
  }
  await start();
})();
