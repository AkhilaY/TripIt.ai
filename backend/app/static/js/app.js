import { api, ApiError, authHeaders, getKey, isOffline, setKey, toNative } from './api.js';
import { enableDrag } from './drag.js';
import { ICON, hydrateIcons } from './icons.js';
import { dayHours, mondayIndex, nextChange, openStatus, slotConflict } from './hours.js';
import { toJpegDataUrl } from './images.js';
import { configureMaps, destroyMaps, mapProvider, renderMap } from './map.js';
import { clearOfflineData, disablePush, enablePush, pushState, registerServiceWorker } from './pwa.js';

// ---------- Constants & helpers ----------

const CATS = {
  food: 'Restaurant', cafe: 'Café', dessert: 'Sweets', drinks: 'Bar', nightlife: 'Nightlife', attraction: 'Sight',
  activity: 'Things to do', event: 'Event', nature: 'Outdoors', shopping: 'Shopping', stay: 'Stay', other: 'Other',
};
const CAT_ORDER = Object.keys(CATS);
const TODS = ['morning', 'lunch', 'afternoon', 'dinner', 'evening'];
const ACTIVE = new Set(['queued', 'downloading', 'transcribing', 'analyzing']);
const MENU_CATS = new Set(['food', 'cafe', 'dessert', 'drinks', 'nightlife']); // places that get a Menu tab

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
  me: undefined,        // your account (null before accounts exist)
  folders: null,        // your folders, from /v1/folders
  libf: {},             // filters per saved-places list ('saved' or a folder id)
  cal: null,            // everything dated, from /v1/calendar
  calv: { month: null, day: null, filter: 'all', scrollTo: null },
  bookingsAll: null,    // every booking across trips
  bk: { kind: 'all', trip: 'all', past: false },
  lastTab: 'trips',     // the tab profile and calendar pages go back to
  lastRoot: '#/',
  disc: { kind: 'restaurants', area: 'home', tripId: null, data: {} },
  homeCity: undefined,  // home city setting (null when unset)
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
  menu: {},             // placeId -> saved menu
  menuBusy: {},         // placeId -> true while a menu is being looked up
  menuDiet: {},         // placeId -> dietary filter on the menu
  bkflow: null,         // confirmations read by Claude, being checked one by one
  packing: {},          // tripId -> packing list (null when none yet)
  events: {},           // tripId -> events during the trip (null while loading)
  needsTried: {},       // tripId -> already asked which places need booking this visit
  eventFilter: {},      // tripId -> chosen filter on the events page
  packBusy: {},         // tripId -> true while a list is being made
  reserveTried: {},     // placeId -> already looked for a booking link this visit
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
  if (!parts.length || parts[0] === 'home') return { name: 'home', params };
  if (parts[0] === 'library') return { name: 'trips', params };
  if (parts[0] === 'city' && parts[1]) return { name: 'city', id: decodeURIComponent(parts[1]), params };
  if (parts[0] === 'trip' && parts[1] && parts[2] === 'bookings') return { name: 'bookings', params: new URLSearchParams(`trip=${parts[1]}`) };
  if (parts[0] === 'settings') return { name: 'profile', params };
  if (parts[0] === 'setup') return { name: 'signin', params };
  if (parts[0] === 'saved') return { name: 'trips', params, tab: 'saved' };
  if (parts[0] === 'folder' && parts[1]) return { name: 'folder', id: parts[1], params };
  if (parts[0] === 'trip' && parts[1]) return { name: 'trip', id: parts[1], mode: parts[2] || 'places', params };
  if (parts[0] === 'place' && parts[1]) return { name: 'place', id: parts[1], mode: parts[2] === 'menu' ? 'menu' : 'overview', params };
  if (parts[0] === 'today' && parts[1]) return { name: 'today', id: parts[1], params };
  if (parts[0] === 'packing' && parts[1]) return { name: 'packing', id: parts[1], params };
  if (parts[0] === 'events' && parts[1]) return { name: 'events', id: parts[1], params };
  if (parts[0] === 'edit' && parts[1] && parts[2]) return { name: 'edit', id: parts[1], editId: parts[2], params };
  if (parts[0] === 'editplace' && parts[3]) return { name: 'editplace', id: parts[1], editId: parts[2], entryId: parts[3], params };
  if (['map', 'imports', 'profile', 'signin', 'add', 'concierge', 'taste', 'discover', 'bookings', 'calendar', 'usage'].includes(parts[0])) return { name: parts[0], params };
  return { name: 'trips', params };
}

const TAB_FOR = {
  home: 'home', trips: 'trips', folder: 'trips', city: 'trips', trip: 'trips', place: 'trips', today: 'trips', edit: 'trips', editplace: 'trips', packing: 'trips', events: 'trips', map: 'trips', concierge: 'concierge',
  discover: 'discover', bookings: 'bookings', add: 'trips',
};
// Profile, calendar and their pages open over whichever tab you were on.
const tabOf = (name) => TAB_FOR[name] || S.lastTab || 'trips';
const TAB_INDEX = { home: 0, trips: 1, discover: 2, bookings: 3, concierge: 4 };
const TAB_LABEL = { home: 'Home', trips: 'Library', discover: 'Discover', bookings: 'Bookings', concierge: 'Concierge' };
const DEPTH = { profile: 1, calendar: 1, imports: 2, usage: 2, city: 1, map: 1, taste: 2, folder: 1, trip: 1, today: 1, taste: 1, packing: 1, events: 1, edit: 2, editplace: 3, place: 2 };
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let renderToken = 0;
let lastKey = '';
let lastRoute = null;
let lastHtml = '';

/** How to animate from one screen to the next: iOS-style push/pop within a tab, a crossfade between tabs. */
function transitionKind(from, to) {
  if (!from || to.name === 'add' || from.name === 'signin' || to.name === 'signin') return 'none';
  if (tabOf(from.name) !== tabOf(to.name)) return 'fade';
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

/** Screens the iOS app shows natively: opening one from an embedded web screen hands it to the app. */
const nativeRoute = (r) => ['home', 'trips', 'folder', 'city', 'trip', 'map', 'profile', 'signin', 'imports', 'add', 'editplace', 'place'].includes(r.name);

/** Leaves a screen: inside the iOS app the first web screen hands back to the app's own navigation. */
function leave(fallback) {
  if (EMBED) {
    if (embedDepth > 0) history.back(); else toNative({ back: true });
  } else if (S.navigations > 0) history.back();
  else go(fallback);
}
let embedDepth = -1; // how many screens deep this embedded web view is, so Back at the first one returns to the app

async function render({ quiet = false } = {}) {
  // Background refreshes never cancel a navigation that's still loading, or a field someone is typing in.
  if (quiet && navigating) { quietPending = true; return; }
  if (quiet && editing()) return;
  const r = route();
  if (EMBED && !quiet && (r.name === 'signin' || (lastRoute && nativeRoute(r)))) {
    toNative({ open: location.hash || '#/' });
    if (lastRoute) history.back();
    return;
  }
  if (EMBED && !quiet) {
    const st = history.state;
    if (st && st.d != null) embedDepth = st.d;
    else { embedDepth += 1; history.replaceState({ d: embedDepth }, ''); }
  }
  if (TAB_FOR[r.name]) S.lastTab = TAB_FOR[r.name];
  if (r.name in TAB_INDEX) S.lastRoot = location.hash || '#/';
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
    if (e instanceof ApiError && e.status === 401) { location.hash = '#/signin'; return; }
    reportError(e, `Screen ${r.name}`);
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
    const tab = tabOf(r.name);
    const tabbar = $('#tabbar');
    document.querySelectorAll('.tab').forEach((t) => {
      const on = t.dataset.tab === tab;
      t.classList.toggle('on', on);
      if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
    });
    if (tab in TAB_INDEX) tabbar.style.setProperty('--i', TAB_INDEX[tab]);
    tabbar.hidden = r.name === 'signin' || r.name === 'taste';
    const app = $('.app');
    app.classList.toggle('fullbleed', r.name === 'map' || (r.name === 'trip' && r.mode === 'map'));
    app.classList.toggle('notabs', r.name === 'signin' || r.name === 'taste');
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

function navbar(title, { back, backLabel, right = '', left = '' } = {}) {
  const backHtml = back
    ? `<a class="gbtn" href="${back}" data-act="back" data-fallback="${back}" aria-label="Back to ${esc(backLabel || 'previous screen')}">${ICON.back}</a>`
    : left;
  return `<header class="navbar"><div class="left">${backHtml}</div>
    <div class="title" aria-hidden="true">${esc(title)}</div><div class="right">${right}</div></header>`;
}

/** The bar on each tab's main screen: the calendar on the left, your profile on the right. */
function rootNav(title, { right = '' } = {}) {
  background(S.cal, 'cal', loadCal);
  const today = isoDate(new Date());
  const n = S.cal ? S.cal.items.filter((i) => i.kind !== 'trip' && i.date <= today && (i.end_date || i.date) >= today).length : 0;
  const cal = `<a class="gbtn calbtn" href="#/calendar" aria-label="Calendar${n ? `, ${plural(n, 'thing')} today` : ''}">
    <span class="calglyph" aria-hidden="true"><b>${new Date().getDate()}</b></span>${n ? '<i class="caldot"></i>' : ''}</a>`;
  const me = '<a class="gbtn me" href="#/profile" aria-label="Profile and settings"><span data-icon="person"></span></a>';
  return navbar(title, { left: cal, right: `${right}${me}` });
}
/** Where a page opened from the profile or calendar goes back to. */
const backToTab = () => ({ back: S.lastRoot || '#/', backLabel: TAB_LABEL[S.lastTab] || 'Trips' });

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

/** Running inside the TripIt iOS app (it adds this to the user agent): it has its own share button. */
const NATIVE = /TripItiOS\//.test(navigator.userAgent);
/** One screen of the web app shown inside the native iOS app, which has its own tab bar and screens. */
const EMBED = NATIVE && new URLSearchParams(location.search).has('embed');
// Light, Dark or the device's setting (Profile → Appearance). Inside the iOS app, the app's own setting applies.
const THEME_KEY = 'tripit.theme';
function themeOf() { try { return localStorage.getItem(THEME_KEY) || 'system'; } catch { return 'system'; } }
function applyTheme() {
  const t = themeOf();
  if (EMBED || t === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}
applyTheme();
if (EMBED) document.documentElement.classList.add('embed');

// ---------- Error reporting ----------

/** Sends an unexpected error (a bug, not "you're offline") to the server, which passes it on to error reporting. */
const reportedErrors = new Set();
function reportError(error, where = '') {
  if (error instanceof ApiError) return; // the server already knows, or it's the network
  const message = `${where ? `${where}: ` : ''}${(error && error.message) || String(error)}`.slice(0, 2000);
  if (reportedErrors.size >= 10 || reportedErrors.has(message)) return;
  reportedErrors.add(message);
  fetch('/v1/client-errors', {
    method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ source: EMBED ? 'ios-web' : 'web', message, stack: String((error && error.stack) || '').slice(0, 10000),
      url: (location.hash || '#/').slice(0, 500) }),
  }).catch(() => {});
}
window.addEventListener('error', (ev) => reportError(ev.error || ev.message, 'Uncaught'));
window.addEventListener('unhandledrejection', (ev) => reportError(ev.reason, 'Unhandled'));

/** The chips on the home screen: friendlier groups of the app's categories. */
const GROUPS = [
  { id: 'food', label: 'Food', cats: ['food', 'dessert'] },
  { id: 'coffee', label: 'Coffee', cats: ['cafe'] },
  { id: 'drinks', label: 'Drinks', cats: ['drinks', 'nightlife'] },
  { id: 'stay', label: 'Hotels', cats: ['stay'] },
  { id: 'shopping', label: 'Shopping', cats: ['shopping'] },
  { id: 'sights', label: 'Sights', cats: ['attraction', 'nature'] },
  { id: 'activities', label: 'Activities', cats: ['activity'] },
  { id: 'events', label: 'Events', cats: ['event'] },
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
  const home = { tab: 'saved', cat: 'all', sort: 'popular', trip: 'all', starred: false };
  try {
    const saved = JSON.parse(localStorage.getItem(HOME_KEY) || '{}');
    if (saved.tab === 'trips') home.tab = 'trips';
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
      ? 'Location access is off. Allow it for Travel Edit in Settings → Privacy & Security → Location Services → Safari Websites.'
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
const findAnyPlace = (id) => allPlaces().find((x) => x.id === id && x.trip_id === contextTrip()) || allPlaces().find((x) => x.id === id)
  || (S.places || []).find((x) => x.id === id) || (placeDetail[id] || {}).place;
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
    <span class="s">${esc(sub.join(' · '))}${p.category === 'event' ? `<span class="datechip">${p.event_date ? esc(shortDay(p.event_date)) : 'Date TBC'}</span>` : ''}${p.suggested ? '<span class="suggchip">Suggested</span>' : ''}${needChip(p)}${ratingChip(p)}${hotChip(p)}${dayChip(p)}${dist}</span>
    ${p.recommended_items.length ? `<span class="s clip">Try: ${esc(p.recommended_items.join(', '))}</span>` : ''}
    ${hoursLine(p)}${hereChip(p)}</span>`;
  if (S.sel.on) {
    const picked = S.sel.picked.has(p.id);
    return `<button class="row prow sel${picked ? ' picked' : ''}" data-act="pick" data-id="${p.id}" aria-pressed="${picked}">
      <span class="check" aria-hidden="true">${picked ? ICON.done : ''}</span>${body}</button>`;
  }
  return `<div class="row prow"><a class="rowlink" href="${placeHref(p)}">${body}</a>${starButton(p)}</div>`;
}

function jobRow(job) {
  const active = ACTIVE.has(job.status);
  const title = active ? (job.message || 'Waiting to process…') : job.status === 'failed' ? (job.message || 'Import failed') : (job.message || 'Done');
  const inner = `${platformTile(platformOf(job.url))}<span class="main"><span class="t" style="font-size:16px${job.status === 'failed' ? ';color:var(--warn)' : ''}">${esc(title)}</span>
    <span class="s clip">${esc(job.url.startsWith('upload:') ? 'Screenshots' : job.url.replace(/^https?:\/\/(www\.)?/, ''))} · ${timeAgo(job.created_at)}</span>
    ${(job.warnings || []).map((w) => `<span class="s" style="color:var(--warn)">${esc(w)}</span>`).join('')}</span>`;
  if (active) return `<div class="row">${inner}<span class="spinner"></span></div>`;
  if (job.status === 'done' && job.trip_id) return `<a class="row" href="#/trip/${job.trip_id}">${inner}${ICON.chev}</a>`;
  if (job.status === 'done' && job.reel_id) return `<a class="row" href="#/saved?reel=${job.reel_id}">${inner}${ICON.chev}</a>`;
  if (job.status === 'failed') return `<div class="row">${inner}<button class="btn tint small" data-act="retry" data-id="${job.id}">Retry</button></div>`;
  return `<div class="row">${inner}</div>`;
}

function emptyState(color, icon, title, text, extra = '') {
  return `<div class="empty">${tile(color, icon, 'xl')}<h3>${title}</h3><p>${text}</p>${extra}</div>`;
}

function tripCard(t, i) {
  const cats = t.categories.length ? t.categories : ['other'];
  const g2 = cats[1] ? `var(--c-${cats[1]})` : 'var(--c-indigo)';
  const meta = [t.kind === 'local' ? 'Near home' : t.country, plural(t.place_count, 'place')].filter(Boolean).join(' · ');
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
// Miles where people use them (US, UK), kilometres elsewhere.
const USE_MILES = /^en-(US|GB|LR|MM)\b/i.test(navigator.language || '');
function fmtDistance(m) {
  if (USE_MILES) {
    const mi = m / 1609.34;
    return mi < 0.1 ? `${Math.max(50, Math.round(m * 3.28084 / 50) * 50)} ft` : `${mi < 10 ? mi.toFixed(1) : Math.round(mi)} mi`;
  }
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
    ${photo ? `<a class="next-photo" href="${placeHref(p)}"><img src="${esc(photoUrl(photo, 1000))}" alt="" decoding="async" onerror="this.parentElement.remove()"></a>` : ''}
    <div class="next-body">
      <div class="next-label">${isToday ? 'Up next' : 'First up'} · stop ${n} of ${total}</div>
      <h2><a href="${placeHref(p)}">${esc(p.name)}</a>${starMark(p)}</h2>
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
    'Views & nature', 'Wellness & spas', 'Nightlife', 'History', 'Markets', 'Live music', 'Theatre & comedy', 'Sports'] },
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
    <span class="editcard-meta">${plural(e.entries.length, 'place')}${e.new_count ? ` · ${e.new_count} new` : ''}${e.folder_id ? ' · Saved' : ''}</span></span></a>`;
}

function homeEdits(tripCount) {
  if (!tripCount) return '';
  const all = background(S.allEdits, 'alledits', loadAllEdits);
  if (!all || !all.length) return '';
  const cards = all.flatMap((te) => te.edits.slice(0, 3).map((e) => editCard(te, e))).slice(0, 9);
  const ids = all.map((te) => te.trip_id);
  const busy = ids.some((id) => S.curating[id] || (S.edits[id] && S.edits[id].refreshing) || all.find((te) => te.trip_id === id).refreshing);
  ids.forEach((id) => { if ((S.edits[id] && S.edits[id].refreshing) || all.find((te) => te.trip_id === id).refreshing) pollEdits(id); });
  const aside = busy ? '<span class="eyebrow">Finding new picks…</span>'
    : `<button class="linkbtn" data-act="curateall" data-ids="${ids.join(',')}" aria-label="Get new edits">${ICON.sparkle}New edits</button>`;
  return `<div class="railhead"><h2 class="section-title">The Edits</h2>${aside}</div>
    <div class="rail">${cards.join('')}</div><div class="railhead"><h2 class="section-title">Your trips</h2></div>`;
}

function editsSection(trip) {
  if (S.curating[trip.id] && !(S.edits[trip.id] && S.edits[trip.id].edits.length)) {
    return `<div class="railhead"><h2 class="section-title">The Edits</h2><span class="eyebrow">Curating…</span></div>
      <div class="rail">${'<div class="editcard skeleton"></div>'.repeat(3)}</div>`;
  }
  const te = background(S.edits[trip.id], `edits:${trip.id}`, () => loadEdits(trip.id));
  if (!te) return '';
  // Edits refresh about once a day (and when your places change), quietly in the background.
  if (te.edits.length && te.stale && !te.refreshing && !S.curateTried[trip.id] && !isOffline()) setTimeout(() => curate(trip.id, true), 0);
  if (te.refreshing) pollEdits(trip.id);
  if (!te.edits.length && te.refreshing) {
    return `<div class="railhead"><h2 class="section-title">The Edits</h2><span class="eyebrow">Curating…</span></div>
      <div class="rail">${'<div class="editcard skeleton"></div>'.repeat(3)}</div>`;
  }
  if (!te.edits.length) {
    if (trip.places.length < 3) return '';
    if (trip.places.length >= 4 && !S.curateTried[trip.id] && !isOffline()) setTimeout(() => curate(trip.id, true), 0);
    return `<div class="section"><div class="invite"><div class="eyebrow">The Edits</div><h2>Curate this trip</h2>
      <p>Editorial lists tailored to your taste, mixing your saved places with picks from travel and food publications. They refresh daily.</p>
      <div class="invite-actions"><button class="btn" data-act="curate" data-id="${trip.id}">Curate</button></div></div></div>`;
  }
  const profileNewer = S.profile && S.profile.updated_at && te.created_at && new Date(S.profile.updated_at) > new Date(te.created_at);
  const aside = te.refreshing ? '<span class="eyebrow">Finding new picks…</span>'
    : `<button class="linkbtn" data-act="curate" data-id="${trip.id}" aria-label="Get new edits">${ICON.sparkle}${profileNewer ? 'Refresh for your taste' : 'New edits'}</button>`;
  return `<div class="railhead"><h2 class="section-title">The Edits</h2>${aside}</div>
    <div class="rail">${te.edits.map((e) => editCard(te, e)).join('')}</div>`;
}

async function curate(tripId, auto = false) {
  if (S.curating[tripId] || (S.edits[tripId] && S.edits[tripId].refreshing)) return;
  if (!auto) toast('Finding new picks. This takes about a minute.');
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

/** While new edits are being researched (a minute or so), check back every few seconds. */
const editPolls = {};
function pollEdits(tripId) {
  if (editPolls[tripId]) return;
  editPolls[tripId] = setTimeout(async () => {
    try {
      const te = await api(`/v1/trips/${tripId}/edits`);
      S.edits[tripId] = te; fetchedAt[`edits:${tripId}`] = Date.now();
      if (!te.refreshing) S.allEdits = null;
    } catch { /* try again on the next render */ }
    delete editPolls[tripId];
    render({ quiet: true });
  }, 4000);
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

/** Saved | Trips switch under the Library title. */
const homeSwitch = () => segControl('home', [['saved', 'Saved'], ['trips', 'Trips']].map(([k, label]) => ({
  on: S.home.tab === k,
  html: `<button class="${S.home.tab === k ? 'on' : ''}" data-act="hometab" data-tab="${k}" aria-pressed="${S.home.tab === k}">${label}</button>`,
})));

/** Floating bar while selecting places. */
function selBar() {
  if (!S.sel.on) return '';
  const n = S.sel.picked.size;
  const r = route();
  const dis = n ? '' : 'disabled';
  const actions = r.name === 'trip'
    ? `<button class="btn small" data-act="selectadd" ${dis}>${ICON.calendarPlus}Add to a day</button>
       <button class="btn tint small" data-act="selremovetrip" ${dis}>Remove</button>`
    : `<button class="btn small" data-act="seladdtrip" ${dis}>${ICON.plane}Trip</button>
       <button class="btn tint small" data-act="seladdfolder" ${dis}>${ICON.folder}Folder</button>
       ${r.name === 'folder' ? `<button class="btn tint small" data-act="selremovefolder" data-id="${r.id}" ${dis}>Remove</button>` : ''}`;
  return `<div class="selbar" role="region" aria-label="Selected places"><span class="selcount">${n ? `${n} selected` : 'Tap places to select'}</span>
    <span class="selacts">${actions}</span></div>`;
}

// ---------- Discover ----------

const DISC_KINDS = [['restaurants', 'Restaurants'], ['coffee', 'Coffee'], ['bars', 'Bars'], ['dessert', 'Dessert'], ['things', 'Things to do']];
const PRICE_SIGNS = ['', '$', '$$', '$$$', '$$$$'];
const DISC_CAT = { restaurants: 'food', coffee: 'cafe', bars: 'drinks', dessert: 'dessert', things: 'activity' };

function discKey() {
  const d = S.disc;
  return `${d.area}|${d.area === 'trip' ? d.tripId : ''}|${d.kind}`;
}

async function loadDiscover(force = false) {
  const d = S.disc;
  const key = discKey();
  if (!force && d.data[key] !== undefined) return;
  d.data[key] = null; // asked; renders quietly when the answer arrives
  const q = new URLSearchParams({ kind: d.kind, area: d.area });
  try {
    if (d.area === 'trip') q.set('trip_id', d.tripId);
    if (d.area === 'here') { const pos = await getPosition(); q.set('lat', pos.latitude); q.set('lon', pos.longitude); }
    if (force) q.set('refresh', 'true');
    d.data[key] = await api(`/v1/discover?${q}`);
  } catch (e) {
    d.data[key] = { status: 'error', items: [], message: e.message };
  }
  render({ quiet: true });
}

function discoverCard(it) {
  const hood = it.address ? it.address.split(',').slice(-3, -2)[0] : '';
  const meta = [it.kind_label, it.price_level ? PRICE_SIGNS[it.price_level] : null, it.distance_m != null ? fmtDistance(it.distance_m) : null].filter(Boolean);
  const ph = `<span class="sthumb ph" style="--sz:56px; --pc: var(--c-${DISC_CAT[S.disc.kind] || 'food'})">${ICON[DISC_CAT[S.disc.kind]] || ICON.pin}</span>`;
  const img = it.photo ? `<img class="sthumb" style="--sz:56px" src="${esc(it.photo)}" alt="" loading="lazy" decoding="async" onerror="this.outerHTML=this.nextElementSibling.innerHTML"><template>${ph}</template>` : ph;
  return `<li class="drow">${img}<span class="m"><span class="t">${esc(it.name)}</span>
      <span class="s">${esc([hood && hood.trim(), ...meta].filter(Boolean).join(' · '))}</span>
      ${it.award ? `<span class="award">${ICON.sparkle}${esc(it.award)}</span>` : ''}
      ${it.why ? `<span class="why">${esc(it.why)}</span>` : ''}</span>
    <button class="bmk${it.saved ? ' on' : ''}" data-act="discsave" data-id="${esc(it.id)}" aria-pressed="${!!it.saved}" aria-label="${it.saved ? `Saved: ${esc(it.name)}` : `Save ${esc(it.name)}`}">${ICON.bookmark}</button></li>`;
}

/** The edits for where you're looking: your city's, or the trip's. */
function discoverEdits(cityName, tripId) {
  const all = background(S.allEdits, 'alledits', loadAllEdits) || [];
  const trips = S.trips || [];
  const matches = all.filter((te) => {
    if (tripId) return te.trip_id === tripId;
    const t = trips.find((x) => x.id === te.trip_id);
    return cityName && t && tripStops(t).some((c) => cityKey(c) === cityKey(cityName));
  });
  const cards = matches.flatMap((te) => te.edits.map((e) => ({ te, e }))).slice(0, 4);
  if (!cards.length) return '';
  const [first, ...rest] = cards;
  const photos = first.e.entries.map((x) => x.photo).filter(Boolean).slice(0, 3);
  return `<div class="h2row"><h2 class="h2">The edits${cityName ? ` · ${esc(cityName)}` : ''}</h2></div>
    <a class="ecard" href="#/edit/${first.te.trip_id}/${first.e.id}">${photos.length ? `<span class="eimgs">${photos.map((ph) => `<img src="${esc(photoUrl(ph, 400))}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`).join('')}</span>` : ''}
      <span class="b"><span class="eyebrow">The edit · ${plural(first.e.entries.length, 'place')}</span><span class="t serif">${esc(first.e.title)}</span>
      ${first.e.dek ? `<span class="s">${esc(first.e.dek)}</span>` : ''}</span></a>
    ${rest.length ? `<ul class="rows">${rest.map(({ te, e }) => `<li><a href="#/edit/${te.trip_id}/${e.id}"><span class="m"><span class="eyebrow">The edit · ${plural(e.entries.length, 'place')}</span><span class="t serif">${esc(e.title)}</span></span>${ICON.chev}</a></li>`).join('')}</ul>` : ''}`;
}

async function discoverView() {
  const d = S.disc;
  if (S.homeCity === undefined) S.homeCity = await api('/v1/home').catch(() => null);
  if (S.me === undefined) S.me = await api('/v1/me').catch(() => null);
  const allTrips = await cachedTrips();
  const trips = allTrips.filter((t) => t.kind !== 'local' && t.place_count);
  // While you're travelling, Discover looks around your trip unless you picked somewhere.
  const onTrip = activeTrip(realTrips(allTrips));
  if (!d.picked && onTrip && onTrip.trip.place_count) { d.area = 'trip'; d.tripId = onTrip.trip.id; }
  if (d.area === 'home' && !S.homeCity) d.area = 'here';
  if (d.area === 'trip' && !trips.some((t) => t.id === d.tripId)) d.area = S.homeCity ? 'home' : 'here';
  loadDiscover();
  const res = d.data[discKey()];
  const trip = d.area === 'trip' ? trips.find((t) => t.id === d.tripId) : null;
  const cityName = d.area === 'home' ? S.homeCity.city : trip ? (onTrip && onTrip.trip.id === trip.id
    ? (((trip.stops || []).find((x) => onTrip.day >= x.start_day && onTrip.day <= x.end_day) || {}).city || trip.city) : trip.city) : '';
  const areaLabel = d.area === 'home' ? `Near you · ${S.homeCity.city}` : d.area === 'here' ? 'Near you' : `${trip ? trip.name : 'Trip'}${cityName ? ` · ${cityName}` : ''}`;
  const head = `<div class="tophead end"><span class="tbtns">${roundBtn('add', 'plus', 'Save a place')}${profileBtn()}</span></div>
    <div class="libtitle"><h1 data-anchor>Discover</h1></div>
    <button class="areabtn" data-act="discarea">${ICON.locate}<span>${esc(areaLabel)}</span>${ICON.down}</button>
    <p class="sub tight">Switches to your trip city when you travel</p>
    <div class="fchips" role="group" aria-label="Kind of place">${DISC_KINDS.map(([k, label]) =>
      `<button class="fchip${d.kind === k ? ' on' : ''}" data-act="disckind" data-kind="${k}" aria-pressed="${d.kind === k}">${label}</button>`).join('')}</div>`;
  let body;
  if (res === undefined || res === null) body = '<div class="empty"><span class="spinner"></span><p>Finding the best nearby…</p></div>';
  else if (res.status === 'disabled') body = emptyState('gray', 'compass', 'Discover isn’t switched on', 'It needs a Google Maps key on the server (GOOGLE_MAPS_API_KEY).');
  else if (res.status === 'no_area') body = emptyState('gray', 'pin', 'Where should we look?', 'Set your home city in your profile, or choose Near you.',
    '<a class="btn" href="#/profile">Open your profile</a>');
  else if (res.status === 'error') body = emptyState('gray', 'warn', 'Couldn’t load recommendations', esc(res.message || 'Try again in a moment.'),
    '<button class="btn tint" data-act="discrefresh">Try again</button>');
  else if (!res.items.length) body = emptyState('gray', 'pinslash', 'Nothing well-rated found here', 'Try another kind of place or a wider area.');
  else {
    body = `<div class="h2row"><h2 class="h2">Popular near ${d.area === 'trip' ? esc(cityName || 'your trip') : 'you'}</h2><button class="tbtn" data-act="discrefresh">Refresh</button></div>
      <ul class="drows">${res.items.map(discoverCard).join('')}</ul>
      <p class="sub small">Well rated on Google and picked for your taste. Awards such as Michelin stars come from Claude’s knowledge, not a live feed, so check before you go.</p>`;
  }
  return `<div class="page">${head}${discoverEdits(cityName, trip ? trip.id : null)}${body}</div>`;
}

// ---------- Calendar ----------

const loadCal = () => once('cal', async () => { S.cal = await api('/v1/calendar'); fetchedAt.cal = Date.now(); return S.cal; });
const cachedCal = () => { if (!S.cal) return loadCal(); revalidate('cal', loadCal); return S.cal; };
const CAL_FILTERS = [['all', 'All'], ['event', 'Events'], ['booking', 'Bookings'], ['stop', 'Plans']];
const CAL_KIND = { event: 'Event', booking: 'Booking', stop: 'Plan', trip: 'Trip' };
const isoOf = (d) => isoDate(d);
const dayOf = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
const shortDay = (iso) => dayOf(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

function weekStartsSunday() {
  try {
    const info = new Intl.Locale(navigator.language).weekInfo || new Intl.Locale(navigator.language).getWeekInfo?.();
    if (info && info.firstDay) return info.firstDay === 7;
  } catch { /* older browsers */ }
  return /^en-(US|CA)|^ja|^ko|^zh-TW|^he|^pt-BR/i.test(navigator.language || 'en-US');
}

/** Each item on every day it covers (a hotel stay or a week-long pop-up shows on all its days). */
function calByDay(items) {
  const map = {};
  for (const it of items) {
    if (!it.date) continue;
    const end = it.end_date || it.date;
    for (let d = dayOf(it.date); isoOf(d) <= end; d.setDate(d.getDate() + 1)) (map[isoOf(d)] ||= []).push(it);
  }
  return map;
}

function calWhen(it, iso) {
  if (it.kind === 'trip') return 'Trip';
  if (it.end_date && iso !== it.date) return iso === it.end_date ? 'Last day' : 'Ongoing';
  if (it.time) return fmtClock(it.time);
  return it.part_of_day ? cap(it.part_of_day) : 'All day';
}

function calRow(it, iso) {
  const dest = it.kind === 'booking' ? `data-act="calbooking" data-id="${it.booking_id}"`
    : it.kind === 'trip' ? `data-href="#/trip/${it.trip_id}"` : `data-href="#/place/${it.place_id}"`;
  const add = it.kind === 'event' || it.kind === 'booking'
    ? `<button class="gbtn small caladd" data-act="caladd" data-id="${esc(it.id)}" aria-label="Add ${esc(it.title)} to your calendar app">${ICON.calendarPlus}</button>` : '';
  return `<div class="calrow k-${it.kind}">
    <button class="calrow-main" ${dest} ${dest.startsWith('data-href') ? 'data-act="calopen"' : ''}>
      <span class="when">${esc(calWhen(it, iso))}</span><span class="bar" aria-hidden="true"></span>
      <span class="main"><span class="t">${esc(it.title)}</span>${it.subtitle ? `<span class="s">${esc(it.subtitle)}</span>` : ''}</span>
    </button>${add}</div>`;
}

async function calendarView() {
  const cal = await cachedCal();
  const c = S.calv;
  const today = isoOf(new Date());
  if (!c.month) c.month = today.slice(0, 7);
  const items = c.filter === 'all' ? cal.items : cal.items.filter((i) => i.kind === c.filter || (c.filter !== 'trip' && i.kind === 'trip' && c.filter === 'stop'));
  const byDay = calByDay(items);
  const trips = calByDay(cal.items.filter((i) => i.kind === 'trip'));
  const [y, m] = c.month.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  const days = new Date(y, m, 0).getDate();
  const sunday = weekStartsSunday();
  const lead = (first.getDay() + (sunday ? 0 : 6)) % 7;
  const names = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, (sunday ? 7 : 1) + i).toLocaleDateString(undefined, { weekday: 'narrow' }));
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push('<span class="cday out"></span>');
  for (let d = 1; d <= days; d++) {
    const iso = `${c.month}-${String(d).padStart(2, '0')}`;
    const kinds = [...new Set((byDay[iso] || []).filter((x) => x.kind !== 'trip').map((x) => x.kind))].slice(0, 3);
    const trip = trips[iso] ? trips[iso][0] : null;
    const cls = ['cday', iso === today ? 'today' : '', iso === c.day ? 'sel' : '', iso < today ? 'past' : '',
      trip ? 'intrip' : '', trip && trip.date === iso ? 'tstart' : '', trip && (trip.end_date || trip.date) === iso ? 'tend' : ''].filter(Boolean).join(' ');
    const n = (byDay[iso] || []).filter((x) => x.kind !== 'trip').length;
    cells.push(`<button class="${cls}" data-act="calday" data-date="${iso}" aria-pressed="${iso === c.day}"
      aria-label="${esc(shortDay(iso))}${n ? `, ${plural(n, 'item')}` : ''}${trip ? `, ${esc(trip.title)} trip` : ''}"><span class="num">${d}</span>
      <span class="cdots" aria-hidden="true">${kinds.map((k) => `<i class="k-${k}"></i>`).join('')}</span></button>`);
  }
  const monthName = first.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const isThisMonth = c.month === today.slice(0, 7);
  const grid = `<div class="calcard">
    <div class="calhead"><button class="gbtn small" data-act="calmonth" data-step="-1" aria-label="Previous month">${ICON.back}</button>
      <h2>${esc(monthName)}</h2>
      ${isThisMonth ? '<span class="calhead-gap"></span>' : '<button class="linkbtn" data-act="caltoday">Today</button>'}
      <button class="gbtn small flip" data-act="calmonth" data-step="1" aria-label="Next month">${ICON.back}</button></div>
    <div class="cgrid wk" aria-hidden="true">${names.map((n) => `<span>${esc(n)}</span>`).join('')}</div>
    <div class="cgrid">${cells.join('')}</div>
    <div class="legend" aria-hidden="true"><span><i class="k-event"></i>Events</span><span><i class="k-booking"></i>Bookings</span><span><i class="k-stop"></i>Plans</span><span><i class="k-trip"></i>Trips</span></div></div>`;

  // The agenda: from the chosen day (or today) to the end of the month.
  const start = c.day && c.day.startsWith(c.month) ? c.day : (isThisMonth ? today : `${c.month}-01`);
  const end = `${c.month}-${String(days).padStart(2, '0')}`;
  const agendaDays = Object.keys(byDay).filter((d) => d >= start && d <= end).sort();
  let agenda = agendaDays.map((iso) => {
    // Something lasting several days (a pop-up, a hotel stay) is listed once: on its first day, or as
    // "Ongoing" at the top when it began earlier, and again on any day you tap.
    const list = byDay[iso].filter((it) => (it.kind === 'trip' ? it.date === iso
      : !it.end_date || it.date === iso || iso === c.day || (iso === agendaDays[0] && it.date < iso)));
    if (!list.length) return '';
    let rows = list.map((it) => calRow(it, iso));
    if (c.filter === 'all') { // a day of a planned trip shows as one row; Plans shows every stop
      rows = [];
      const done = new Set();
      for (const it of list) {
        if (it.kind !== 'stop') { rows.push(calRow(it, iso)); continue; }
        if (done.has(it.trip_id)) continue;
        done.add(it.trip_id);
        const same = list.filter((x) => x.kind === 'stop' && x.trip_id === it.trip_id);
        const trip = cal.items.find((x) => x.kind === 'trip' && x.trip_id === it.trip_id);
        const n = trip ? Math.round((dayOf(iso) - dayOf(trip.date)) / 86400000) + 1 : null;
        const names = same.slice(0, 3).map((x) => x.title).join(', ') + (same.length > 3 ? ` + ${same.length - 3} more` : '');
        rows.push(`<div class="calrow k-stop"><button class="calrow-main" data-act="calopen" data-href="#/today/${it.trip_id}${n ? `?day=${n}` : ''}">
          <span class="when">${n ? `Day ${n}` : 'Plan'}</span><span class="bar" aria-hidden="true"></span>
          <span class="main"><span class="t">${esc(trip ? `${trip.title} plan` : 'Your plan')} · ${plural(same.length, 'stop')}</span><span class="s">${esc(names)}</span></span>
          </button></div>`);
      }
    }
    return `<div class="agday${iso === c.day ? ' sel' : ''}" id="ag-${iso}"><div class="datehead">${iso === today ? 'Today · ' : ''}${esc(shortDay(iso))}</div>
      <div class="group">${rows.join('')}</div></div>`;
  }).join('');
  if (!agenda) {
    agenda = `<div class="calempty">${c.day && byDay[c.day] === undefined ? `Nothing on ${esc(shortDay(c.day))}.` : `Nothing else in ${esc(first.toLocaleDateString(undefined, { month: 'long' }))}.`}
      ${cal.items.some((i) => i.date > end) ? '<button class="linkbtn" data-act="calnext">Show what’s next</button>' : ''}</div>`;
  }
  const undated = c.filter === 'all' || c.filter === 'event' ? cal.undated : [];
  const undatedHtml = undated.length ? `<div class="section"><div class="section-h">Saved events without a date</div><div class="group tiles">
    ${undated.map((it) => `<div class="row"><a class="rowlink" href="#/place/${it.place_id}">${tile('event', 'event')}<span class="main"><span class="t">${esc(it.title)}</span>
      ${it.subtitle ? `<span class="s">${esc(it.subtitle)}</span>` : ''}</span></a>
      <button class="btn tint small" data-act="eventdate" data-id="${it.place_id}">Set date</button></div>`).join('')}</div>
    <div class="section-f">Add a date and they appear on the calendar.</div></div>` : '';

  const counts = { all: cal.items.filter((i) => i.kind !== 'trip').length };
  ['event', 'booking', 'stop'].forEach((k) => { counts[k] = cal.items.filter((i) => i.kind === k).length; });
  const chips = `<div class="fchips" role="group" aria-label="Show">${CAL_FILTERS.map(([k, label]) =>
    `<button class="fchip${c.filter === k ? ' on' : ''}" data-act="calfilter" data-f="${k}" aria-pressed="${c.filter === k}">${label}<span class="n">${counts[k] + (k === 'event' ? cal.undated.length : 0)}</span></button>`).join('')}</div>`;
  const weekEnd = isoOf(new Date(Date.now() + 6 * 86400000));
  const soon = cal.items.filter((i) => i.date >= today && i.date <= weekEnd);
  const ev = soon.filter((i) => i.kind === 'event').length;
  const bk = soon.filter((i) => i.kind === 'booking').length;
  const thisWeek = [ev ? plural(ev, 'event') : '', bk ? plural(bk, 'booking') : ''].filter(Boolean).join(' and ');
  const sync = `<button class="gbtn wide" data-act="calsync" aria-label="Sync with Google or Apple Calendar">${ICON.calendarPlus}Sync</button>`;
  if (!cal.items.length && !cal.undated.length) {
    return `${navbar('Calendar', { ...backToTab(), right: sync })}<h1 class="largetitle" data-anchor>Calendar</h1>
      ${emptyState('event', 'calendar', 'Nothing on your calendar yet',
        'Save a reel about a pop-up, a class or a show and it lands here on its date. Bookings and planned trip days appear too.')}`;
  }
  return {
    html: `${navbar('Calendar', { ...backToTab(), right: sync })}<h1 class="largetitle" data-anchor>Calendar</h1>
      <div class="subtitle"><span>${thisWeek ? `${thisWeek} in the next 7 days` : 'No events or bookings in the next 7 days'}</span></div>
      ${chips}${grid}<div class="agenda">${agenda}</div>${undatedHtml}`,
    after: () => { if (c.scrollTo) { const el = document.getElementById(`ag-${c.scrollTo}`); c.scrollTo = null; if (el) el.scrollIntoView({ block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth' }); } },
  };
}

function calItem(id) {
  return S.cal && S.cal.items.find((i) => i.id === id);
}

function addToCalendarSheet(it) {
  const abs = (u) => new URL(u, location.origin).href;
  openSheet({ type: 'actions', title: `Add “${it.title}” to`, actions: [
    { label: 'Google Calendar', run: () => window.open(it.google_url, '_blank', 'noopener') },
    { label: 'Apple Calendar', run: () => { location.href = abs(it.ics_url); } },
    { label: 'Outlook or another app (.ics)', run: () => window.open(abs(it.ics_url), '_blank', 'noopener') },
  ] });
}

async function calSyncSheet() {
  const cal = await loadCal();
  const st = { feed: cal.feed };
  openSheet({
    type: 'form', title: 'Sync your calendar', st,
    body: () => st.feed ? `<div class="section"><div class="group tiles">
        <a class="row" href="${esc(st.feed.webcal_url)}">${tile('red', 'calendar')}<span class="main"><span class="t">Apple Calendar</span><span class="s">Subscribe on this iPhone or Mac</span></span>${ICON.chev}</a>
        <a class="row" href="${esc(st.feed.google_url)}" target="_blank" rel="noopener">${tile('blue', 'calendar')}<span class="main"><span class="t">Google Calendar</span><span class="s">Adds it under “Other calendars”</span></span>${ICON.chev}</a>
        <button class="row" data-act="copy" data-value="${esc(st.feed.url)}">${tile('gray', 'link')}<span class="main"><span class="t">Copy link</span><span class="s">For Outlook or any calendar app</span></span></button>
      </div><div class="section-f">New events, bookings and plans keep flowing in. Apple Calendar refreshes on its own schedule; Google can take a few hours. This link is private: anyone who has it can see your calendar.</div></div>
      <div class="section"><div class="group"><button class="row" data-act="calfeedoff"><span class="main"><span class="t" style="color:var(--warn)">Turn off this link</span></span></button></div></div>`
      : `<div class="section"><div class="group tiles"><div class="row">${tile('event', 'calendar')}<span class="main"><span class="t">See The Travel Edit in your calendar</span>
        <span class="s">Events, bookings and planned days show up in Google or Apple Calendar and stay up to date.</span></span></div></div>
        <div class="section"><button class="btn wide" data-act="calfeedon">Turn on calendar sync</button></div>
        <div class="section-f">To add just one event, tap the calendar button next to it instead.</div></div>`,
  });
}

function eventDateSheet(p) {
  const st = { date: p.event_date || '', end: p.event_end_date || '', time: p.start_time || '' };
  openSheet({
    type: 'form', title: p.event_date ? 'Change date' : 'When is it?', confirm: 'Save', st,
    body: () => `<div class="section"><div class="group tiles">
      <label class="row">${tile('event', 'calendar')}<span class="main"><span class="t">Date</span></span><input class="datefield" type="date" id="ev-date" value="${esc(st.date)}"></label>
      <label class="row">${tile('indigo', 'clock')}<span class="main"><span class="t">Starts at</span><span class="s">Optional</span></span><input class="datefield" type="time" id="ev-time" value="${esc(st.time)}"></label>
      <label class="row">${tile('gray', 'calendar')}<span class="main"><span class="t">Ends on</span><span class="s">For a pop-up that runs several days</span></span><input class="datefield" type="date" id="ev-end" value="${esc(st.end)}"></label>
      </div></div>
      ${p.event_date ? `<div class="section"><div class="group"><button class="row" data-act="eventdateclear" data-id="${p.id}"><span class="main"><span class="t" style="color:var(--warn)">Remove the date</span></span></button></div></div>` : ''}`,
    async ok() {
      const date = $('#ev-date').value;
      if (!date) { toast('Pick a date first', true); return; }
      const end = $('#ev-end').value;
      const time = $('#ev-time').value;
      const fresh = await api(`/v1/places/${p.id}`, { method: 'PATCH', body: {
        event_date: date, event_end_date: end && end > date ? end : null, ...(time ? { start_time: time } : { clear_start_time: true }) } });
      afterPlaceChange(fresh);
      closeSheet();
      toast(`On your calendar for ${shortDay(date)}`);
      render();
    },
  });
}

function afterPlaceChange(fresh) {
  const trip = S.trip[fresh.trip_id];
  if (trip) trip.places = trip.places.map((x) => (x.id === fresh.id ? fresh : x));
  if (S.places) S.places = S.places.map((x) => (x.id === fresh.id ? fresh : x));
  fetchedAt.cal = 0;
  loadCal().then(() => render({ quiet: true })).catch(() => {});
}

/** On an event's page: when it is, with a way to set the date or add it to a calendar app. */
function eventWhen(p) {
  if (p.category !== 'event') return '';
  const when = p.event_date
    ? `${shortDay(p.event_date)}${p.event_end_date ? ` – ${shortDay(p.event_end_date)}` : ''}${p.start_time ? ` · ${fmtClock(p.start_time)}` : ''}`
    : 'No date yet';
  return `<div class="section"><div class="group tiles"><div class="row">${tile('event', 'calendar')}
    <span class="main"><span class="s">When</span><span class="t">${esc(when)}</span>${p.venue ? `<span class="s">${esc(p.venue)}</span>` : ''}</span>
    <button class="linkbtn" data-act="eventdate" data-id="${p.id}">${p.event_date ? 'Change' : 'Set date'}</button></div>
    ${p.event_date ? `<button class="row" data-act="eventcal" data-id="${p.id}">${tile('red', 'calendarPlus')}<span class="main"><span class="t link">Add to Google or Apple Calendar</span></span>${ICON.chev}</button>` : ''}
  </div></div>`;
}

// ---------- Bookings tab ----------

const loadAllBookings = () => once('allbookings', async () => { S.bookingsAll = await api('/v1/bookings'); fetchedAt.allbookings = Date.now(); return S.bookingsAll; });
const cachedAllBookings = () => { if (!S.bookingsAll) return loadAllBookings(); revalidate('allbookings', loadAllBookings); return S.bookingsAll; };
const BK_FILTERS = [['all', 'All'], ['flight', 'Flights'], ['hotel', 'Stays'], ['reservation', 'Tables'], ['car', 'Cars'], ['other', 'Other']];
const bookingEnd = (b) => (b.end_at || b.start_at || '').slice(0, 10);

/** The trip a new booking most likely belongs to: the one happening now, else the next one, else the newest. */
function likelyTrip(trips) {
  const list = trips.filter((t) => t.kind !== 'local');
  const active = activeTrip(list);
  if (active) return active.trip;
  const today = isoDate(new Date());
  const next = list.filter((t) => t.start_date && t.start_date >= today).sort((a, b) => a.start_date.localeCompare(b.start_date))[0];
  return next || list[0] || trips[0] || null;
}

async function bookingsTab(r) {
  const [all, trips] = await Promise.all([cachedAllBookings(), cachedTrips()]);
  const b = S.bk;
  if (r.params.get('trip')) b.trip = r.params.get('trip');
  if (b.trip !== 'all' && !trips.some((t) => t.id === b.trip)) b.trip = 'all';
  const inTrip = all.filter((x) => b.trip === 'all' || x.trip_id === b.trip);
  const present = new Set(inTrip.map((x) => x.kind));
  if (b.kind !== 'all' && !present.has(b.kind)) b.kind = 'all';
  const list = inTrip.filter((x) => b.kind === 'all' || x.kind === b.kind);
  const today = isoDate(new Date());
  const upcoming = list.filter((x) => x.start_at && bookingEnd(x) >= today);
  const undated = list.filter((x) => !x.start_at);
  const past = list.filter((x) => x.start_at && bookingEnd(x) < today).reverse();
  const tripName = Object.fromEntries(trips.map((t) => [t.id, t.name]));
  const card = (x) => bookingCard(x, { trip: b.trip === 'all' ? tripName[x.trip_id] || x.trip_name : null });
  const byDate = (rows) => {
    const groups = [];
    rows.forEach((x) => {
      const key = x.start_at.slice(0, 10);
      const last = groups[groups.length - 1];
      if (last && last.key === key) last.items.push(x); else groups.push({ key, items: [x] });
    });
    return groups.map((g) => `<div class="datehead">${g.key === today ? 'Today · ' : ''}${esc(fmtDay(parseWhen(g.key).day))}</div>${g.items.map(card).join('')}`).join('');
  };
  const add = `<button class="gbtn tint" data-act="addbookingany" aria-label="Add a booking">${ICON.plus}</button>`;
  const head = `${rootNav('Bookings', { right: add })}<h1 class="largetitle" data-anchor>Bookings</h1>`;
  if (!all.length) {
    return head + emptyState('blue', 'bookings', 'No bookings yet',
      'Keep flights, stays, tables and car rentals in one place. Add one from a screenshot, the confirmation email, or type it in.',
      `<button class="btn" data-act="addbookingany">${ICON.plus}Add a booking</button>`);
  }
  const next = upcoming[0];
  const subtitle = next ? `Next: ${next.title} · ${next.start_at.slice(0, 10) === today ? 'today' : shortDay(next.start_at.slice(0, 10))}` : 'Nothing coming up';
  const tripsWith = trips.filter((t) => all.some((x) => x.trip_id === t.id));
  const chips = present.size > 1 ? `<div class="fchips" role="group" aria-label="Type">${BK_FILTERS.filter(([k]) => k === 'all' || present.has(k)).map(([k, label]) =>
    `<button class="fchip${b.kind === k ? ' on' : ''}" data-act="bkkind" data-k="${k}" aria-pressed="${b.kind === k}">${label}</button>`).join('')}</div>` : '';
  const ctl = tripsWith.length > 1 || b.trip !== 'all' ? `<div class="homectl"><button class="pillbtn" data-act="bktrip">${esc(b.trip === 'all' ? 'All trips' : tripName[b.trip])}</button></div>` : '';
  const body = `${upcoming.length ? byDate(upcoming) : `<div class="calempty">Nothing coming up${b.kind !== 'all' || b.trip !== 'all' ? ' here' : ''}.</div>`}
    ${undated.length ? `<div class="datehead">No date</div>${undated.map(card).join('')}` : ''}
    ${past.length ? `<div class="section"><button class="btn tint wide" data-act="bkpast" aria-expanded="${b.past}">${b.past ? 'Hide' : 'Show'} past bookings (${past.length})</button></div>
      ${b.past ? byDate(past) : ''}` : ''}
    <div class="section-f bkfoot">Bookings stay private: shared trip links never include them.</div>`;
  return `${head}<div class="subtitle"><span>${esc(subtitle)}</span></div>${chips}${ctl}${body}`;
}

/** What you can do with a booking: lounges for a flight, edit, copy the reference, delete. */
function bookingActions(trip, b) {
  const actions = [{ label: 'Edit', run: () => bookingForm(trip, b, { id: b.id }) }];
  if (b.kind === 'flight' && b.origin) actions.unshift({ label: `Airport lounges at ${b.origin}`, run: () => loungeSheet(trip, b) });
  if (b.place_id) actions.push({ label: 'Open place', run: () => go(`#/place/${b.place_id}`) });
  if (b.confirmation) actions.push({ label: 'Copy confirmation number', run: async () => { try { await navigator.clipboard.writeText(b.confirmation); toast('Copied'); } catch { toast(b.confirmation); } } });
  actions.push({ label: 'Delete booking', destructive: true, run: async () => {
    syncTrip(await api(`/v1/trips/${trip.id}/bookings/${b.id}`, { method: 'DELETE' }));
    toast('Booking deleted');
    render();
  } });
  return actions;
}

async function bookingWithTrip(id) {
  let trip = Object.values(S.trip).find((t) => (t.bookings || []).some((x) => x.id === id));
  if (!trip) {
    const row = (S.bookingsAll || []).find((x) => x.id === id);
    if (row) trip = await loadTrip(row.trip_id);
  }
  const b = trip && trip.bookings.find((x) => x.id === id);
  return b ? { trip, b } : {};
}

// ---------- Library: saved places and folders ----------

const loadFolders = () => once('folders', async () => { S.folders = await api('/v1/folders'); fetchedAt.folders = Date.now(); return S.folders; });
const cachedFolders = () => { if (!S.folders) return loadFolders(); revalidate('folders', loadFolders); return S.folders; };
const placeHref = (p, suffix = '') => `#/place/${p.id}${suffix}${p.trip_id ? `?trip=${p.trip_id}` : ''}`;
/** Filters for a list of saved places, kept per list (Saved, or a folder). */
const libFilter = (scope) => (S.libf[scope] ||= { cats: new Set(), cities: new Set(), starred: false, unplanned: false, q: '' });
const libActive = (f) => f.cats.size + f.cities.size + (f.starred ? 1 : 0) + (f.unplanned ? 1 : 0) + (f.q ? 1 : 0);

function filterSaved(list, f) {
  const q = normText(f.q);
  return list.filter((p) => (!f.cats.size || f.cats.has(GROUP_OF[p.category] || 'other'))
    && (!f.cities.size || f.cities.has(p.city || 'Somewhere'))
    && (!f.starred || p.must_do)
    && (!f.unplanned || !p.trip_ids.length)
    && (!q || normText(`${p.name} ${p.neighborhood || ''} ${p.city || ''} ${p.venue || ''}`).includes(q)));
}
function normText(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim(); }

/** Search, type chips (pick several), more filters, sort and select, above a list of saved places. */
function libControls(scope, places) {
  const f = libFilter(scope);
  const counts = {};
  places.forEach((p) => { const g = GROUP_OF[p.category] || 'other'; counts[g] = (counts[g] || 0) + 1; });
  const more = f.cities.size + (f.unplanned ? 1 : 0);
  return `<div class="libsearch"><label class="searchbox">${ICON.search}<input type="search" data-act="libq" data-scope="${esc(scope)}" value="${esc(f.q)}"
      placeholder="Search your saved places" aria-label="Search your saved places" autocomplete="off" enterkeyhint="search"></label></div>
    <div class="fchips" role="group" aria-label="Filter by type (choose any)">
      <button class="fchip star${f.starred ? ' on' : ''}" data-act="libstar" data-scope="${esc(scope)}" aria-pressed="${f.starred}">${ICON.star}Starred</button>
      ${GROUPS.filter((g) => counts[g.id]).map((g) => `<button class="fchip${f.cats.has(g.id) ? ' on' : ''}" data-act="libcat" data-scope="${esc(scope)}" data-cat="${g.id}" aria-pressed="${f.cats.has(g.id)}">${g.label}<span class="n">${counts[g.id]}</span></button>`).join('')}
    </div>
    <div class="homectl">
      <button class="pillbtn${more ? ' on' : ''}" data-act="libmore" data-scope="${esc(scope)}">${more ? `Filters · ${more}` : 'More filters'}</button>
      <button class="pillbtn" data-act="homesort" aria-label="Sort: ${esc(SORTS[S.home.sort].label)}">${esc(SORTS[S.home.sort].label)}</button>
      <button class="pillbtn${S.sel.on ? ' on' : ''}" data-act="selecttoggle">${S.sel.on ? 'Done' : 'Select'}</button>
      ${libActive(f) ? `<button class="linkbtn" data-act="libclear" data-scope="${esc(scope)}">Clear</button>` : ''}</div>`;
}

/** The list itself (redrawn in place while typing in the search box). */
function libList(scope, places) {
  const f = libFilter(scope);
  const list = sortPlaces(filterSaved(places, f), S.home.sort);
  if (!places.length) return '';
  if (!list.length) {
    return emptyState('gray', 'pinslash', 'Nothing matches', f.q ? `No saved place matches “${esc(f.q)}”.` : 'Try fewer filters.',
      `<button class="btn tint" data-act="libclear" data-scope="${esc(scope)}">Clear filters</button>`);
  }
  return `<div class="libcount">${libActive(f) ? `${plural(list.length, 'place')} match` : plural(list.length, 'place')}</div>
    <div class="section"><div class="group thumbs">${list.map((p) => placeRow(p, { home: true })).join('')}</div></div>`;
}

function folderCard(fo) {
  const imgs = fo.covers.slice(0, 4);
  const cover = imgs.length >= 3
    ? `<span class="fcover grid">${imgs.slice(0, 4).map((c) => `<img src="${esc(photoUrl(c, 300))}" alt="" loading="lazy" decoding="async" onerror="this.remove()">`).join('')}</span>`
    : imgs.length ? `<span class="fcover"><img src="${esc(photoUrl(imgs[0], 500))}" alt="" loading="lazy" decoding="async" onerror="this.remove()"></span>`
      : `<span class="fcover empty">${ICON.folder}</span>`;
  return `<a class="fcard" href="#/folder/${fo.id}">${cover}<span class="fname">${esc(fo.name)}</span><span class="fcount">${plural(fo.place_count, 'place')}</span></a>`;
}

async function savedView(r) {
  const [places, folders] = await Promise.all([cachedPlaces(), cachedFolders()]);
  const reel = r.params.get('reel');
  const shown = reel ? places.filter((p) => p.reel_ids.includes(reel)) : places;
  const strip = `<div class="section"><div class="section-h hrow"><span>Your folders</span>
      ${folders.length ? '<button class="linkbtn" data-act="newfolder">New folder</button>' : ''}</div>
    <div class="folders" role="list">
      ${folders.map(folderCard).join('')}
      <button class="fcard new" data-act="newfolder"><span class="fcover empty">${ICON.plus}</span><span class="fname">New folder</span>
        <span class="fcount">${folders.length ? 'Name it anything' : 'e.g. Date night, Brunch'}</span></button>
    </div></div>`;
  const banner = reel ? `<div class="reelbanner">${ICON.link}<span>${plural(shown.length, 'place')} from one post</span><a class="linkbtn" href="#/saved">Show everything</a></div>` : '';
  const body = !places.length
    ? emptyState('accent', 'bookmark', 'Nothing saved yet',
      'Share a TikTok or Instagram post to Travel Edit, paste a link, or search for a place. Everything you save lands here, ready to sort into folders and trips.',
      `<button class="btn" data-act="add">${ICON.plus}Add a place</button><a class="linkbtn" href="#/profile">Set up the share button</a>`)
    : `<div class="section-h hrow libhead"><span>All saved</span></div>${libControls('saved', shown)}<div id="libbody" data-scope="saved">${libList('saved', shown)}</div>`;
  return `${strip}${banner}${body}${selBar()}`;
}

async function folderView(r) {
  const [places, folders] = await Promise.all([cachedPlaces(), cachedFolders()]);
  const fo = folders.find((x) => x.id === r.id);
  if (!fo) throw new ApiError('This folder was deleted.', 404);
  const inside = places.filter((p) => p.folder_ids.includes(fo.id));
  const more = `<button class="gbtn" data-act="foldermenu" data-id="${fo.id}" aria-label="Folder options">${ICON.more}</button>`;
  const head = `${navbar(fo.name, { back: '#/library', backLabel: 'Library', right: more })}<h1 class="largetitle" data-anchor>${esc(fo.name)}</h1>
    <div class="subtitle"><span>${plural(inside.length, 'place')}</span></div>
    <div class="actionsrow"><button class="btn tint small" data-act="folderadd" data-id="${fo.id}">${ICON.plus}Add places</button>
      ${inside.length ? `<button class="btn small" data-act="newtrip" data-folder="${fo.id}">${ICON.plane}Plan a trip from this</button>` : ''}</div>`;
  if (!inside.length) {
    return head + emptyState('gray', 'folder', 'This folder is empty', 'Add places from everything you’ve saved. A place can be in as many folders as you like.',
      `<button class="btn" data-act="folderadd" data-id="${fo.id}">${ICON.plus}Add places</button>`);
  }
  return `${head}${libControls(fo.id, inside)}<div id="libbody" data-scope="${fo.id}">${libList(fo.id, inside)}</div>${selBar()}`;
}

/** Redraws a saved-places list after the search text changes, without touching the search box. */
function redrawLibList(scope) {
  const box = document.getElementById('libbody');
  if (!box || box.dataset.scope !== scope || !S.places) return;
  const places = scope === 'saved' ? S.places
    : scope.startsWith('city:') ? byVisit(savedOnly(S.places).filter((p) => p.city && cityKey(p.city) === scope.slice(5)))
      : S.places.filter((p) => p.folder_ids.includes(scope));
  box.innerHTML = libList(scope, places);
  hydrateIcons(box);
}

function libMoreSheet(scope) {
  const f = libFilter(scope);
  const base = scope === 'saved' ? S.places || [] : (S.places || []).filter((p) => p.folder_ids.includes(scope));
  const cities = {};
  base.forEach((p) => { const c = p.city || 'Somewhere'; cities[c] = (cities[c] || 0) + 1; });
  const st = { cities: new Set(f.cities), unplanned: f.unplanned };
  openSheet({
    type: 'form', title: 'Filters', confirm: 'Show', st,
    body: () => `<div class="section"><div class="section-h">City</div><div class="fchips wrap">
        ${Object.entries(cities).sort((a, b) => b[1] - a[1]).map(([c, n]) => `<button class="fchip${st.cities.has(c) ? ' on' : ''}" data-act="libcity" data-city="${esc(c)}" aria-pressed="${st.cities.has(c)}">${esc(c)}<span class="n">${n}</span></button>`).join('')}
      </div></div>
      <div class="section"><div class="group tiles"><label class="row" for="lib-unplanned">${tile('blue', 'trips')}<span class="main"><span class="t">Not in a trip yet</span></span>
        <input class="switch" type="checkbox" id="lib-unplanned" data-act="libunplanned" ${st.unplanned ? 'checked' : ''}></label></div>
      <div class="section-f">Pick as many as you like. Type chips and the search box add to these.</div></div>`,
    ok() {
      f.cities = st.cities; f.unplanned = st.unplanned;
      closeSheet(); render({ quiet: true });
    },
  });
}

/** Tick saved places from everything (or one folder) and search; used to fill folders and trips. */
function pickerBody(st) {
  const folders = S.folders || [];
  const q = normText(st.q);
  const pool = (S.places || []).filter((p) => !st.exclude.has(p.id)
    && (st.folder === 'all' || p.folder_ids.includes(st.folder))
    && (!q || normText(`${p.name} ${p.city} ${p.neighborhood || ''}`).includes(q)));
  pool.sort((a, b) => (st.picked.has(b.id) - st.picked.has(a.id)) || (Number(b.must_do) - Number(a.must_do)) || a.name.localeCompare(b.name));
  const rows = pool.map((p) => {
    const on = st.picked.has(p.id);
    return `<button class="row prow sel${on ? ' picked' : ''}" data-act="sheetpick" data-id="${p.id}" aria-pressed="${on}"><span class="check" aria-hidden="true">${on ? ICON.done : ''}</span>${thumb(p, 44)}
      <span class="main"><span class="t">${esc(p.name)}${starMark(p)}</span><span class="s">${esc([CATS[p.category], p.neighborhood || p.city].filter(Boolean).join(' · '))}</span></span></button>`;
  }).join('');
  return `<div class="libsearch"><label class="searchbox">${ICON.search}<input type="search" data-act="pkq" value="${esc(st.q)}" placeholder="Search your saved places" aria-label="Search" autocomplete="off"></label></div>
    ${folders.length ? `<div class="fchips" role="group" aria-label="From">
      <button class="fchip${st.folder === 'all' ? ' on' : ''}" data-act="pkfolder" data-f="all">All saved</button>
      ${folders.map((fo) => `<button class="fchip${st.folder === fo.id ? ' on' : ''}" data-act="pkfolder" data-f="${fo.id}">${ICON.folder}${esc(fo.name)}</button>`).join('')}</div>` : ''}
    <div class="section" id="pklist">${pool.length ? `<div class="group thumbs">${rows}</div>` : '<div class="section-f">Nothing here to add.</div>'}</div>`;
}

async function pickSavedSheet({ title, exclude = new Set(), confirm = 'Add', onDone }) {
  await Promise.all([cachedPlaces(), cachedFolders()]);
  const st = { picked: new Set(), q: '', folder: 'all', exclude };
  openSheet({
    type: 'form', title, confirm, st,
    body: () => pickerBody(st),
    async ok() {
      if (!st.picked.size) { toast('Tick at least one place', true); return; }
      S.sheet.busy = true; renderOverlay();
      try { await onDone([...st.picked]); closeSheet(); } catch (e) { S.sheet.busy = false; renderOverlay(); toast(e.message, true); }
    },
  });
}

function folderNameSheet({ title = 'New list', name = '', confirm = 'Create', onDone }) {
  openSheet({
    type: 'form', title, confirm, st: {},
    body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="folder-name" value="${esc(name)}" maxlength="80"
      placeholder="e.g. Date night, Brunch spots, Paris someday" aria-label="List name" autocomplete="off"></div></div></div>`,
    async ok() {
      const value = $('#folder-name').value.trim();
      if (!value) { toast('Give the list a name', true); return; }
      S.sheet.busy = true; renderOverlay();
      try { await onDone(value); } catch (e) { S.sheet.busy = false; renderOverlay(); toast(e.message, true); }
    },
  });
}

function afterLibraryChange() {
  fetchedAt.folders = 0; fetchedAt.places = 0; fetchedAt.trips = 0;
  return Promise.all([loadFolders(), loadPlaces()]).catch(() => {});
}

async function addToFolderSheet(ids) {
  const folders = await cachedFolders();
  const add = async (fid, name) => {
    await api(`/v1/folders/${fid}/places`, { method: 'POST', body: { place_ids: ids } });
    await afterLibraryChange(); resetSel();
    toast(`Added ${plural(ids.length, 'place')} to ${name}`); render();
  };
  openSheet({ type: 'actions', title: `Add ${plural(ids.length, 'place')} to a folder`, actions: [
    ...folders.map((fo) => ({ label: fo.name, run: () => add(fo.id, fo.name) })),
    { label: 'New folder…', run: () => folderNameSheet({ onDone: async (name) => {
      const fo = await api('/v1/folders', { method: 'POST', body: { name, place_ids: ids } });
      closeSheet(); await afterLibraryChange(); resetSel();
      toast(`Made ${fo.name} with ${plural(ids.length, 'place')}`); render();
    } }) },
  ] });
}

async function addToTripSheet(ids) {
  const trips = await cachedTrips();
  openSheet({ type: 'actions', title: `Add ${plural(ids.length, 'place')} to a trip`, actions: [
    ...trips.map((t) => ({ label: t.name, run: async () => {
      syncTrip(await api(`/v1/trips/${t.id}/places`, { method: 'POST', body: { place_ids: ids } }));
      await afterLibraryChange(); resetSel();
      toast(`Added to ${t.name}`); render();
    } })),
    { label: 'New trip with these…', run: () => newTripSheet({ placeIds: ids }) },
  ] });
}

// ---------- A place's folders and trips ----------

const placeDetail = {}; // id -> {place, reels} for places opened outside a trip
const loadPlaceDetail = (id) => once(`pd:${id}`, async () => { placeDetail[id] = await api(`/v1/places/${id}`); fetchedAt[`pd:${id}`] = Date.now(); return placeDetail[id]; });
const cachedPlaceDetail = (id) => { if (!placeDetail[id]) return loadPlaceDetail(id); revalidate(`pd:${id}`, () => loadPlaceDetail(id)); return placeDetail[id]; };
/** The trip a place is being looked at in (from the page address), if any. */
const contextTrip = () => { const r = route(); return r.name === 'trip' ? r.id : (r.name === 'place' ? r.params.get('trip') : null); };

async function placeFoldersSheet(id) {
  const [folders, places] = await Promise.all([cachedFolders(), cachedPlaces()]);
  const p = places.find((x) => x.id === id) || findAnyPlace(id);
  const st = { place: id, inside: new Set(p ? p.folder_ids : []) };
  openSheet({
    type: 'form', title: 'Folders', confirm: 'Done', st,
    body: () => `<div class="section">${folders.length ? `<div class="group tiles">${folders.map((fo) => {
      const on = st.inside.has(fo.id);
      return `<button class="row prow sel${on ? ' picked' : ''}" data-act="pffolder" data-f="${fo.id}" aria-pressed="${on}"><span class="check" aria-hidden="true">${on ? ICON.done : ''}</span>
        ${tile('gold', 'folder')}<span class="main"><span class="t">${esc(fo.name)}</span><span class="s">${plural(fo.place_count, 'place')}</span></span></button>`;
    }).join('')}</div>` : '<div class="section-f">No folders yet.</div>'}
      <div class="section"><button class="btn tint wide" data-act="pfnew" data-id="${id}">${ICON.plus}New folder</button></div>
      <div class="section-f">A place can be in as many folders as you like.</div></div>`,
    ok() { closeSheet(); render(); },
  });
}

async function placeTripsSheet(id) {
  const trips = await cachedTrips();
  const places = await cachedPlaces();
  const p = places.find((x) => x.id === id) || findAnyPlace(id);
  const inTrips = new Set(p ? p.trip_ids : []);
  openSheet({ type: 'actions', title: `Add ${p ? p.name : 'this place'} to a trip`, actions: [
    ...trips.map((t) => ({ label: `${inTrips.has(t.id) ? '✓ ' : ''}${t.name}`, run: async () => {
      if (inTrips.has(t.id)) { go(`#/trip/${t.id}`); return; }
      syncTrip(await api(`/v1/trips/${t.id}/places`, { method: 'POST', body: { place_ids: [id] } }));
      await afterLibraryChange(); delete placeDetail[id];
      toast(`Added to ${t.name}`); render();
    } })),
    { label: 'New trip with this place…', run: () => newTripSheet({ placeIds: [id] }) },
  ] });
}

/** A booking belongs to a trip: use the one the place is on, or ask (and add the place to it). */
async function withTripFor(p, then) {
  if (p.trip_id && S.trip[p.trip_id]) { then(S.trip[p.trip_id]); return; }
  const trips = await cachedTrips();
  const mine = trips.filter((t) => (p.trip_ids || []).includes(t.id));
  if (mine.length === 1) { then(await loadTrip(mine[0].id)); return; }
  const list = mine.length ? mine : trips;
  if (!list.length) { toast('Make a trip first to keep bookings with it', true); return; }
  openSheet({ type: 'actions', title: 'Which trip is this for?', actions: list.map((t) => ({ label: t.name, run: async () => {
    if (!(p.trip_ids || []).includes(t.id)) syncTrip(await api(`/v1/trips/${t.id}/places`, { method: 'POST', body: { place_ids: [p.id] } }));
    then(await loadTrip(t.id));
  } })) });
}

// ---------- New trip ----------

/** Make a trip in three short steps: where and how long, who plans it, which places. */
async function newTripSheet({ placeIds = [], folderId = null } = {}) {
  const [places] = await Promise.all([cachedPlaces(), cachedFolders()]);
  const fromFolder = folderId ? places.filter((p) => p.folder_ids.includes(folderId)).map((p) => p.id) : [];
  const picked = new Set([...placeIds, ...fromFolder]);
  const cities = {};
  places.forEach((p) => { if (p.city) cities[p.city] = (cities[p.city] || 0) + 1; });
  const guess = [...picked].map((id) => places.find((p) => p.id === id)).filter(Boolean).map((p) => p.city).find(Boolean) || '';
  const st = { step: 1, city: guess, name: '', days: 3, start: '', mode: null, fill: true, prefs: '', picked, q: '', folder: 'all', exclude: new Set(), touched: picked.size > 0 };
  const steps = (n) => `<div class="steps-dots" aria-label="Step ${n} of 3">${[1, 2, 3].map((i) => `<i class="${i <= n ? 'on' : ''}"></i>`).join('')}</div>`;
  const back = '<button class="linkbtn backstep" data-act="ntback">‹ Back</button>';
  const body = () => {
    if (st.step === 1) {
      const sugg = Object.entries(cities).sort((a, b) => b[1] - a[1]).slice(0, 6);
      return `${steps(1)}<div class="section"><div class="section-h">Where to?</div><div class="group"><div class="row">
          <input class="field" data-act="ntfield" data-f="city" value="${esc(st.city)}" placeholder="City, e.g. Lisbon" aria-label="City" autocomplete="off" autocapitalize="words"></div></div>
        ${sugg.length ? `<div class="fchips wrap">${sugg.map(([c, n]) => `<button class="fchip${normText(c) === normText(st.city) ? ' on' : ''}" data-act="ntcity" data-city="${esc(c)}">${esc(c)}<span class="n">${n}</span></button>`).join('')}</div>
          <div class="section-f">Cities you’ve saved places in.</div>` : ''}</div>
        <div class="section"><div class="group tiles">
          <div class="row"><span class="main"><span class="t">Trip name</span></span><input class="field right" data-act="ntfield" data-f="name" value="${esc(st.name)}" placeholder="${esc(st.city ? `${st.city} trip` : 'Optional')}" aria-label="Trip name" maxlength="120"></div>
          <div class="row"><span class="main"><span class="t">Days</span></span>
            <span class="stepper"><button class="gbtn small" data-act="ntdays" data-d="-1" aria-label="One day fewer" ${st.days <= 1 ? 'disabled' : ''}>−</button>
            <b aria-live="polite">${st.days}</b><button class="gbtn small" data-act="ntdays" data-d="1" aria-label="One more day" ${st.days >= 21 ? 'disabled' : ''}>+</button></span></div>
          <label class="row"><span class="main"><span class="t">Start date</span><span class="s">Optional</span></span><input class="datefield" type="date" data-act="ntfield" data-f="start" value="${esc(st.start)}"></label>
        </div></div>
        <div class="section"><button class="btn wide" data-act="sheetok">Next</button></div>`;
    }
    if (st.step === 2) {
      const card = (m, icon, title, text) => `<button class="choice${st.mode === m ? ' on' : ''}" data-act="ntmode" data-m="${m}">${tile(m === 'ai' ? 'gold' : 'indigo', icon, 'md')}
        <span class="main"><span class="t">${title}</span><span class="s">${text}</span></span>${ICON.chev}</button>`;
      return `${steps(2)}${back}<div class="section"><div class="section-h">How would you like to plan it?</div>
        ${card('ai', 'sparkle', 'Plan it for me', `AI arranges your places into ${plural(st.days, 'day')}, grouped by area with sensible times. It can suggest a few extras for quiet days.`)}
        ${card('manual', 'calendar', 'I’ll build it myself', `${plural(st.days, 'empty day')} for you to fill from your saved places. You can ask AI to tidy it later.`)}</div>`;
    }
    const n = st.picked.size;
    return `${steps(3)}${back}<div class="section-h pad">${n ? `${plural(n, 'place')} picked` : 'Pick places to include'}${st.city ? ` · ${esc(st.city)}` : ''}</div>
      ${st.mode === 'ai' ? `<div class="section"><div class="group tiles">
        <label class="row" for="nt-fill">${tile('gold', 'sparkle')}<span class="main"><span class="t">Suggest places for quiet days</span><span class="s">Marked “Suggested”, easy to keep or remove</span></span>
          <input class="switch" type="checkbox" id="nt-fill" data-act="ntfill" ${st.fill ? 'checked' : ''}></label>
        <div class="row"><input class="field" data-act="ntfield" data-f="prefs" value="${esc(st.prefs)}" placeholder="Anything to keep in mind? e.g. slow mornings, no museums" aria-label="Preferences" maxlength="1000"></div>
      </div></div>` : ''}
      ${pickerBody(st)}
      <div class="stickycta"><button class="btn wide" data-act="sheetok">${st.mode === 'ai' ? `${ICON.sparkle}Plan my trip` : 'Create trip'}${n ? ` · ${plural(n, 'place')}` : ''}</button></div>`;
  };
  openSheet({
    type: 'form', title: 'New trip', confirm: 'Next', st, body,
    async ok() {
      if (st.step === 1) {
        st.city = st.city.trim();
        if (!st.city) { toast('Where are you going?', true); return; }
        if (!st.touched) { // start with everything saved in that city ticked
          places.filter((p) => normText(p.city) === normText(st.city)).forEach((p) => st.picked.add(p.id));
          st.touched = true;
        }
        st.step = 2; S.sheet.confirm = null; renderOverlay(); return;
      }
      if (st.step === 2) return;
      if (st.mode === 'ai' && !st.picked.size && !st.fill) { toast('Pick some places, or turn on suggestions', true); return; }
      S.sheet.busy = true; renderOverlay();
      try {
        const trip = await api('/v1/trips', { method: 'POST', body: {
          city: st.city, name: st.name.trim() || null, days: st.days, start_date: st.start || null, place_ids: [...st.picked],
          plan: st.mode, fill_gaps: st.mode === 'ai' && st.fill, preferences: st.prefs.trim() || null,
        } });
        S.trip[trip.id] = trip;
        await afterLibraryChange(); await loadTrips();
        resetSel(); closeSheet();
        toast(st.mode === 'ai' ? (trip.planned_by === 'claude' ? 'Your trip is planned' : 'Planned by location (AI unavailable)') : 'Your days are ready to fill');
        go(`#/trip/${trip.id}/itinerary`);
      } catch (e) {
        if (S.sheet) { S.sheet.busy = false; renderOverlay(); }
        toast(e.message, true);
      }
    },
  });
}

// ---------- Usage & costs (owner only) ----------

const FEATURE_LABEL = {
  import: 'Imports', plan: 'AI plans', tidy: 'Tidy with AI', suggest: 'Suggestions', concierge: 'Concierge',
  menu: 'Menus', menu_retry: 'Menus (extra tries)', menu_links: 'Menus (finding links)', bookings: 'Reading bookings',
  packing: 'Packing lists', edits: 'Edits', edits_research: 'Edits (web research)', discover: 'Discover notes',
  lounges: 'Lounges', booking_needs: 'Booking checks', events: 'What’s on', briefing: 'Daily briefings', other: 'Other',
};
const GOOGLE_LABEL = {
  locate: 'Place lookups', search: 'Place search', nearby: 'Discover nearby', details: 'Place details',
  menu_photos: 'Menu photo search', photo: 'Photos', routes: 'Travel times (per route)',
};
const money = (n) => (n > 0 && n < 0.01 ? '<$0.01' : `$${(n || 0).toFixed(2)}`);
const count = (n) => (n || 0).toLocaleString();

async function usageView() {
  const u = S.usage = await api('/v1/admin/usage');
  const budget = u.monthly_budget;
  const pct = budget ? Math.min(100, (u.month_cost / budget) * 100) : 0;
  const month = new Date(`${u.month}-01T12:00:00Z`).toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
  const day = (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
  const rows = (items, fn) => (items.length ? `<div class="group tiles">${items.map(fn).join('')}</div>` : '<div class="section-f">Nothing yet.</div>');
  const row = (t, s, v) => `<div class="row"><span class="main"><span class="t">${esc(t)}</span>${s ? `<span class="s">${esc(s)}</span>` : ''}</span><span class="val">${esc(v)}</span></div>`;
  const limits = Object.entries(u.limit_labels).map(([k, label]) => `${u.config[`limit_${k}`] || 'no limit'} ${label}`).join(' · ');
  return `${navbar('Usage & costs', { back: '#/profile', backLabel: 'Profile' })}
    <h1 class="largetitle" data-anchor>Usage & costs</h1>
    <div class="subtitle"><span>AI spend in ${esc(month)} (UTC), estimated from Claude’s token counts</span></div>

    <div class="section"><div class="group tiles">
      <div class="row"><span class="main"><span class="t">${money(u.month_cost)} of ${budget ? money(budget) : 'no budget'}</span>
        <span class="s">${u.paused ? 'Budget used up: AI is paused until next month' : budget ? `${Math.round(pct)}% of this month’s budget` : 'No monthly budget set'}</span>
        ${budget ? `<span class="progress big" style="margin-top:8px"><i style="width:${pct}%;${u.paused || pct >= 80 ? 'background:var(--danger)' : ''}"></i></span>` : ''}</span></div>
      ${row('Today', null, money(u.today_cost))}
      <button class="row" data-act="usagelimits">${tile('gray', 'lock')}<span class="main"><span class="t">Budgets and limits</span>
        <span class="s">${esc(`${money(u.config.user_daily_budget_usd)} a day per person · ${limits}`)}</span></span>${ICON.chev}</button>
    </div><div class="section-f">Emails from Sentry at 50%, 80% and 100% of the monthly budget. Your own use counts toward it, but per-person limits don’t apply to you.</div></div>

    <div class="section"><div class="section-h">By day</div>
      ${rows(u.days, (d) => row(day(d.day), `${count(d.calls)} AI calls`, money(d.cost)))}</div>

    <div class="section"><div class="section-h">By feature this month</div>
      ${rows(u.features, (f) => row(FEATURE_LABEL[f.feature] || f.feature,
        `${count(f.calls)} calls · ${count(f.input_tokens + f.output_tokens)} tokens${f.searches ? ` · ${count(f.searches)} web searches` : ''}`, money(f.cost)))}</div>

    <div class="section"><div class="section-h">By person this month</div>
      ${rows(u.people, (p) => row(p.email, `${count(p.calls)} AI calls · ${money(p.cost_today)} today`, money(p.cost_month)))}</div>

    <div class="section"><div class="section-h">Google Maps this month</div>
      ${rows(u.google, (g) => row(GOOGLE_LABEL[g.kind] || g.kind, `${count(g.calls)} calls`, money(g.cost)))}
      ${u.google.length ? `<div class="section-f">About ${money(u.google_cost)} at Google’s list prices, before its free monthly allowance (most small apps pay nothing). Billed by Google; not part of the AI budget.</div>` : ''}</div>`;
}

// ---------- Place page pieces ----------

/** "● Open now · until midnight · $$" */
function statusLine(p, st) {
  const price = p.price_hint && p.price_hint.length <= 5 ? p.price_hint : '';
  if (!st && !price) return '';
  const rest = st ? st.label.replace(/^Open until /, 'until ').replace(/^Closed · /, '').replace(/^Open now$/, '') : '';
  return `<span class="pstatus">${st ? `<i class="dot ${st.state === 'open' ? 'open' : ''}"></i><b class="${st.state === 'open' ? 'open' : ''}">${st.state === 'open' ? 'Open now' : 'Closed'}</b>${rest && !/^(Closed|Open 24 hours)$/.test(rest) ? ` · ${esc(rest)}` : ''}` : ''}${price ? `${st ? ' · ' : ''}${esc(price)}` : ''}</span>`;
}

/** The Reel you saved it from, what it said, and your own note. */
function whySaved(p, reels) {
  const reel = reels && reels[0];
  const quote = p.tips || (p.recommended_items[0] ? `Order the ${p.recommended_items[0]}.` : p.summary);
  const saved = p.created_at ? dayOf(p.created_at.slice(0, 10)).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : 'recently';
  const frame = (p.photos || []).find((ph) => ph.source === 'reel');
  const thumbSrc = frame ? photoUrl(frame, 240) : (reel && reel.thumbnail_url && safeUrl(reel.thumbnail_url)) || '';
  const url = reel && safeUrl(reel.url);
  const noteOpen = S.noteOpen && S.noteOpen[p.id];
  return `<h2 class="h2">Why you saved it</h2><div class="pcard why">
    ${reel ? `<a class="reelthumb" ${url ? `href="${esc(url)}" target="_blank" rel="noopener"` : ''} aria-label="Watch the Reel">${thumbSrc ? `<img src="${esc(thumbSrc)}" alt="" loading="lazy" onerror="this.remove()">` : ''}<span class="play">${ICON.play}</span></a>` : ''}
    <span class="m">
      <span class="t">${reel ? esc(reel.creator ? `@${reel.creator}` : platformName(reel.platform)) : 'Saved by you'}</span>
      <span class="s">${reel ? `From a Reel · saved ${esc(saved)}` : `Saved ${esc(saved)}`}</span>
      ${quote ? `<q>${esc(quote)}</q>` : ''}
      ${url ? `<a class="tlink" href="${esc(url)}" target="_blank" rel="noopener">Watch the Reel</a>` : ''}
      ${p.mention_count >= 2 ? `<span class="s">In ${p.mention_count} of your saved Reels</span>` : ''}
    </span>
    ${noteOpen || p.user_notes ? `<textarea class="notes" id="notes" data-act="notes" data-id="${p.id}" placeholder="Your note" rows="2" aria-label="Your note">${esc(p.user_notes)}</textarea>` : ''}
  </div>${noteOpen || p.user_notes ? '' : `<button class="tbtn quietbtn" data-act="shownote" data-id="${p.id}">${ICON.note}Add your own note</button>`}`;
}

function bookedOn(p, trip) { return !!(trip && (trip.bookings || []).some((b) => b.place_id === p.id && b.kind === 'reservation')); }
function mainKind(p, trip) {
  if (!bookedOn(p, trip) && safeUrl(p.reserve_url)) return 'reserve';
  if (p.booking_kind === 'tickets' && p.booking_need && safeUrl(p.website)) return 'tickets';
  return 'directions';
}

/** One main button (Book a table, Get tickets, or Directions) and what to know about booking. */
function mainAction(p, trip) {
  const kind = mainKind(p, trip);
  const links = mapsLinks(p, trip || { places: [p] });
  const button = kind === 'reserve'
    ? `<a class="btn wide" href="${esc(p.reserve_url)}" target="_blank" rel="noopener" data-reserve="${p.id}" data-act="link">${ICON.calendar}Book a table</a>`
    : kind === 'tickets'
      ? `<a class="btn wide" href="${esc(p.website)}" target="_blank" rel="noopener">${ICON.ticket}Get tickets</a>`
      : `<button class="btn wide" data-act="directionsmenu" data-apple="${esc(links.apple)}" data-google="${esc(links.google)}">${ICON.route}Directions</button>`;
  let need = '';
  if (p.booking_need && p.booking_need !== 'none') {
    const req = p.booking_need === 'required';
    const text = p.booking_kind === 'tickets' ? (req ? 'Tickets needed' : 'Tickets recommended') : (req ? 'Book ahead' : 'Booking recommended');
    need = `<p class="needhint${req ? ' attn' : ''}">${ICON.info}${esc(text)}.${p.booking_note ? ` ${esc(p.booking_note)}` : ''}</p>`;
  }
  return `<div class="mainact">${button}${need}</div>`;
}

/** Quiet buttons: Directions (unless it's the main one), Menu, Call, Website. */
function quietActions(p, trip) {
  const kind = mainKind(p, trip);
  const links = mapsLinks(p, trip || { places: [p] });
  const out = [];
  if (kind !== 'directions') out.push(`<button class="qtile" data-act="directionsmenu" data-apple="${esc(links.apple)}" data-google="${esc(links.google)}">${ICON.route}Directions</button>`);
  if (MENU_CATS.has(p.category)) out.push(`<a class="qtile" href="${placeHref(p, '/menu')}">${ICON.menu}Menu</a>`);
  if (p.phone) out.push(`<a class="qtile" href="tel:${esc(p.phone.replace(/[^\d+]/g, ''))}">${ICON.phone}Call</a>`);
  if (safeUrl(p.website) && kind !== 'tickets') out.push(`<a class="qtile" href="${esc(p.website)}" target="_blank" rel="noopener">${ICON.globe}Website</a>`);
  return out.length ? `<div class="qtiles" style="--n:${out.length}">${out.join('')}</div>` : '';
}

/** Day, time and reservation on the trip this place is part of. */
function tripSlot(p, trip) {
  const m = trip.places.find((x) => x.id === p.id) || p;
  const booking = (trip.bookings || []).find((b) => b.place_id === p.id);
  const dayLabel = (d) => [dayDate(trip.start_date, d) ? shortDay(dayDate(trip.start_date, d)) : `Day ${d}`, trip.city].filter(Boolean).join(' · ');
  const rows = [];
  if (trip.day_count) {
    rows.push(`<label class="srow" for="slot-day">${ICON.calendar}<span class="k">Day</span>
      <select class="select" id="slot-day" data-act="slotday" data-trip="${trip.id}" data-id="${p.id}">
        <option value="0">Not scheduled</option>
        ${Array.from({ length: trip.day_count }, (_, i) => `<option value="${i + 1}" ${m.day_number === i + 1 ? 'selected' : ''}>${esc(dayLabel(i + 1))}</option>`).join('')}
      </select></label>`);
    rows.push(`<label class="srow" for="slot-tod">${ICON.clock}<span class="k">Time</span>
      <select class="select" id="slot-tod" data-act="slottod" data-trip="${trip.id}" data-id="${p.id}">
        <option value="">Any time</option>
        ${TODS.map((x) => `<option value="${x}" ${m.time_of_day === x ? 'selected' : ''}>${cap(x)}</option>`).join('')}
      </select></label>`);
    rows.push(`<label class="srow" for="slot-time">${ICON.clock}<span class="k">Exact time</span>
      <input class="datefield" type="time" id="slot-time" data-act="slottime" data-trip="${trip.id}" data-id="${p.id}" value="${esc(m.start_time || '')}"></label>`);
  }
  if (MENU_CATS.has(p.category) || p.booking_need || booking) {
    rows.push(booking
      ? `<button class="srow" data-act="bookingmenu" data-id="${booking.id}">${ICON.ticket}<span class="k">Reservation</span><span class="v">${esc(booking.title)}</span></button>`
      : `<button class="srow" data-act="bookedplace" data-id="${p.id}">${ICON.ticket}<span class="k">Reservation</span><span class="v${p.booking_need === 'required' ? ' attn' : ''}">Not booked yet</span></button>`);
  }
  if (!rows.length) return '';
  return `<div class="h2row"><h2 class="h2">On your trip</h2><a class="tbtn" href="#/trip/${trip.id}">${esc(trip.name)}</a></div>
    <div class="pcard list">${rows.join('')}</div>`;
}

/** Today's hours (tap for the week), tips, price and what it's like. */
function goodToKnow(p) {
  const h = p.opening_hours;
  const rows = [];
  if (h && h.text && h.text.length) {
    let today = h.text[0];
    if (h.weekly && h.weekly.length === 7) {
      const ranges = h.weekly[mondayIndex(new Date())] || [];
      today = ranges.length ? `Open today ${ranges.map((x) => `${fmtClock(x.open)} – ${fmtClock(x.close)}`).join(', ')}` : 'Closed today';
    }
    const open = S.allHours && S.allHours[p.id];
    const idx = mondayIndex(new Date());
    rows.push(`<button class="krow" data-act="allhours" data-id="${p.id}" aria-expanded="${!!open}">${ICON.clock}<span class="m"><span class="t">${esc(today)}</span>
      <span class="s">From ${h.source === 'google' ? 'Google' : 'OpenStreetMap'} · hours change, check before you go</span></span><span class="tlink">${open ? 'Less' : 'All hours'}</span></button>
      ${open ? `<div class="hourlist pad">${h.text.map((line, i) => `<span class="${h.weekly && i === idx ? 'today' : ''}">${esc(line)}</span>`).join('')}</div>` : ''}`);
  } else {
    rows.push(`<div class="krow">${ICON.clock}<span class="m"><span class="t">No opening hours found</span><span class="s">Check Google Maps before you go</span></span></div>`);
  }
  p.recommended_items.slice(p.tips ? 0 : 1).forEach((item) => rows.push(`<div class="krow">${ICON.star}<span class="m"><span class="t">Try the ${esc(item)}</span></span></div>`));
  const price = p.price_hint && (p.summary || p.price_hint.length > 5) ? p.price_hint : '';
  if (price || (p.summary && (p.tips || p.recommended_items.length))) {
    rows.push(`<div class="krow">${ICON.tag}<span class="m"><span class="t">${esc([price, p.summary].filter(Boolean).join(' · '))}</span></span></div>`);
  }
  return `<h2 class="h2">Good to know</h2><div class="pcard list">${rows.join('')}</div>`;
}

/** Address, phone, website, then the rating. */
function detailsBlock(p) {
  const rows = [];
  if (p.address) rows.push(`<div class="krow">${ICON.pin}<span class="m"><span class="t">${esc(p.address)}</span></span>
    <button class="ibtn" data-act="copy" data-value="${esc(p.address)}" aria-label="Copy address">${ICON.copy}</button></div>`);
  if (p.phone) rows.push(`<a class="krow" href="tel:${esc(p.phone.replace(/[^\d+]/g, ''))}">${ICON.phone}<span class="m"><span class="t">${esc(p.phone)}</span></span></a>`);
  const site = safeUrl(p.website);
  if (site) {
    let host = site;
    try { host = new URL(site).hostname.replace(/^www\./, ''); } catch { /* as is */ }
    rows.push(`<a class="krow" href="${esc(site)}" target="_blank" rel="noopener">${ICON.globe}<span class="m"><span class="t">${esc(host)}</span></span></a>`);
  }
  if (p.rating) {
    const google = safeUrl(p.maps_url);
    const body = `${ICON.star}<span class="m"><span class="t quiet">${p.rating.toFixed(1)} on Google${p.rating_count ? ` · ${p.rating_count.toLocaleString()} reviews` : ''}</span></span>`;
    rows.push(google ? `<a class="krow" href="${esc(google)}" target="_blank" rel="noopener">${body}</a>` : `<div class="krow">${body}</div>`);
  }
  if (!rows.length) return '';
  return `<h2 class="h2">Details</h2><div class="pcard list">${rows.join('')}</div>`;
}

/** City (automatic), category, lists and trips. */
function organizeBlock(p) {
  if (!S.folders) loadFolders().then(() => render({ quiet: true })).catch(() => {});
  const lists = (S.folders || []).filter((fo) => (p.folder_ids || []).includes(fo.id)).map((fo) => fo.name);
  const trips = realTrips(S.trips || []).filter((t) => (p.trip_ids || []).includes(t.id)).map((t) => t.name);
  const city = isHomePlace(p) ? `Around ${p.city} · automatic` : p.city ? `${p.city} · automatic` : 'Unknown';
  return `<h2 class="h2">Organize</h2><div class="pcard list">
    <div class="orow"><span class="k">City</span><span class="v quiet">${esc(city)}</span></div>
    <label class="orow" for="cat-select"><span class="k">Category</span><select class="select" id="cat-select" data-act="setcat" data-id="${p.id}">
      ${CAT_ORDER.map((c) => `<option value="${c}" ${p.category === c ? 'selected' : ''}>${CATS[c]}</option>`).join('')}</select></label>
    <button class="orow" data-act="placefolders" data-id="${p.id}"><span class="k">Lists</span><span class="v${lists.length ? '' : ' acc'}">${esc(lists.join(', ') || 'Add to a list')}</span></button>
    <button class="orow" data-act="placetrips" data-id="${p.id}"><span class="k">Trips</span><span class="v${trips.length ? '' : ' acc'}">${esc(trips.join(', ') || 'Add to a trip')}</span></button>
  </div>`;
}

// ---------- A trip's route ----------

const ROUTE_MODES = [['train', 'Train'], ['flight', 'Flight'], ['drive', 'Drive'], ['bus', 'Bus'], ['ferry', 'Ferry'], ['other', 'Other']];
function readRoute(st) {
  st.stops = st.stops.map((x, i) => ({
    city: ($(`#rt-city-${i}`) || {}).value ?? x.city,
    days: Math.max(1, Number(($(`#rt-days-${i}`) || {}).value ?? x.days) || 1),
    travel_mode: ($(`#rt-mode-${i}`) || {}).value ?? x.travel_mode,
    travel_minutes: Number(($(`#rt-mins-${i}`) || {}).value ?? x.travel_minutes) || null,
    travel_note: ($(`#rt-note-${i}`) || {}).value ?? x.travel_note,
  }));
}
function routeSheet(t) {
  const route = (t.stops && t.stops.length) ? t.stops : [{ city: t.city, days: Math.max(t.day_count, 1) }];
  const st = { stops: route.map((x) => ({ city: x.city, days: x.days, travel_mode: x.travel_mode || 'train', travel_minutes: x.travel_minutes || null, travel_note: x.travel_note || '' })) };
  openSheet({ type: 'form', title: 'Route', confirm: 'Save', st,
    body: () => `${st.stops.map((x, i) => `<div class="section"><div class="section-h hrow"><span>Stop ${i + 1}</span>
        ${st.stops.length > 1 ? `<button class="linkbtn" data-act="routedel" data-i="${i}">Remove</button>` : ''}</div><div class="group">
        ${i ? `<label class="row authrow" for="rt-mode-${i}"><span class="lbl">Getting there</span><select class="select" id="rt-mode-${i}">${ROUTE_MODES.map(([k, l]) => `<option value="${k}" ${x.travel_mode === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
          <label class="row authrow" for="rt-mins-${i}"><span class="lbl">Minutes</span><input class="field" id="rt-mins-${i}" type="number" min="0" max="3000" inputmode="numeric" value="${x.travel_minutes || ''}" placeholder="e.g. 135"></label>
          <label class="row authrow" for="rt-note-${i}"><span class="lbl">Note</span><input class="field" id="rt-note-${i}" maxlength="120" value="${esc(x.travel_note || '')}" placeholder="e.g. Eurostar from St Pancras"></label>` : ''}
        <label class="row authrow" for="rt-city-${i}"><span class="lbl">City</span><input class="field" id="rt-city-${i}" maxlength="120" value="${esc(x.city)}" placeholder="City"></label>
        <label class="row authrow" for="rt-days-${i}"><span class="lbl">Days</span><input class="field" id="rt-days-${i}" type="number" min="1" max="21" inputmode="numeric" value="${x.days}"></label>
      </div></div>`).join('')}
      <div class="section"><button class="btn tint wide" data-act="routeadd">${ICON.plus}Add a stop</button>
        <div class="section-f">If the trip is longer than its stops, the last stop keeps the extra days.</div></div>`,
    async ok() {
      readRoute(st);
      if (st.stops.some((x) => !x.city.trim())) { toast('Give every stop a city', true); return; }
      const body = { stops: st.stops.map((x, i) => ({ city: x.city.trim(), days: x.days,
        ...(i ? { travel_mode: x.travel_mode, travel_minutes: x.travel_minutes || null, travel_note: (x.travel_note || '').trim() || null } : {}) })) };
      S.sheet.busy = true; renderOverlay();
      try {
        S.trip[t.id] = await api(`/v1/trips/${t.id}/stops`, { method: 'PUT', body });
        fetchedAt.trips = 0; closeSheet(); render();
      } catch (e) { S.sheet.busy = false; renderOverlay(); toast(e.message, true); }
    } });
}

// ---------- Home during a trip ----------

const TOD_MINUTE = { morning: 570, lunch: 750, afternoon: 900, dinner: 1170, evening: 1260 };
function slotMinute(p) {
  if (p.start_time) { const [h, m] = p.start_time.split(':').map(Number); return h * 60 + m; }
  return TOD_MINUTE[p.time_of_day] ?? 720;
}
const minuteClock = (m) => fmtClock(`${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
function walkMins(p, prev) {
  if (S.pos && located(p)) { const d = meters(S.pos.latitude, S.pos.longitude, p.latitude, p.longitude); if (d < 5000) return Math.max(1, Math.round(d / 80)); }
  if (prev && located(prev) && located(p)) { const d = meters(prev.latitude, prev.longitude, p.latitude, p.longitude); if (d < 5000) return Math.max(1, Math.round(d / 80)); }
  return null;
}
function hours(min) { if (min < 60) return `${min} min`; const q = Math.round(min / 15); return `${Math.floor(q / 4)}${['', '¼', '½', '¾'][q % 4]} hr`; }
const temp = (c) => Math.round(USE_MILES ? (c * 9) / 5 + 32 : c);

async function loadTodayWeather(t, places) {
  const key = `${t.id}:${todayIso()}`;
  if (S.weatherToday && S.weatherToday.key === key) return;
  S.weatherToday = { key, w: null };
  const at = S.pos || places.find(located);
  if (!at) return;
  try {
    S.weatherToday.w = await api(`/v1/weather/today?lat=${at.latitude}&lon=${at.longitude}&on=${todayIso()}`);
    render({ quiet: true });
  } catch { /* no weather */ }
}

function travelHomeHtml(t, day) {
  const detail = S.trip[t.id];
  const route = (t.stops && t.stops.length) ? t.stops : [{ city: t.city, start_day: 1, end_day: t.day_count }];
  const si = Math.max(0, route.findIndex((x) => day >= x.start_day && day <= x.end_day));
  const city = route[si].city;
  const list = detail ? stops(detail, day) : [];
  if (detail) loadTodayWeather(t, list.length ? list : detail.places);
  const now = new Date().getHours() * 60 + new Date().getMinutes();
  const next = list.find((p) => !p.visited && slotMinute(p) >= now - 30) || list.find((p) => !p.visited);
  const booked = new Set(((detail && detail.bookings) || []).map((b) => b.place_id).filter(Boolean));
  const hoods = [...new Set(list.map((p) => p.neighborhood).filter(Boolean))];
  const title = (detail && detail.day_titles && detail.day_titles[day - 1] && !/^Day \d+$/.test(detail.day_titles[day - 1])) ? detail.day_titles[day - 1]
    : hoods.length >= 2 ? `${hoods[0]}, then ${hoods[1]}` : hoods[0] || `Day ${day} in ${city}`;
  const w = S.weatherToday && S.weatherToday.w;

  // Dinner gap: nothing after 6 PM, so offer saved food places close to where the day ends.
  let gap = [];
  if (detail && list.length && !list.some((p) => slotMinute(p) >= 1080)) {
    const planned = new Set(detail.places.filter((p) => p.day_number).map((p) => p.id));
    const anchor = [...list].reverse().find(located);
    gap = savedOnly(S.places || []).filter((p) => ['food', 'drinks'].includes(p.category) && !planned.has(p.id) && p.city && cityKey(p.city) === cityKey(city)
      && (!anchor || !located(p) || meters(anchor.latitude, anchor.longitude, p.latitude, p.longitude) < 2500));
  }
  const rows = list.map((p, i) => {
    const m = slotMinute(p);
    const walk = walkMins(p, list[i - 1]);
    const isNext = next && p.id === next.id;
    const leave = isNext && walk != null ? m - walk - now : null;
    const what = p.time_of_day === 'morning' ? 'Breakfast' : p.time_of_day ? cap(p.time_of_day) : CATS[p.category];
    const warn = p.booking_need && !booked.has(p.id) && MENU_CATS.has(p.category)
      ? `<span class="tl-warn">${p.booking_need === 'required' ? 'No table booked yet' : 'No table booked · expect a queue'}</span>` : '';
    return `<a class="tl${isNext ? ' next' : ''}${p.visited ? ' done' : ''}" href="#/place/${p.id}?trip=${t.id}"><span class="tl-time">${esc(minuteClock(m))}</span><i class="tl-dot"></i>
      <span class="tl-body">${isNext ? `<span class="eyebrow">Next${leave != null && leave > 0 && leave <= 90 ? ` · leave in ${leave} min` : ''}</span>` : ''}
        <span class="tl-name serif">${esc(p.name)}</span><span class="tl-meta">${esc([what, walk != null ? `${walk} min walk` : ''].filter(Boolean).join(' · '))}</span>${warn}</span></a>`;
  }).join('');
  const gapRow = gap.length ? `<div class="tl gap"><span class="tl-time">${esc(minuteClock(1170))}</span><i class="tl-dot dashed"></i>
    <span class="tl-body"><span class="tl-name">Dinner isn't planned</span><span class="tl-meta">${plural(gap.length, 'saved place')} ${gap.length === 1 ? 'is' : 'are'} close to where you'll be</span>
    <button class="tlink" data-act="dinnergap" data-trip="${t.id}" data-day="${day}" data-ids="${gap.slice(0, 8).map((p) => p.id).join(',')}">Choose one</button></span></div>` : '';
  const links = next ? mapsLinks(next, detail) : null;
  const todayHtml = `<section class="tcard"><div class="tc-head"><span class="m"><span class="eyebrow">${route.length > 1 ? `Today · stop ${si + 1} of ${route.length}` : 'Today'}</span>
      <span class="t serif">${esc(title)}</span></span>${w ? `<span class="twx"><b>${temp(w.temp_max)}°</b><span>${esc(w.summary)}</span></span>` : ''}</div>
    ${list.length ? `<div class="tline">${rows}${gapRow}</div>` : '<p class="sub">Nothing planned for today yet.</p>'}
    <div class="wbtns"><a class="btn" href="#/today/${t.id}">Open today</a>
      ${links ? `<button class="btn tint" data-act="directionsmenu" data-apple="${esc(links.apple)}" data-google="${esc(links.google)}">${ICON.fwd}Directions</button>` : `<a class="btn tint" href="#/trip/${t.id}">Plan today</a>`}</div></section>`;

  const near = savedOnly(S.places || []).filter((p) => (S.pos && located(p) ? meters(S.pos.latitude, S.pos.longitude, p.latitude, p.longitude) < 3000 : !S.pos && p.city && cityKey(p.city) === cityKey(city)))
    .sort((a, b) => (distanceOf(a) ?? 1e12) - (distanceOf(b) ?? 1e12)).slice(0, 8);
  const nearHtml = near.length ? `<div class="h2row"><h2 class="h2">Near you now</h2><span class="hint">From your ${esc(city)} saves</span></div>
    <div class="hscroll">${near.map((p) => { const st = openStatus(p.opening_hours); const wk = S.pos && located(p) ? Math.max(1, Math.round(meters(S.pos.latitude, S.pos.longitude, p.latitude, p.longitude) / 80)) : null; return `<a class="ocard sm" href="${placeHref(p)}">
      ${p.photos && p.photos[0] ? `<img src="${esc(photoUrl(p.photos[0], 400))}" alt="" loading="lazy" decoding="async">` : `<span class="ph" style="--pc: var(--c-${p.category})">${ICON[p.category] || ICON.pin}</span>`}
      <span class="t">${esc(p.name)}</span><span class="s">${st ? `<span class="${st.state === 'open' ? 'open' : ''}">${st.state === 'open' ? 'Open' : 'Closed'}</span>` : ''}${wk ? `${st ? ' · ' : ''}${wk} min walk` : ''}</span></a>`; }).join('')}</div>` : '';

  let nextHtml = '';
  const ns = route[si + 1];
  if (ns) {
    const saved = savedOnly(S.places || []).filter((p) => p.city && cityKey(p.city) === cityKey(ns.city));
    const inPlan = ((detail && detail.places) || []).filter((p) => p.day_number >= ns.start_day && p.day_number <= ns.end_day).length;
    const date = dayDate(t.start_date, ns.start_day);
    const iso = (() => { const d = dayOf(t.start_date); d.setDate(d.getDate() + ns.start_day - 1); return isoDate(d); })();
    const hotel = ((detail && detail.bookings) || []).some((b) => b.kind === 'hotel' && (b.start_at || '').slice(0, 10) <= iso && iso <= ((b.end_at || b.start_at || '').slice(0, 10)));
    const photo = saved.find((p) => p.photos && p.photos[0]);
    const travel = [ns.travel_note || (ns.travel_mode ? cap(ns.travel_mode) : ''), ns.travel_minutes ? `about ${hours(ns.travel_minutes)}` : ''].filter(Boolean).join(' · ');
    nextHtml = `<h2 class="h2">Next stop</h2><div class="ccard">
      <span class="crow">${photo ? `<img class="sthumb" style="--sz:46px" src="${esc(photoUrl(photo.photos[0], 150))}" alt="">` : `<span class="sthumb ph" style="--sz:46px">${ICON.pin}</span>`}
        <span class="m">${date ? `<span class="eyebrow">${esc(date)}</span>` : ''}<span class="t serif">${esc(ns.city)}</span>${travel ? `<span class="s">${esc(travel)}</span>` : ''}</span></span>
      <span class="cline">${ICON.bookmark}${plural(saved.length, 'saved place')} · ${inPlan} in the plan</span>
      ${hotel ? '' : `<span class="cline attn">${ICON.stay || ICON.bag}No hotel booked yet<a class="tlink" href="#/trip/${t.id}/bookings">Add a stay</a></span>`}</div>`;
  }
  // The route only when it adds something: a London trip called "London" shows London once.
  const routeText = tripStops(t).join(' → ');
  const showRoute = routeText && cityKey(routeText) !== cityKey(t.name);
  return `<div class="tstrip"><b>Day ${day} of ${t.day_count}</b><span class="n">${esc(t.name)}</span>${showRoute ? `<span class="r">${esc(routeText)}</span>` : ''}</div>${todayHtml}${nearHtml}${nextHtml}`;
}

// ---------- Home, Library and cities ----------
// Places file themselves by city: your home city is "Around <city>", every other city is sorted automatically,
// trips are routes of stops, and lists are yours. "Want to go / Been" filters the whole Library.

const cityKey = (c) => normText(c);
const isHomePlace = (p) => !!(S.homeCity && p.city && cityKey(p.city) === cityKey(S.homeCity.city));
const savedOnly = (list) => list.filter((p) => p.saved !== false);
const VISITS = [['all', 'All'], ['want', 'Want to go'], ['been', 'Been']];
function visitOf() { try { return localStorage.getItem('tripit.visit') || 'all'; } catch { return 'all'; } }
const byVisit = (list, v = visitOf()) => (v === 'want' ? list.filter((p) => !p.visited) : v === 'been' ? list.filter((p) => p.visited) : list);
const todayIso = () => isoDate(new Date());

async function ensureHome() {
  if (S.homeCity === undefined) S.homeCity = await api('/v1/home').catch(() => null);
  return S.homeCity;
}

/** Every city with saved places except home, the biggest first. */
function cityGroups(list) {
  const groups = new Map();
  list.filter((p) => p.city && !isHomePlace(p)).forEach((p) => {
    const k = cityKey(p.city);
    if (!groups.has(k)) groups.set(k, { name: p.city, places: [] });
    groups.get(k).places.push(p);
  });
  return [...groups.values()].sort((a, b) => b.places.length - a.places.length || a.name.localeCompare(b.name));
}

const realTrips = (trips) => trips.filter((t) => t.kind !== 'local').sort((a, b) => {
  if (a.start_date && b.start_date) return a.start_date.localeCompare(b.start_date);
  if (a.start_date || b.start_date) return a.start_date ? -1 : 1;
  return (b.created_at || '').localeCompare(a.created_at || '');
});
function tripEnd(t) {
  if (!t.start_date || !t.day_count) return t.start_date;
  const d = dayOf(t.start_date); d.setDate(d.getDate() + t.day_count - 1);
  return isoDate(d);
}
/** "Oct 24–25", "Oct 28 – Nov 2" (or "24–25 Oct" where that's the custom). */
function dateRange(a, b) {
  const f = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' });
  return a.getTime() === b.getTime() || !f.formatRange ? f.format(a) : f.formatRange(a, b);
}
const upcomingTrips = (trips) => realTrips(trips).filter((t) => t.start_date && (tripEnd(t) || t.start_date) >= todayIso());
const tripStops = (t) => ((t.stops && t.stops.length) ? t.stops.map((x) => x.city) : [t.city]).filter(Boolean);
function tripForCity(trips, city) {
  const k = cityKey(city);
  const visits = (t) => tripStops(t).some((c) => cityKey(c) === k);
  return upcomingTrips(trips).find(visits) || realTrips(trips).find(visits) || null;
}

/** "1–6 Nov", "28 Oct – 2 Nov". */
function tripRange(t) {
  if (!t.start_date) return '';
  return dateRange(dayOf(t.start_date), dayOf(tripEnd(t) || t.start_date));
}

/** "In 9 days", "Tomorrow", "Now". */
function tripCountdown(t) {
  if (!t.start_date) return '';
  const days = Math.round((dayOf(t.start_date) - dayOf(todayIso())) / 86400000);
  if (days > 1) return `In ${days} days`;
  if (days === 1) return 'Tomorrow';
  return (tripEnd(t) || t.start_date) >= todayIso() ? 'Now' : '';
}

/** Where a place was filed: "Atlanta · Around Atlanta", "Zürich · Switzerland trip, Day 1", "Paris · on your wishlist". */
function filing(p) {
  let where;
  const trip = realTrips(S.trips || []).find((t) => (p.trip_ids || []).includes(t.id));
  if (isHomePlace(p)) where = `Around ${S.homeCity.city}`;
  else if (trip) {
    where = /trip/i.test(trip.name) ? trip.name : `${trip.name} trip`;
    const member = S.trip[trip.id] && S.trip[trip.id].places.find((x) => x.id === p.id);
    if (member && member.day_number) where += `, Day ${member.day_number}`;
  } else {
    const fo = (S.folders || []).find((f) => (p.folder_ids || []).includes(f.id));
    where = fo ? fo.name : 'on your wishlist';
  }
  return [p.city, where].filter(Boolean).join(' · ');
}

/** Distance from you (when the browser knows) or from the middle of your home city. */
function distanceOf(p) {
  if (p.latitude == null || p.longitude == null) return null;
  if (S.pos) return meters(S.pos.latitude, S.pos.longitude, p.latitude, p.longitude);
  if (S.homeCity && S.homeCity.latitude != null) return meters(S.homeCity.latitude, S.homeCity.longitude, p.latitude, p.longitude);
  return null;
}
const miles = (m) => (m == null ? '' : fmtDistance(m));

const roundBtn = (act, icon, label, extra = '') => `<button class="rbtn" data-act="${act}" ${extra} aria-label="${esc(label)}">${ICON[icon]}</button>`;
function profileBtn() {
  const src = (S.me && (S.me.name || S.me.email)) || '';
  return `<a class="rbtn initial" href="#/profile" aria-label="Profile and settings">${src ? esc(src[0].toUpperCase()) : ICON.person}</a>`;
}
const smallThumb = (p, size = 48) => (p.photos && p.photos[0]
  ? `<img class="sthumb" style="--sz:${size}px" src="${esc(photoUrl(p.photos[0], size * 3))}" alt="" loading="lazy" decoding="async" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'sthumb ph',style:'--sz:${size}px'}))">`
  : `<span class="sthumb ph" style="--sz:${size}px; --pc: var(--c-${p.category})">${ICON[p.category] || ICON.pin}</span>`);
function visitSeg(list) {
  const v = visitOf();
  return `<div class="visitseg" role="group" aria-label="Filter by status">${VISITS.map(([k, label]) => `<button data-act="visit" data-v="${k}" aria-pressed="${v === k}" class="${v === k ? 'on' : ''}">${label} <span>${byVisit(list, k).length}</span></button>`).join('')}</div>`;
}

// This weekend's picks: Saturday brunch or coffee, Sunday dinner, from places you haven't been to yet.
function weekendDays(now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (today.getDay() === 0) return [null, today];
  const sat = new Date(today); sat.setDate(today.getDate() + (6 - today.getDay()));
  const sun = new Date(sat); sun.setDate(sat.getDate() + 1);
  return [sat, sun];
}
function weekendLabel() {
  const [sat, sun] = weekendDays();
  return dateRange(sat || sun, sun);
}
function openAt(p, day, minute) {
  const w = p.opening_hours && p.opening_hours.weekly;
  if (!w || w.length !== 7) return true;
  const toMin = (s) => { const [h, m] = String(s).split(':').map(Number); return h * 60 + m; };
  return (w[mondayIndex(day)] || []).some((r) => { const o = toMin(r.open); let c = toMin(r.close); if (c <= o) c += 1440; return minute >= o && minute < c; });
}
function weekendPicks(places, seed) {
  const eat = new Set(['food', 'cafe', 'dessert', 'drinks']);
  let pool = places.filter((p) => eat.has(p.category));
  if (!pool.length) pool = places;
  if (!pool.length) return [];
  pool = [...pool].sort((a, b) => (b.must_do - a.must_do) || (a.created_at || '').localeCompare(b.created_at || ''));
  const k = ((seed * 2) % pool.length + pool.length) % pool.length;
  pool = pool.slice(k).concat(pool.slice(0, k));
  const [sat, sun] = weekendDays();
  const used = new Set();
  const picks = [];
  const take = (test) => pool.find((p) => !used.has(p.id) && test(p)) || pool.find((p) => !used.has(p.id));
  if (sat) {
    const p = take((x) => ['cafe', 'food', 'dessert'].includes(x.category) && openAt(x, sat, 660));
    if (p) { used.add(p.id); picks.push({ slot: p.category === 'cafe' ? 'Sat · Coffee' : 'Sat · Brunch', p }); }
  }
  const q = take((x) => ['food', 'drinks'].includes(x.category) && openAt(x, sun, 1140));
  if (q) { used.add(q.id); picks.push({ slot: q.category === 'drinks' ? 'Sun · Drinks' : 'Sun · Dinner', p: q }); }
  return picks;
}

function bookMeta(p) {
  const bits = [esc(p.neighborhood || CATS[p.category] || '')];
  const d = distanceOf(p);
  if (d != null) bits.push(esc(miles(d)));
  if (p.booking_need === 'required') bits.push(`<span class="attn">${p.booking_kind === 'tickets' ? 'Tickets needed' : 'Book ahead'}</span>`);
  else if (p.booking_need === 'none') bits.push('walk-in');
  return bits.filter(Boolean).join(' · ');
}

async function homeView() {
  const [places, trips] = await Promise.all([cachedPlaces(), cachedTrips()]);
  cachedFolders();
  await ensureHome();
  if (S.me === undefined) S.me = await api('/v1/me').catch(() => null);
  const saved = savedOnly(places);
  const hour = new Date().getHours();
  const first = S.me && S.me.name ? S.me.name.split(' ')[0] : '';
  const greet = `${hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'}${first ? `, ${esc(first)}` : ''}`;
  const date = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  const onTrip = activeTrip(realTrips(trips));
  const hereCity = onTrip ? (((onTrip.trip.stops || []).find((x) => onTrip.day >= x.start_day && onTrip.day <= x.end_day) || {}).city || onTrip.trip.city) : S.homeCity && S.homeCity.city;
  const head = `<div class="tophead"><span class="eyebrow quiet">${esc([date, hereCity].filter(Boolean).join(' · '))}</span>
      <span class="tbtns">${roundBtn('add', 'plus', 'Save a place')}${profileBtn()}</span></div>
    <h1 class="greet" data-anchor>${greet}</h1>`;
  const jobs = S.jobs.filter((j) => ACTIVE.has(j.status));
  const jobsHtml = jobs.length ? `<div class="section"><div class="group tiles">${jobs.map(jobRow).join('')}</div></div>` : '';

  let weekend;
  if (S.homeCity) {
    const picks = weekendPicks(saved.filter((p) => isHomePlace(p) && !p.visited), S.shuffle || 0);
    weekend = `<section class="wcard"><span class="eyebrow">This weekend · ${esc(weekendLabel())}</span>
      <h2 class="h2 big">Your ${esc(S.homeCity.city)} weekend</h2>
      ${picks.length ? `<p class="sub">Picked from places you've saved but haven't been to yet</p>
        <ul class="picks">${picks.map(({ slot, p }) => `<li><a href="${placeHref(p)}">${smallThumb(p, 56)}<span class="m">
          <span class="eyebrow quiet">${esc(slot)}</span><span class="t">${esc(p.name)}</span><span class="s">${bookMeta(p)}</span></span></a></li>`).join('')}</ul>
        <div class="wbtns"><button class="btn" data-act="planweekend" data-ids="${picks.map((x) => x.p.id).join(',')}">Plan the weekend</button>
          <button class="btn tint" data-act="shuffle">${ICON.shuffle}Shuffle</button></div>`
        : `<p class="sub">Save places around ${esc(S.homeCity.city)} and we'll pick a couple for the weekend from the ones you haven't been to.</p>`}
    </section>`;
  } else {
    weekend = `<section class="wcard"><span class="eyebrow">Your city</span><h2 class="h2 big">Where's home?</h2>
      <p class="sub">Set your home city and places you save there are kept as Around your city, with weekend picks and what's open now.</p>
      <div class="wbtns"><button class="btn" data-act="homecity">Set home city</button></div></section>`;
  }

  const open = saved.filter((p) => {
    const st = openStatus(p.opening_hours);
    if (!st || st.state !== 'open') return false;
    const d = S.pos ? distanceOf(p) : null;
    return d != null ? d < 30000 : isHomePlace(p);
  }).sort((a, b) => (distanceOf(a) ?? 1e12) - (distanceOf(b) ?? 1e12)).slice(0, 8);
  const openHtml = open.length ? `<h2 class="h2">Open now from your saves</h2>
    <div class="hscroll">${open.map((p) => { const st = openStatus(p.opening_hours); const d = distanceOf(p); return `<a class="ocard" href="${placeHref(p)}">
      ${p.photos && p.photos[0] ? `<img src="${esc(photoUrl(p.photos[0], 500))}" alt="" loading="lazy" decoding="async">` : `<span class="ph" style="--pc: var(--c-${p.category})">${ICON[p.category] || ICON.pin}</span>`}
      <span class="t">${esc(p.name)}</span><span class="s"><span class="open">${esc(st.label.replace(/^Open until/, 'Until'))}</span>${d != null ? ` · ${esc(miles(d))}` : ''}</span></a>`; }).join('')}</div>` : '';

  const next = upcomingTrips(trips)[0];
  let coming = '';
  if (next) {
    const detail = S.trip[next.id];
    if (!detail) loadTrip(next.id).then(() => render({ quiet: true })).catch(() => {});
    const booked = new Set(((detail && detail.bookings) || []).map((b) => b.place_id).filter(Boolean));
    const need = detail && detail.places.find((p) => p.booking_need === 'required' && !booked.has(p.id) && !p.suggested);
    const cover = next.cover_photo ? `<img class="sthumb" style="--sz:64px" src="${esc(photoUrl(next.cover_photo, 200))}" alt="" loading="lazy">` : `<span class="sthumb ph" style="--sz:64px">${ICON.plane}</span>`;
    coming = `<h2 class="h2">Coming up</h2><a class="ccard" href="#/trip/${next.id}">
      <span class="crow">${cover}<span class="m">${tripCountdown(next) ? `<span class="eyebrow">${esc(tripCountdown(next))}</span>` : ''}
        <span class="t serif">${esc(next.name)}</span><span class="s">${esc([tripStops(next).join(' → '), tripRange(next)].filter(Boolean).join(' · '))}</span></span></span>
      ${need ? `<span class="cneed">${ICON.bell}<span class="t">${esc(need.name)} still needs ${need.booking_kind === 'tickets' ? 'tickets' : 'a table'}</span><span class="go">Book</span></span>` : ''}</a>`;
  }

  const weekAgo = isoDate(new Date(Date.now() - 7 * 86400000));
  const sorted = [...saved].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
  const thisWeek = sorted.filter((p) => (p.created_at || '') >= weekAgo);
  const recent = (thisWeek.length ? thisWeek : sorted).slice(0, 5);
  const recentHtml = recent.length ? `<h2 class="h2">${thisWeek.length ? 'Saved this week' : 'Recently saved'}</h2>
    <ul class="rows">${recent.map((p) => `<li><a href="${placeHref(p)}">${smallThumb(p)}<span class="m"><span class="t">${esc(p.name)}</span><span class="s">${esc(filing(p))}</span></span></a></li>`).join('')}</ul>`
    : (S.homeCity ? emptyState('accent', 'bookmark', 'Nothing saved yet', 'Share a TikTok or Instagram Reel to The Travel Edit, paste a link, or search for a place.',
      `<button class="btn" data-act="add">${ICON.plus}Save a place</button>`) : '');

  // On a trip today: today at this stop, what's near, and the next stop instead of the at-home sections.
  const active = activeTrip(realTrips(trips));
  if (active) {
    if (!S.trip[active.trip.id]) loadTrip(active.trip.id).then(() => render({ quiet: true })).catch(() => {});
    return `<div class="page">${head}${jobsHtml}${travelHomeHtml(active.trip, active.day)}${recentHtml}</div>`;
  }
  return `<div class="page">${head}${jobsHtml}${weekend}${openHtml}${coming}${recentHtml}${tasteInvite()}</div>`;
}

function libMain(places, trips, folders) {
  const q = normText(S.libq || '');
  const shown = byVisit(places);
  if (q) {
    const hits = shown.filter((p) => normText(`${p.name} ${p.neighborhood || ''} ${p.city || ''} ${p.venue || ''}`).includes(q));
    const cities = cityGroups(shown).filter((c) => normText(c.name).includes(q));
    const lists = folders.filter((f) => normText(f.name).includes(q));
    if (!hits.length && !cities.length && !lists.length) return emptyState('gray', 'search', 'Nothing matches', `Nothing in your Library matches “${esc(S.libq)}”.`);
    return `${cities.length || lists.length ? `<h2 class="h2 small">Cities and lists</h2><ul class="rows">
        ${cities.map((c) => listRow(`#/city/${encodeURIComponent(c.name)}`, c.name, plural(c.places.length, 'place'), c.places.find((p) => p.photos && p.photos[0]))).join('')}
        ${lists.map((f) => listRow(`#/folder/${f.id}`, f.name, plural(f.place_count, 'place'), null, f.covers[0])).join('')}</ul>` : ''}
      ${hits.length ? `<h2 class="h2 small">${plural(hits.length, 'place')}</h2><div class="section flush"><div class="group thumbs">${hits.map((p) => placeRow(p, { home: true })).join('')}</div></div>` : ''}`;
  }
  let around = '';
  if (S.homeCity) {
    const mine = shown.filter(isHomePlace);
    const openN = mine.filter((p) => { const st = openStatus(p.opening_hours); return st && st.state === 'open'; }).length;
    around = `<a class="acard" href="#/city/${encodeURIComponent(S.homeCity.city)}">
      <span class="arow"><span class="m"><span class="eyebrow">${ICON.home}Your city</span><span class="t serif">Around ${esc(S.homeCity.city)}</span>
        <span class="s">${plural(mine.length, 'place')}${openN ? ` · <span class="open">${openN} open now</span>` : ''}</span></span><span class="chevc">${ICON.chev}</span></span>
      ${mine.length ? photoStrip(mine) : ''}</a>`;
  }
  const all = realTrips(trips);
  const tripsHtml = `<div class="h2row"><h2 class="h2">Trips</h2><button class="tbtn" data-act="newtrip">${ICON.plus}New trip</button></div>
    ${all.length ? all.map((t, i) => (i === 0 ? routeCard(t) : tripRowHtml(t))).join('') : '<p class="sub">Plan a trip from a city you’ve saved places in, or start one from scratch.</p>'}`;
  const groups = cityGroups(shown);
  const visible = S.allCities ? groups : groups.slice(0, 4);
  const citiesHtml = groups.length ? `<div class="h2row"><h2 class="h2">Cities</h2>${groups.length > 4
    ? `<button class="tbtn" data-act="allcities" aria-expanded="${!!S.allCities}">${S.allCities ? `Show fewer${ICON.up}` : `See all ${groups.length}${ICON.down}`}</button>`
    : '<span class="hint">Sorted for you automatically</span>'}</div>
    <div class="citygrid">${visible.map((c) => cityTile(c, tripForCity(trips, c.name))).join('')}</div>` : '';
  const listsHtml = `<div class="h2row"><h2 class="h2">Your lists</h2><button class="tbtn" data-act="newfolder">${ICON.plus}New list</button></div>
    ${folders.length ? `<ul class="rows">${folders.map((f) => listRow(`#/folder/${f.id}`, f.name, listSub(f, places), null, f.covers[0])).join('')}</ul>`
      : '<p class="sub">Make lists for anything: date night, early risers, best croissants. A place can be on several.</p>'}`;
  return `${around}${tripsHtml}${citiesHtml}${listsHtml}`;
}

function photoStrip(list) {
  const withPhotos = list.filter((p) => p.photos && p.photos[0]);
  const src = withPhotos.length ? withPhotos : list;
  const n = list.length > 4 ? 3 : 4;
  return `<span class="pstrip">${src.slice(0, n).map((p) => (p.photos && p.photos[0] ? `<img src="${esc(photoUrl(p.photos[0], 240))}" alt="" loading="lazy" decoding="async">` : `<span class="ph" style="--pc: var(--c-${p.category})">${ICON[p.category] || ICON.pin}</span>`)).join('')}${list.length > 4 ? `<span class="more">+${list.length - 3}</span>` : ''}</span>`;
}
function routeStrip(stops) { return `<span class="route">${stops.map((s, i) => `${i ? '<i></i>' : ''}<span>${esc(s)}</span>`).join('')}</span>`; }
function routeCard(t) {
  return `<a class="rcard" href="#/trip/${t.id}">${t.cover_photo ? `<img src="${esc(photoUrl(t.cover_photo, 900))}" alt="" loading="lazy" decoding="async">` : `<span class="ph">${ICON.plane}</span>`}
    <span class="b"><span class="tr"><span class="t serif">${esc(t.name)}</span>${tripCountdown(t) ? `<span class="cd">${esc(tripCountdown(t))}</span>` : ''}</span>
      <span class="s">${esc([tripRange(t) || 'No dates yet', plural(t.place_count, 'place')].join(' · '))}</span>${routeStrip(tripStops(t))}</span></a>`;
}
function tripRowHtml(t) {
  const cover = t.cover_photo ? `<img class="sthumb" style="--sz:56px" src="${esc(photoUrl(t.cover_photo, 180))}" alt="" loading="lazy">` : `<span class="sthumb ph" style="--sz:56px">${ICON.plane}</span>`;
  return `<a class="trow" href="#/trip/${t.id}">${cover}<span class="m"><span class="t serif">${esc(t.name)}</span>
    <span class="s">${esc([tripRange(t), tripStops(t).join(' → ')].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</a>`;
}
function cityTile(c, trip) {
  const photos = c.places.filter((p) => p.photos && p.photos[0]).slice(0, 2);
  const when = trip ? (trip.start_date ? `<span class="acc">Trip ${esc(dayOf(trip.start_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }))}</span>` : '<span class="acc">On a trip</span>') : 'No trip yet';
  return `<a class="ctile" href="#/city/${encodeURIComponent(c.name)}"><span class="cimgs">${photos.length ? photos.map((p) => `<img src="${esc(photoUrl(p.photos[0], 300))}" alt="" loading="lazy" decoding="async">`).join('') : `<span class="ph">${ICON.pin}</span>`}</span>
    <span class="t serif">${esc(c.name)}</span><span class="s">${plural(c.places.length, 'place')} · ${when}</span></a>`;
}
function listRow(href, title, sub, place = null, photo = null) {
  const ph = photo || (place && place.photos && place.photos[0]);
  return `<li><a href="${href}">${ph ? `<img class="sthumb" style="--sz:48px" src="${esc(photoUrl(ph, 150))}" alt="" loading="lazy">` : `<span class="sthumb ph" style="--sz:48px">${ICON.folder}</span>`}
    <span class="m"><span class="t">${esc(title)}</span><span class="s">${esc(sub)}</span></span>${ICON.chev}</a></li>`;
}
function listSub(f, places) {
  const cities = [...new Set(places.filter((p) => (p.folder_ids || []).includes(f.id) && p.city).map((p) => p.city))].sort();
  const where = !cities.length ? '' : cities.length <= 2 ? cities.join(', ') : `${cities.length} cities`;
  return [plural(f.place_count, 'place'), where].filter(Boolean).join(' · ');
}

async function libraryView(r) {
  const [places, trips, folders] = await Promise.all([cachedPlaces(), cachedTrips(), cachedFolders()]);
  await ensureHome();
  if (S.me === undefined) S.me = await api('/v1/me').catch(() => null);
  if (r.tab === 'saved') { // everything in one list (and the places from one Reel, from a notification)
    return `${navbar('All places', { back: '#/library', backLabel: 'Library' })}<h1 class="largetitle" data-anchor>All places</h1>${await savedView(r)}`;
  }
  const saved = savedOnly(places);
  const jobs = S.jobs.filter((j) => ACTIVE.has(j.status));
  const head = `<div class="tophead end"><span class="tbtns">${roundBtn('add', 'plus', 'Save a place')}${profileBtn()}</span></div>
    <div class="libtitle"><h1 data-anchor>Library</h1><a class="mapbtn" href="#/map">${ICON.map}Map</a></div>
    <label class="lsearch">${ICON.search}<span class="vh">Search places, cities and lists</span>
      <input type="search" data-act="libsearch" value="${esc(S.libq || '')}" placeholder="Places, cities, lists" autocomplete="off" enterkeyhint="search"></label>
    ${visitSeg(saved)}`;
  const empty = !saved.length && !realTrips(trips).length;
  const body = empty ? emptyState('accent', 'bookmark', 'Nothing saved yet',
    'Share a TikTok or Instagram Reel to The Travel Edit, paste a link, or search for a place. Places file themselves by city.',
    `<button class="btn" data-act="add">${ICON.plus}Save a place</button><a class="linkbtn" href="#/profile">Set up the share button</a>`)
    : `${jobs.length ? `<div class="section flush"><div class="group tiles">${jobs.map(jobRow).join('')}</div></div>` : ''}<div id="libmain">${libMain(saved, trips, folders)}</div>`;
  return `<div class="page">${head}${body}</div>`;
}

/** Redraws the Library under the search box while typing. */
function redrawLibMain() {
  const box = document.getElementById('libmain');
  if (!box || !S.places) return;
  box.innerHTML = libMain(savedOnly(S.places), S.trips || [], S.folders || []);
  hydrateIcons(box);
}

async function cityView(r) {
  const [places, trips] = await Promise.all([cachedPlaces(), cachedTrips()]);
  cachedFolders();
  await ensureHome();
  const name = r.id;
  const home = !!(S.homeCity && cityKey(S.homeCity.city) === cityKey(name));
  const all = savedOnly(places).filter((p) => p.city && cityKey(p.city) === cityKey(name));
  const trip = home ? null : tripForCity(trips, name);
  const title = home ? `Around ${name}` : name;
  const openN = all.filter((p) => { const st = openStatus(p.opening_hours); return st && st.state === 'open'; }).length;
  const sub = [plural(all.length, 'place'), home ? (openN ? `${openN} open now` : '') : trip ? (tripRange(trip) ? `trip ${tripRange(trip)}` : `on ${trip.name}`) : 'your wishlist, no trip yet'].filter(Boolean).join(' · ');
  const scope = `city:${cityKey(name)}`;
  const shown = byVisit(all);
  const head = `${navbar(title, { back: '#/library', backLabel: 'Library', right: `<a class="gbtn" href="#/map" aria-label="Map">${ICON.map}</a>` })}
    ${home ? '<div class="eyebrow pad">Your city</div>' : ''}<h1 class="largetitle" data-anchor>${esc(title)}</h1>
    <div class="subtitle"><span>${esc(sub)}</span></div>
    <div class="page tight">${trip ? `<span class="eyebrow quiet planned">Planned trip</span>${tripRowHtml(trip)}` : (!home && all.length ? `<button class="btn wide" data-act="citytrip" data-city="${esc(name)}">${ICON.plane}Plan a trip to ${esc(name)}</button>` : '')}
    ${visitSeg(all)}</div>`;
  if (!all.length) return head + emptyState('gray', 'pin', 'Nothing here yet', `Places you save in ${esc(name)} land here automatically.`);
  return `${head}${libControls(scope, shown)}<div id="libbody" data-scope="${esc(scope)}">${libList(scope, shown)}</div>${selBar()}`;
}

const VIEWS = {
  async folder(r) { return folderView(r); },

  async calendar() { return calendarView(); },

  async bookings(r) { return bookingsTab(r); },

  async discover() { return discoverView(); },

  async home() { return homeView(); },

  async trips(r) { return libraryView(r); },

  async city(r) { return cityView(r); },

  async trip(r) {
    const trip = await cachedTrip(r.id);
    if (trip.kind !== 'local' && trip.places.some((p) => !p.booking_checked_at)) ensureNeeds([trip.id]);
    const local = trip.kind === 'local';
    const modes = local ? ['places', 'map'] : ['places', 'itinerary', 'map'];
    const mode = modes.includes(r.mode) ? r.mode : 'places';
    const right = `<span class="gcluster">${r.mode === 'bookings' ? `<button class="gbtn" data-act="addbooking" data-id="${trip.id}" aria-label="Add a booking">${ICON.plus}</button>` : ''}<button class="gbtn" data-act="sharetrip" data-id="${trip.id}" aria-label="Share trip">${ICON.share}</button>
      <button class="gbtn" data-act="tripmenu" data-id="${trip.id}" aria-label="More">${ICON.more}</button></span>`;
    const seg = segControl(`seg:${trip.id}`, modes.map((m) => ({
      on: m === mode,
      html: `<a href="#/trip/${trip.id}${m === 'places' ? '' : `/${m}`}" class="${m === mode ? 'on' : ''}" ${m === mode ? 'aria-current="page"' : ''}>${{ itinerary: 'Plan' }[m] || cap(m)}</a>`,
    })));
    const meta = [local ? 'Near home' : trip.country, plural(trip.places.length, 'place'), trip.day_count ? `${trip.day_count}-day plan` : ''].filter(Boolean).join(' · ');
    const cats = [...new Set(trip.places.map((p) => p.category))].sort((a, b) => CAT_ORDER.indexOf(a) - CAT_ORDER.indexOf(b));
    const head = `${navbar(trip.name, { back: '#/library', backLabel: 'Library', right })}
      <h1 class="largetitle" data-anchor>${esc(trip.name)}</h1>
      <div class="subtitle"><span>${esc(meta)}</span><span class="tiles-inline" aria-hidden="true">${cats.slice(0, 6).map((c) => catTile(c, 'sm')).join('')}</span>
        ${trip.share_token ? `<button class="chip-shared" data-act="sharetrip" data-id="${trip.id}">${ICON.link}Shared</button>` : ''}</div>${seg}`;

    if (mode === 'places' && local) return head + placesList(trip);
    if (mode === 'places') {
      if (S.packing[trip.id] === undefined) { // for the packing card's progress
        S.packing[trip.id] = null;
        api(`/v1/trips/${trip.id}/packing`).then((list) => { S.packing[trip.id] = list; render({ quiet: true }); }).catch(() => { delete S.packing[trip.id]; });
      }
      loadEvents(trip.id);
      return head + bookingsCard(trip) + packingCard(trip) + eventsCard(trip) + editsSection(trip) + placesList(trip);
    }
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

  async packing(r) {
    const trip = await cachedTrip(r.id);
    const body = await packingView(trip);
    return `${navbar('Packing', { back: `#/trip/${trip.id}`, backLabel: trip.name })}<h1 class="largetitle" data-anchor>Packing</h1>
      <div class="subtitle"><span>${esc([trip.name, trip.start_date ? dayDate(trip.start_date, 1) : '', trip.day_count ? plural(trip.day_count, 'day') : ''].filter(Boolean).join(' · '))}</span></div>${body}`;
  },

  async events(r) {
    const trip = await cachedTrip(r.id);
    return `${navbar('What’s on', { back: `#/trip/${trip.id}`, backLabel: trip.name })}<h1 class="largetitle" data-anchor>What’s on</h1>
      <div class="subtitle"><span>${esc([trip.name, trip.start_date ? dayDate(trip.start_date, 1) : ''].filter(Boolean).join(' · '))}</span></div>${eventsView(trip)}`;
  },

  async today(r) {
    const trip = await cachedTrip(r.id);
    const active = activeTrip([trip]);
    const head = (title) => navbar(title, { back: '#/library', backLabel: 'Library',
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
        ? `<div class="row"><a class="rowlink" href="${placeHref(p)}">${inner}</a><button class="linkbtn" data-act="undone" data-id="${p.id}" aria-label="Mark ${esc(p.name)} not visited">Undo</button></div>`
        : `<a class="row" href="${placeHref(p)}">${inner}${ICON.chev}</a>`;
    };
    const bag = await todayBag(trip, day);
    const html = `${head(title)}<h1 class="largetitle" data-anchor>${title}</h1>
      <div class="subtitle"><span>${esc([dayDate(trip.start_date, day), trip.name, trip.day_titles[day - 1]].filter(Boolean).join(' · '))}</span></div>
      ${pills}
      ${dayBookings(trip, day).length ? `<div class="section"><div class="section-h">Booked today</div>${bookingRows(dayBookings(trip, day))}</div>` : ''}
      ${bag}
      ${tonightEvents(trip, day)}
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
    // Opened from a trip (?trip=…) it shows that trip's day and time; from Saved or a folder, just the place.
    const ctxId = r.params.get('trip');
    const inTrip = ctxId ? await Promise.resolve().then(() => cachedTrip(ctxId)).catch(() => null) : null;
    let p = inTrip ? tripPlace(inTrip, r.id) : null;
    let reels;
    if (p) {
      const reelIds = p.reel_ids && p.reel_ids.length ? p.reel_ids : [p.reel_id].filter(Boolean);
      reels = reelIds.map((id) => inTrip.reels.find((x) => x.id === id)).filter(Boolean);
    } else {
      const d = await cachedPlaceDetail(r.id);
      p = d.place; reels = d.reels;
    }
    const trip = p.trip_id && inTrip ? inTrip : { id: null, name: 'Library', city: p.city, bookings: [], day_count: 0, places: [p], reels };
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

    const hasMenu = MENU_CATS.has(p.category);
    if (hasMenu && p.website && !p.reserve_checked_at && !S.reserveTried[p.id]) {
      S.reserveTried[p.id] = true; // look for the restaurant's Resy or OpenTable page once, in the background
      api(`/v1/places/${p.id}/reserve-link`, { method: 'POST' }).then((fresh) => {
        trip.places = trip.places.map((x) => (x.id === fresh.id ? fresh : x));
        if (S.places) S.places = S.places.map((x) => (x.id === fresh.id ? fresh : x));
        render({ quiet: true });
      }).catch(() => {});
    }
    // The trip this place is on (opened from the Library it's the first one), for its day, time and reservation.
    let slotTrip = trip.id ? trip : null;
    if (!slotTrip) {
      const member = realTrips(S.trips || []).find((t) => (p.trip_ids || []).includes(t.id));
      if (member) {
        slotTrip = S.trip[member.id] || null;
        if (!slotTrip) loadTrip(member.id).then(() => render({ quiet: true })).catch(() => {});
      }
    }
    const back = trip.id ? `#/trip/${trip.id}` : '#/library';
    const right = `<span class="gcluster"><button class="gbtn" data-act="shareplace" data-id="${p.id}" aria-label="Share">${ICON.share}</button>
      <button class="gbtn" data-act="placemore" data-id="${p.id}" data-trip="${slotTrip ? slotTrip.id : ''}" aria-label="More: star, lists, wrong pin, remove from trip, delete">${ICON.more}</button></span>`;
    if (r.mode === 'menu' && hasMenu) {
      return { html: `${navbar(`${p.name} menu`, { back: placeHref(p), backLabel: p.name })}<h1 class="largetitle" data-anchor>Menu</h1>
        <div class="subtitle"><span>${esc(p.name)}</span></div>${await menuSection(p)}` };
    }
    const after = () => { if (isLocated) renderMap($('#mini-map'), [p], { interactive: false, zoom: 15 }); };
    const html = `${navbar(p.name, { back, backLabel: trip.id ? trip.name : 'Library', right })}
      ${hero}
      <div class="pg">
        <span class="eyebrow quiet">${esc([CATS[p.category], p.must_do ? 'Starred' : ''].filter(Boolean).join(' · '))}</span>
        <h1 class="pname" data-anchor>${esc(p.name)}${isNew(p)}</h1>
        ${p.neighborhood || p.city ? `<span class="ploc">${esc([p.neighborhood, p.city].filter(Boolean).join(', '))}</span>` : ''}
        ${statusLine(p, st)}
        ${p.resolved_name ? `<span class="pnote">On maps as ${esc(p.resolved_name)}</span>` : ''}
        ${p.confidence === 'low' ? '<span class="pnote attn">The name was hard to make out in the Reel; double-check it.</span>' : ''}
        ${p.suggested && trip.id ? `<div class="pcard sugg">${ICON.sparkle}<span class="m"><span class="t">Suggested for this trip</span>
          <span class="s">${esc(p.suggestion_note || 'Added by AI to fill a quiet day')}</span></span>
          <button class="tbtn" data-act="keepsugg" data-trip="${trip.id}" data-id="${p.id}">Keep</button></div>` : ''}
        <button class="beenbtn${p.visited ? ' on' : ''}" data-act="pvisit" data-id="${p.id}" data-v="${p.visited ? 0 : 1}" aria-pressed="${!!p.visited}">
          <span class="ck">${ICON.check}</span>Been here</button>
        ${whySaved(p, reels)}
        ${mainAction(p, slotTrip)}
        ${quietActions(p, slotTrip)}
        ${eventWhen(p)}
        ${slotTrip && slotTrip.kind !== 'local' ? tripSlot(p, slotTrip) : ''}
        ${isLocated ? '' : `<h2 class="h2 small">Not on the map yet</h2><div class="group">
          <form class="row" data-form="locate" data-id="${p.id}"><span class="inline-form">
            <input class="field" id="locate-q" name="q" placeholder="Search, e.g. ${esc(p.name)}, ${esc(p.city)}" value="${esc(`${p.name}, ${p.neighborhood ? `${p.neighborhood}, ` : ''}${p.city}`)}" autocomplete="off">
            <button class="btn small" type="submit">Find</button></span></form></div>`}
        ${goodToKnow(p)}
        ${detailsBlock(p)}
        ${gettingThere(p)}
        ${organizeBlock(p)}
      </div>`;
    return { html, after };
  },

  async edit(r) {
    const trip = await cachedTrip(r.id);
    const te = S.edits[r.id] || await loadEdits(r.id);
    const e = te.edits.find((x) => x.id === r.editId);
    if (!e) throw new ApiError('This edit was refreshed. Open the trip to see the latest ones.', 404);
    const onTrip = new Set(trip.places.map((p) => p.id));
    const saveEdit = e.folder_id
      ? `<a class="btn tint small" href="#/folder/${e.folder_id}">${ICON.done}Saved to Library</a>`
      : `<button class="btn small" data-act="bookmarkedit" data-trip="${trip.id}" data-id="${e.id}">${ICON.bookmark}Save this edit</button>`;
    const html = `${navbar(e.title, { back: `#/trip/${trip.id}`, backLabel: trip.name })}
      <header class="edithead">${e.cover_photo ? `<div class="edithero"><img src="${esc(photoUrl(e.cover_photo, 1200))}" alt="" decoding="async" onerror="this.parentElement.remove()"></div>` : ''}
        <div class="eyebrow">The Edit · ${esc(trip.name)}</div>
        <h1 class="edittitle" data-anchor>${esc(e.title)}</h1>
        <p class="dek">${esc(e.dek)}</p>
        <div class="byline">${te.curated_by === 'claude+web' ? 'Your saves and the best of the press' : te.curated_by === 'claude' ? 'Curated for you' : 'From your saves'}
          · ${plural(e.entries.length, 'place')}${e.new_count ? ` · ${e.new_count} new to you` : ''}</div>
        <div class="editsave">${saveEdit}<span class="s">${e.folder_id ? 'Kept as a folder, even after the edits refresh.' : 'Edits refresh daily. Save this one to keep it as a folder.'}</span></div></header>
      <ol class="editlist">${e.entries.map((it, i) => {
        const href = it.saved ? `#/place/${it.place_id}${onTrip.has(it.place_id) ? `?trip=${trip.id}` : ''}` : `#/editplace/${trip.id}/${e.id}/${it.id}`;
        const p = it.saved ? (trip.places.find((x) => x.id === it.place_id) || {}) : {};
        const st = p.opening_hours ? openStatus(p.opening_hours) : null;
        const src = it.source ? `<span class="ee-source">${it.saved && !it.source.url ? '' : 'via '}${safeUrl(it.source.url)
          ? `<a href="${esc(it.source.url)}" target="_blank" rel="noopener" data-act="link">${esc(it.source.name)}</a>` : esc(it.source.name)}</span>` : '';
        const action = it.saved
          ? '<span class="ee-saved">' + ICON.done + 'In your library</span>'
          : `<button class="btn tint small" data-act="saveeditentry" data-trip="${trip.id}" data-edit="${e.id}" data-id="${it.id}">${ICON.bookmark}Save</button>`;
        const body = `${it.photo ? `<span class="ee-photo"><img src="${esc(photoUrl(it.photo, 900))}" alt="" loading="lazy" decoding="async" onerror="this.parentElement.remove()"></span>` : ''}
          <span class="ee-body"><span class="ee-num">${String(i + 1).padStart(2, '0')}</span>
            <span class="eyebrow">${esc([CATS[it.category], it.neighborhood].filter(Boolean).join(' · '))}</span>
            <span class="ee-name">${esc(it.name)}${p.must_do ? starMark(p) : ''}</span>
            ${it.note ? `<span class="ee-note">${esc(it.note)}</span>` : ''}
            ${it.rating && !it.saved ? `<span class="s">★ ${it.rating.toFixed(1)}${it.rating_count ? ` · ${fmtCount(it.rating_count)} reviews` : ''}</span>` : ''}
            ${st ? `<span class="s hours-${st.state}">${esc(st.label)}</span>` : ''}</span>`;
        return `<li class="${it.saved ? '' : 'isnew'}">${href ? `<a class="editentry" href="${href}">${body}</a>` : `<div class="editentry">${body}</div>`}
          <div class="ee-foot">${src}${!it.saved && safeUrl(it.maps_url) ? `<a class="linkbtn" href="${esc(it.maps_url)}" target="_blank" rel="noopener">Map</a>` : ''}${action}</div></li>`;
      }).join('')}</ol>
      <div class="section"><a class="btn tint wide" href="#/trip/${trip.id}/map">${ICON.map}See your trip on the map</a></div>`;
    return html;
  },

  /** A place from an edit that isn't saved yet (a publication's pick): what we know, where it's from, and Save. */
  async editplace(r) {
    const trip = await cachedTrip(r.id);
    const te = S.edits[r.id] || await loadEdits(r.id);
    const e = te.edits.find((x) => x.id === r.editId);
    const it = e && e.entries.find((x) => x.id === r.entryId);
    if (!it) throw new ApiError('This edit was refreshed. Open the trip to see the latest ones.', 404);
    if (it.saved && it.place_id) { location.replace(`#/place/${it.place_id}`); return ''; }
    const hasCoords = it.latitude != null && it.longitude != null;
    const where = [it.name, it.neighborhood, it.city || trip.city].filter(Boolean).join(', ');
    const apple = hasCoords ? `https://maps.apple.com/?daddr=${it.latitude},${it.longitude}` : `https://maps.apple.com/?daddr=${encodeURIComponent(where)}`;
    const google = `https://www.google.com/maps/dir/?api=1&destination=${hasCoords ? `${it.latitude},${it.longitude}` : encodeURIComponent(where)}`;
    const src = it.source;
    return `${navbar(it.name, { back: `#/edit/${trip.id}/${e.id}`, backLabel: e.title })}
      ${it.photo ? `<div class="hero"><div class="gallery"><div class="gimg"><img src="${esc(photoUrl(it.photo, 1000))}" alt="${esc(it.name)}" decoding="async" onerror="this.closest('.hero').remove()"></div></div></div>` : ''}
      <div class="ph" style="${cvar(it.category)}">
        <span class="cat">${catTile(it.category, 'sm')}${CATS[it.category] || 'Place'}</span>
        <h1 data-anchor>${esc(it.name)}</h1>
        <span class="loc">${esc([it.neighborhood, it.city || trip.city].filter(Boolean).join(' · '))}</span>
        ${it.rating ? `<span class="s">★ ${it.rating.toFixed(1)}${it.rating_count ? ` · ${fmtCount(it.rating_count)} reviews` : ''}</span>` : ''}
      </div>
      <div class="section"><button class="btn wide" data-act="saveeditentry" data-trip="${trip.id}" data-edit="${e.id}" data-id="${it.id}">${ICON.bookmark}Save to your library</button></div>
      ${it.note ? `<div class="section"><div class="section-h">Why it’s in ${esc(e.title)}</div><div class="group"><div class="notecard">${esc(it.note)}</div></div></div>` : ''}
      ${src ? `<div class="section"><div class="section-h">Recommended by</div><div class="group tiles">
        ${safeUrl(src.url) ? `<a class="row" href="${esc(src.url)}" target="_blank" rel="noopener">` : '<div class="row">'}${tile('indigo', 'book')}
        <span class="main"><span class="t">${esc(src.name)}</span>${src.title ? `<span class="s">${esc(src.title)}</span>` : ''}</span>${safeUrl(src.url) ? `${ICON.chev}</a>` : '</div>'}</div></div>` : ''}
      <div class="section"><div class="section-h">Getting there</div><div class="group tiles">
        <a class="row" href="${esc(apple)}" target="_blank" rel="noopener">${tile('green', 'map')}<span class="main"><span class="t">Directions in Apple Maps</span></span>${ICON.chev}</a>
        <a class="row" href="${esc(google)}" target="_blank" rel="noopener">${tile('blue', 'globe')}<span class="main"><span class="t">Directions in Google Maps</span></span>${ICON.chev}</a>
        ${safeUrl(it.maps_url) ? `<a class="row" href="${esc(it.maps_url)}" target="_blank" rel="noopener">${tile('gray', 'pin')}<span class="main"><span class="t">Open in Google Maps</span><span class="s">Hours, photos and reviews</span></span>${ICON.chev}</a>` : ''}
      </div><div class="section-f">Save it to see opening hours, the menu, and to add it to folders and trips.</div></div>`;
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
      html: `${rootNav('Concierge', { right: msgs.length ? `<button class="gbtn" data-act="chatnew" aria-label="New conversation">${ICON.plus}</button>` : '' })}
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
    const [trips, places, folders] = await Promise.all([cachedTrips(), cachedPlaces(), cachedFolders()]);
    const groups = [{ id: 'all', name: 'All saved', n: places.length },
      ...trips.map((t) => ({ id: t.id, name: t.name, n: t.place_count, has: (p) => p.trip_ids.includes(t.id) })),
      ...folders.map((fo) => ({ id: fo.id, name: fo.name, n: fo.place_count, folder: true, has: (p) => p.folder_ids.includes(fo.id) }))];
    if (!S.mapTrip || !groups.some((g) => g.id === S.mapTrip)) S.mapTrip = 'all';
    const group = groups.find((g) => g.id === S.mapTrip);
    const shown = group.has ? places.filter(group.has) : places;
    const chips = `<div class="mapchips top">${groups.map((g) =>
      `<button class="mapchip ${S.mapTrip === g.id ? 'on' : ''}" data-act="maptrip" data-id="${g.id}" aria-pressed="${S.mapTrip === g.id}">${g.folder ? ICON.folder : ''}${esc(g.name)} · ${g.n}</button>`).join('')}</div>`;
    return {
      html: `<h1 class="vh">All places</h1><div class="map fill"><div id="all-map" style="position:absolute;inset:0"></div>
        <a class="gbtn mapback" href="#/library" data-act="back" data-fallback="#/library" aria-label="Back to Library">${ICON.back}</a>${groups.length > 1 ? chips : ''}
        ${!places.length ? '<div class="mapnote">No places yet. Share a reel to start.</div>' : ''}</div>`,
      after: () => renderMap($('#all-map'), shown, { popup: popupHtml, newIds: S.newIds, pad: { top: 90, bottom: 120 } }),
    };
  },

  async imports() {
    revalidate('jobs', loadJobs);
    schedulePoll();
    return `${navbar('Imports', { back: '#/profile', backLabel: 'Profile', right: addButton })}
      <h1 class="largetitle" data-anchor>Imports</h1>
      ${S.jobs.length ? `<div class="section"><div class="group tiles">${S.jobs.map(jobRow).join('')}</div>
        <div class="section-f">Tap a finished import to see its places.</div></div>`
        : emptyState('blue', 'tray', 'Nothing imported yet', 'Reels you share to Travel Edit show up here while they’re processed.')}`;
  },

  async usage() { return usageView(); },

  async profile() {
    if (!S.config) { S.config = await api('/v1/config'); configureMaps({ googleMapsKey: S.config.google_maps_key }); }
    if (!S.profile) await loadProfile().catch(() => {});
    if (S.homeCity === undefined) S.homeCity = await api('/v1/home').catch(() => null);
    if (S.me === undefined) S.me = await api('/v1/me').catch(() => null);
    const me = S.me;
    const origin = location.origin;
    const key = getKey();
    const geocoder = { google: 'Google Places', openstreetmap: 'OpenStreetMap', none: 'Off' }[S.config.geocoder] || S.config.geocoder;
    const copyLine = (value, label) => `<div class="copyline"><code>${esc(value)}</code><button class="copybtn" data-act="copy" data-value="${esc(value)}" aria-label="Copy ${label}">Copy</button></div>`;
    const push = await pushState();
    const pushNote = {
      install: 'On iPhone, notifications work once Travel Edit is on your Home Screen (see below). Open it from there, then turn this on.',
      denied: 'Notifications are blocked for Travel Edit. Turn them on in Settings → Notifications → Travel Edit.',
      unsupported: 'This browser can’t show notifications from The Travel Edit.',
      off: 'Get a notification when a reel you shared has been turned into places, or if it couldn’t be read.',
      on: 'You’ll get a notification when each shared reel’s places are saved.',
    }[push];
    return `${navbar('Profile', backToTab())}<h1 class="largetitle" data-anchor>Profile</h1>
      <div class="subtitle"><span>${me ? esc(me.email) : 'Your taste, home city and app settings'}</span></div>

      ${me ? `<div class="section"><div class="section-h">Account</div><div class="group tiles">
        <button class="row" data-act="changepw">${tile('gray', 'lock')}<span class="main"><span class="t">Change password</span></span>${ICON.chev}</button>
        ${me.is_admin ? `<button class="row" data-act="invites">${tile('gold', 'plus')}<span class="main"><span class="t">Invite people</span>
          <span class="s">Make a one-time code for each tester</span></span>${ICON.chev}</button>
        <button class="row" data-act="people">${tile('blue', 'person')}<span class="main"><span class="t">People</span>
          <span class="s">Everyone with an account; reset a forgotten password</span></span>${ICON.chev}</button>
        <a class="row" href="#/usage">${tile('green', 'tag')}<span class="main"><span class="t">Usage & costs</span>
          <span class="s">AI spend by day, feature and person; budgets and daily limits</span></span>${ICON.chev}</a>` : ''}
        <button class="row" data-act="feedback">${tile('indigo', 'sparkle')}<span class="main"><span class="t">Send feedback</span>
          <span class="s">Something broken, confusing or missing? Tell us</span></span>${ICON.chev}</button>
        <button class="row" data-act="signout">${tile('red', 'signout')}<span class="main"><span class="t" style="color:var(--danger)">Sign out</span></span></button>
      </div></div>` : `<div class="section"><div class="group tiles"><a class="row" href="#/signin">${tile('gold', 'person')}<span class="main"><span class="t">Create your account</span>
        <span class="s">Keeps your places private and lets you invite testers</span></span>${ICON.chev}</a></div></div>`}

      ${EMBED ? '' : `<div class="section"><div class="section-h">Appearance</div>
        <div class="visitseg" role="group" aria-label="Appearance">${[['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([k, label]) =>
          `<button data-act="settheme" data-v="${k}" aria-pressed="${themeOf() === k}" class="${themeOf() === k ? 'on' : ''}">${label}</button>`).join('')}</div>
        <div class="section-f">Light is warm ivory; Dark is espresso. System follows your device.</div></div>`}
      <div class="section"><div class="section-h">You</div><div class="group tiles">
        <button class="row" data-act="homecity">${tile('green', 'pin')}<span class="main"><span class="t">Home city</span>
          <span class="s">${esc(S.homeCity ? [S.homeCity.city, S.homeCity.country].filter(Boolean).join(', ') : 'Discover looks here first')}</span></span>${ICON.chev}</button>
        <a class="row" href="#/imports">${tile('blue', 'tray')}<span class="main"><span class="t">Imports</span>
          <span class="s">${S.jobs.some((j) => ACTIVE.has(j.status)) ? 'Working on a reel…' : 'Reels you’ve shared and their status'}</span></span>${ICON.chev}</a>
        <a class="row" href="#/taste">${tile('gold', 'sparkle')}<span class="main"><span class="t">Your travel taste</span>
          <span class="s">${esc(tasteSummary(S.profile) || 'Tailors your edits, briefings and concierge')}</span></span>${ICON.chev}</a>
      </div></div>

      ${NATIVE ? '' : `<div class="section"><div class="section-h">Notifications</div><div class="group tiles">
        <label class="row" for="push-toggle">${tile('red', 'bell')}<span class="main"><span class="t">Import notifications</span></span>
          <input class="switch" type="checkbox" id="push-toggle" data-act="pushtoggle" ${push === 'on' ? 'checked' : ''} ${['on', 'off'].includes(push) ? '' : 'disabled'}></label>
        ${push === 'on' ? `<button class="row" data-act="pushtest">${tile('gray', 'bell')}<span class="main"><span class="t link">Send a test notification</span></span></button>` : ''}
      </div><div class="section-f">${pushNote}</div></div>`}

      <div class="section"><div class="section-h">Offline</div><div class="group tiles">
        <div class="row">${tile('teal', 'offline')}<span class="main"><span class="t">Works without signal</span>
          <span class="s">Trips you open are kept on this phone, with their photos and the map areas you’ve viewed. Today’s trip is saved automatically.</span></span></div>
      </div><div class="section-f">To save a whole trip before you go, open it and choose ••• → Save for offline.</div></div>

      ${NATIVE ? `<div class="section"><div class="section-h">Share from TikTok &amp; Instagram</div><div class="group tiles">
        <div class="row">${tile('indigo', 'share')}<span class="main"><span class="t">Share → Travel Edit</span>
          <span class="s">In TikTok tap Share → More (•••); in Instagram tap the paper plane → Share to…. The places appear in Saved about a minute later.</span></span></div>
      </div></div>` : `<div class="section"><div class="section-h">Share from TikTok &amp; Instagram</div><div class="group">
        <div class="row">${tile('indigo', 'share', 'md')}<span class="main"><span class="t b">iPhone share button</span><span class="s">A one-time shortcut in the Shortcuts app</span></span></div>
        <ol class="steps">
          <li>Open the <b>Shortcuts</b> app, tap <b>+</b> and name the shortcut <b>Travel Edit</b>.</li>
          <li>Tap the <b>ⓘ</b> button (or the name at the top) and turn on <b>Show in Share Sheet</b>. Tap <b>Done</b>.</li>
          <li>At the top it now says “Receive <i>Any</i> input from Share Sheet”. Tap <i>Any</i> and keep only <b>URLs</b> and <b>Text</b>.</li>
          <li>Add the action <b>Get Contents of URL</b>. Set the URL to the address below.</li>
          <li>Tap the <b>›</b> arrow on that action: set <b>Method</b> to <b>POST</b>; under <b>Headers</b> add <span class="kbd">X-API-Key</span> with your key below; set <b>Request Body</b> to <b>JSON</b> and add a <b>Text</b> field named <span class="kbd">url</span> whose value is the <b>Shortcut Input</b> variable.</li>
          <li>Optional: add <b>Show Notification</b> with the text “Saved to Travel Edit”.</li>
          <li>In TikTok tap <b>Share → More (•••)</b>, or in Instagram tap the <b>paper plane → Share to…</b>, then choose <b>Travel Edit</b>. The first time, you may need to scroll the app row and add Travel Edit to your favorites.</li>
        </ol>
        <div class="sublabel">Shortcut URL</div>${copyLine(`${origin}/v1/jobs`, 'shortcut URL')}
        <div class="sublabel">X-API-Key</div>${me
          ? `<div class="copyline"><span class="s">${me.has_import_key ? 'You made a key already. Lost it? Make a new one; the old one stops working.' : 'A personal key that can only send links to your library.'}</span>
              <button class="copybtn" data-act="importkey">${me.has_import_key ? 'New key' : 'Make key'}</button></div>`
          : key ? copyLine(key, 'API key') : '<div class="copyline"><span class="s">This server doesn’t require a key.</span></div>'}
      </div>
      <div class="section-f">Simpler but opens Travel Edit each time: make the shortcut a single <b>Open URLs</b> action with <span class="kbd">${esc(origin)}/share?url=</span> followed by the <b>Shortcut Input</b> variable. It opens in Safari, so sign in there once too.</div></div>

      <div class="section"><div class="section-h">Home Screen</div><div class="group">
        <div class="row">${tile('blue', 'home', 'md')}<span class="main"><span class="t b">Add Travel Edit to your Home Screen</span><span class="s">Opens full screen, like an app</span></span></div>
        <ol class="steps">
          <li>Open this page in <b>Safari</b>.</li>
          <li>Tap the <b>Share</b> button, then <b>Add to Home Screen</b>.</li>
          <li>On Android, use Chrome’s <b>Install app</b> and Travel Edit appears in the share sheet automatically.</li>
        </ol></div></div>`}

      <div class="section"><div class="section-h">Server</div><div class="group tiles">
        <div class="row">${tile('gray', 'server')}<span class="main"><span class="s">Address</span><span class="t">${esc(origin)}</span></span></div>
        <div class="row">${tile('green', 'pin')}<span class="main"><span class="t">Finding places</span></span><span class="val">${esc(geocoder)}</span></div>
        <div class="row">${tile('orange', 'route')}<span class="main"><span class="t">Travel times</span></span><span class="val">${S.config.routing === 'google' ? 'Google Routes' : 'Estimated'}</span></div>
        <div class="row">${tile('blue', 'map')}<span class="main"><span class="t">Maps in the app</span></span><span class="val">${mapProvider() === 'google' ? 'Google Maps' : 'OpenStreetMap'}</span></div>
        ${!me && key ? `<button class="row" data-act="signout">${tile('red', 'signout')}<span class="main"><span class="t" style="color:var(--danger)">Sign out on this device</span></span></button>` : ''}
      </div></div>
      ${me ? `<div class="section"><div class="group"><button class="row" data-act="deleteaccount"><span class="main"><span class="t" style="color:var(--danger)">Delete account</span>
        <span class="s">Removes your account and everything you saved</span></span></button></div></div>` : ''}`;
  },

  async signin(r) {
    const status = await api('/v1/auth/status').catch(() => ({ accounts: true }));
    const first = !status.accounts;
    const mode = first ? 'first' : (r.params.get('mode') === 'join' ? 'join' : 'in');
    const seg = first ? '' : segControl('auth', [['in', 'Sign in'], ['join', 'Create account']].map(([m, label]) => ({
      on: m === mode, html: `<a href="#/signin${m === 'join' ? '?mode=join' : ''}" data-replace class="${m === mode ? 'on' : ''}">${label}</a>`,
    })));
    const field = (id, label, type, auto, extra = '') => `<label class="row authrow" for="${id}"><span class="lbl">${label}</span>
      <input class="field" id="${id}" name="${id}" type="${type}" autocomplete="${auto}" ${extra} required></label>`;
    const fields = mode === 'in'
      ? field('email', 'Email', 'email', 'username', 'inputmode="email" autocapitalize="off"') + field('password', 'Password', 'password', 'current-password')
      : field('email', 'Email', 'email', 'username', 'inputmode="email" autocapitalize="off"')
        + field('password', 'Password', 'password', 'new-password', 'minlength="8" placeholder="At least 8 characters"')
        + field('invite', first ? 'Server key' : 'Invite code', first ? 'password' : 'text', 'off', `autocapitalize="characters" ${first ? '' : 'placeholder="ABCD-2345"'}`);
    const lead = first
      ? 'Create the first account. Use the server key (APP_API_KEY) as the code: everything already saved in The Travel Edit becomes yours, and you can invite others after.'
      : mode === 'join' ? 'The Travel Edit is invite-only for now. Enter the code you were given.' : 'Your places, folders and trips, on any device.';
    return `<div class="authpage">
      <div class="authmark" aria-hidden="true">${ICON.bookmark}</div>
      <h1 class="authtitle">${first ? 'Set up The Travel Edit' : mode === 'join' ? 'Join The Travel Edit' : 'Welcome back'}</h1>
      <p class="authlead">${lead}</p>${seg}
      <form class="section" data-form="${mode === 'in' ? 'signin' : 'signup'}" novalidate><div class="group">${fields}</div>
        <div class="section-f autherr" id="auth-error" role="alert"></div>
        <button class="btn wide" type="submit">${mode === 'in' ? 'Sign in' : 'Create account'}</button>
        ${mode === 'in' ? '<p class="section-f authhelp">Forgot your password? Ask whoever invited you to reset it.</p>' : ''}
      </form></div>`;
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

const DIETS = { vegetarian: 'Vegetarian', vegan: 'Vegan', gluten_free: 'Gluten-free', spicy: 'Spicy' };

/** The Menu tab of a place page. */
async function menuSection(p) {
  let m = S.menu[p.id];
  if (!m) {
    try { m = S.menu[p.id] = await api(`/v1/places/${p.id}/menu`); } catch (e) { return `<div class="error" role="alert">${esc(e.message)}</div>`; }
  }
  const site = safeUrl(p.website);
  const links = `<div class="menulinks">${site ? `<a class="linkbtn" href="${esc(site)}" target="_blank" rel="noopener">Website</a>` : ''}
    ${safeUrl(p.maps_url) ? `<a class="linkbtn" href="${esc(p.maps_url)}" target="_blank" rel="noopener">Google Maps</a>` : ''}</div>`;
  if (S.menuBusy[p.id]) {
    return `<div class="empty menuwait"><span class="spinner big"></span><h3>Looking for the menu</h3>
      <p>Checking ${site ? 'the website' : 'what’s online'} and reading it for you. This can take up to a minute.</p></div>`;
  }
  const siteBtn = `<button class="linkbtn" data-act="menuwebsite" data-id="${p.id}">${site ? 'Use a different website' : 'Add the restaurant’s website'}</button>
    <button class="linkbtn" data-act="menuupload" data-id="${p.id}">Add a photo or PDF of the menu</button>`;
  if (m.status === 'unknown') {
    return emptyState('accent', 'book', 'See the menu',
      `We’ll look for it ${site ? 'on the website' : 'online'} and lay it out neatly here. If it’s only on Google, a screenshot works too.`,
      `<button class="btn" data-act="findmenu" data-id="${p.id}">${ICON.search}Find the menu</button>${siteBtn}`);
  }
  if (m.status === 'none') {
    return `${emptyState('gray', 'book', 'No menu found',
      'We couldn’t find a menu we could read. Some places only post theirs on Instagram or a delivery app. Seen it on Google? Screenshot the menu there and add it here.',
      `<button class="btn tint" data-act="findmenu" data-id="${p.id}" data-refresh="1">Try again</button>${siteBtn}${links}`)}
      ${m.trace && m.trace.length ? `<div class="section"><div class="section-h">What we tried</div><div class="group"><div class="notecard"><ul class="trace">${m.trace.map((t) => `<li>${esc(t)}</li>`).join('')}</ul></div></div></div>` : ''}`;
  }
  const host = (() => { try { return new URL(m.source_url).hostname.replace(/^www\./, ''); } catch { return ''; } })();
  const source = m.source_kind === 'upload' ? 'From the photo or PDF you added' : m.source_kind === 'photos'
    ? 'Read from photos on Google Maps'
    : `From ${host && safeUrl(m.source_url) ? `<a href="${esc(m.source_url)}" target="_blank" rel="noopener">${esc(host)}</a>` : 'the website'}`;
  const present = Object.keys(DIETS).filter((tag) => m.sections.some((s) => s.items.some((i) => i.tags.includes(tag))));
  const diet = present.includes(S.menuDiet[p.id]) ? S.menuDiet[p.id] : null;
  const keep = (i) => !diet || i.tags.includes(diet) || (diet === 'vegetarian' && i.tags.includes('vegan'));
  const sections = m.sections.map((s) => ({ ...s, items: s.items.filter(keep) })).filter((s) => s.items.length);
  const chips = present.length ? `<div class="fchips" role="group" aria-label="Dietary filter">${present.map((tag) =>
    `<button class="fchip${diet === tag ? ' on' : ''}" data-act="menudiet" data-id="${p.id}" data-tag="${tag}" aria-pressed="${diet === tag}">${DIETS[tag]}</button>`).join('')}</div>` : '';
  return `<div class="menuhead"><span class="s">${source} · ${timeAgo(m.fetched_at)}</span>
      <button class="linkbtn" data-act="findmenu" data-id="${p.id}" data-refresh="1">Refresh</button></div>
    ${m.notes ? `<div class="section"><div class="group"><div class="notecard">${esc(m.notes)}</div></div></div>` : ''}${chips}
    ${sections.map((s) => `<div class="section"><h2 class="section-title">${esc(s.title)}<span class="count">${s.items.length}</span></h2>
      ${s.note ? `<div class="section-f menusub">${esc(s.note)}</div>` : ''}
      <div class="group menu">${s.items.map((i) => `<div class="row menuitem"><span class="main"><span class="t">${esc(i.name)}${i.tags.map((tag) => `<span class="mtag" title="${DIETS[tag]}">${esc(DIETS[tag])}</span>`).join('')}</span>
        ${i.description ? `<span class="s">${esc(i.description)}</span>` : ''}</span>${i.price ? `<span class="price">${esc(i.price)}</span>` : ''}</div>`).join('')}</div></div>`).join('')
      || '<div class="section"><div class="section-f">Nothing on the menu matches that filter.</div></div>'}
    <div class="section"><div class="section-f">Menus change. Check with the restaurant for today’s dishes and prices.${m.source_kind === 'photos' || m.source_kind === 'upload' ? ' Read from photos, so some items may be missing or misread.' : ''}</div>
      <button class="linkbtn" data-act="menuupload" data-id="${p.id}">Wrong or missing dishes? Add a photo or PDF of the menu</button></div>`;
}

const fileToBase64 = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
  reader.onerror = () => reject(new Error(`Couldn’t read ${file.name || 'that file'}`));
  reader.readAsDataURL(file);
});

/** For sites the server can't read: photos or a PDF of the menu, picked on the phone. */
function pickMenuFiles(id) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*,application/pdf';
  input.multiple = true;
  input.onchange = async () => {
    const files = [...input.files];
    if (!files.length) return;
    S.menuBusy[id] = true;
    render();
    try {
      const images = [];
      const pdfs = [];
      for (const f of files) {
        if (f.type === 'application/pdf' || /\.pdf$/i.test(f.name)) { if (pdfs.length < 2) pdfs.push(await fileToBase64(f)); }
        else if (images.length < 6) images.push(await toJpegDataUrl(f));
      }
      S.menu[id] = await api(`/v1/places/${id}/menu/upload`, { method: 'POST', body: { images, pdfs } });
      toast('Menu added');
    } catch (e) {
      toast(e.message, true);
    } finally {
      delete S.menuBusy[id];
      render();
    }
  };
  input.click();
}

async function runFindMenu(id, refresh) {
  S.menuBusy[id] = true;
  render();
  try {
    S.menu[id] = await api(`/v1/places/${id}/menu`, { method: 'POST', body: { refresh } });
    if (S.menu[id].status === 'none') toast('No menu found');
  } catch (e) {
    toast(e.message, true);
  } finally {
    delete S.menuBusy[id];
    render();
  }
}

/** Rating, website and phone rows for a place's Details (only the ones we have). */
/** On a place's page: the folders and trips it's in, with ways to add it to more. */
function librarySection(p, trip) {
  const folders = (S.folders || []).filter((fo) => (p.folder_ids || []).includes(fo.id)).map((fo) => fo.name);
  const trips = (S.trips || []).filter((t) => (p.trip_ids || []).includes(t.id)).map((t) => t.name);
  if (!S.folders) loadFolders().then(() => render({ quiet: true })).catch(() => {});
  if (p.suggested && trip.id) {
    return `<div class="section"><div class="group tiles"><div class="row">${tile('gold', 'sparkle')}<span class="main"><span class="t">Suggested for this trip</span>
      <span class="s">${esc(p.suggestion_note || 'Added by AI to fill a quiet day')}</span></span>
      <button class="btn tint small" data-act="keepsugg" data-trip="${trip.id}" data-id="${p.id}">Keep</button></div></div></div>`;
  }
  return `<div class="section"><div class="section-h">In your library</div><div class="group tiles">
    <button class="row" data-act="placefolders" data-id="${p.id}">${tile('gold', 'folder')}<span class="main"><span class="t">Folders</span>
      <span class="s">${esc(folders.join(', ') || 'Not in a folder')}</span></span><span class="s link">Edit</span>${ICON.chev}</button>
    <button class="row" data-act="placetrips" data-id="${p.id}">${tile('blue', 'plane')}<span class="main"><span class="t">Trips</span>
      <span class="s">${esc(trips.join(', ') || 'Not in a trip yet')}</span></span><span class="s link">Add</span>${ICON.chev}</button>
    ${trip.id ? `<button class="row" data-act="removefromtrip" data-trip="${trip.id}" data-id="${p.id}">${tile('gray', 'close')}<span class="main"><span class="t">Remove from ${esc(trip.name)}</span>
      <span class="s">It stays in your saved places</span></span></button>` : ''}
  </div></div>`;
}

function contactRows(p) {
  const rows = [];
  const googleLink = safeUrl(p.maps_url) && /^https?:\/\/([a-z0-9-]+\.)*(google\.[a-z.]+|goo\.gl)\//i.test(p.maps_url) ? p.maps_url : null;
  if (p.rating) {
    const body = `${tile('gold', 'star')}<span class="main"><span class="s">Google rating</span>
      <span class="t">${p.rating.toFixed(1)}${p.rating_count ? ` · ${p.rating_count.toLocaleString()} reviews` : ' out of 5'}</span></span>`;
    rows.push(googleLink
      ? `<a class="row" href="${esc(googleLink)}" target="_blank" rel="noopener">${body}<span class="s link">Read reviews</span>${ICON.chev}</a>`
      : `<div class="row">${body}</div>`);
  }
  const site = safeUrl(p.website);
  if (site) {
    let host = site;
    try { host = new URL(site).hostname.replace(/^www\./, ''); } catch { /* show the address as is */ }
    rows.push(`<a class="row" href="${esc(site)}" target="_blank" rel="noopener">${tile('blue', 'globe')}<span class="main"><span class="s">Website</span>
      <span class="t link">${esc(host)}</span></span>${ICON.chev}</a>`);
  }
  if (p.phone) {
    rows.push(`<a class="row" href="tel:${esc(p.phone.replace(/[^\d+]/g, ''))}">${tile('green', 'phone')}<span class="main"><span class="s">Phone</span>
      <span class="t link">${esc(p.phone)}</span></span>${ICON.chev}</a>`);
  }
  return rows.join('');
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
  const addBtn = `<button class="btn tint small" data-act="tripaddplaces" data-id="${trip.id}">${ICON.plus}Add from saved</button>`;
  if (!trip.places.length) {
    return emptyState('gray', 'pinslash', 'No places on this trip yet', 'Add places from everything you’ve saved, or from one of your folders.',
      `<button class="btn" data-act="tripaddplaces" data-id="${trip.id}">${ICON.plus}Add from saved</button>`);
  }
  const bar = `<div class="planbar"><span class="planned-by">${S.sel.on ? 'Tick places, then add them to a day' : addBtn}</span>
    <button class="linkbtn" data-act="selecttoggle">${S.sel.on ? 'Done' : 'Select'}</button></div>`;
  const sugg = trip.places.filter((p) => p.suggested);
  const suggHtml = sugg.length ? `<div class="section"><h2 class="section-title">${tile('gold', 'sparkle')}Suggested for quiet days<span class="count">${sugg.length}</span></h2>
    <div class="group thumbs">${sugg.map((p) => `<div class="row prow"><a class="rowlink" href="${placeHref(p)}">${thumb(p, 56)}<span class="main">
      <span class="t">${esc(p.name)}</span><span class="s">${esc([CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}${dayChip(p)}</span>
      ${p.suggestion_note ? `<span class="s why">${esc(p.suggestion_note)}</span>` : ''}</span></a>
      <span class="suggacts"><button class="btn tint small" data-act="keepsugg" data-trip="${trip.id}" data-id="${p.id}">Keep</button>
      <button class="linkbtn" data-act="dropsugg" data-trip="${trip.id}" data-id="${p.id}" aria-label="Remove ${esc(p.name)}">Remove</button></span></div>`).join('')}</div>
    <div class="section-f">Keep one and it joins your saved places too.</div></div>` : '';
  const mine = { ...trip, places: trip.places.filter((p) => !p.suggested) };
  return bar + suggHtml + CAT_ORDER.filter((c) => mine.places.some((p) => p.category === c)).map((c) => {
    const list = mine.places.filter((p) => p.category === c).sort(byPriority);
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
      ${!S.editDay && dayBookings(trip, d).length ? bookingRows(dayBookings(trip, d)) : ''}
      <div class="group${S.editDay ? ' droplist' : ''}" data-day="${d}">${list.map((p, i) => {
        const conflict = slotConflict(p.opening_hours, dayIdx, p.time_of_day, p.start_time);
        const todays = dayIdx != null ? dayHours(p.opening_hours, dayIdx) : null;
        const inner = `<span class="stopnum" style="${cvar(p.category)}">${i + 1}</span>
          ${thumb(p, 52)}
          <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${starMark(p)}${isNew(p)}</span>
          <span class="s">${esc([p.start_time ? fmtClock(p.start_time) : cap(p.time_of_day || ''), CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}${needChip(p)}</span>
          ${todays && !conflict ? `<span class="s">${ICON.clock.replace('<svg', '<svg class="inline-ic"')}${esc(todays)}</span>` : ''}
          ${conflict ? `<span class="warnline">${ICON.warn}${esc(conflict)}${todays && todays !== 'Closed' ? ` (${esc(todays)})` : ''}</span>` : ''}
          ${p.day_note ? `<span class="daynote">${esc(p.day_note)}</span>` : ''}
          ${hereChip(p)}</span>`;
        const next = locatedList[locatedList.indexOf(p) + 1];
        const legRow = located(p) && next && !S.editDay
          ? `<div class="leg" data-day="${d}" data-from="${p.id}" data-to="${next.id}"><span class="spinner" style="width:14px;height:14px"></span></div>` : '';
        return (S.editDay ? dragRow(p, inner) : `<a class="row" href="${placeHref(p)}">${inner}${ICON.chev}</a>`) + legRow;
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
    <a class="popup-link" href="${placeHref(p)}">Details ›</a>`;
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
  const r = route();
  const st = { text: '', trip: tripId, folder: r.name === 'folder' ? r.id : null, results: '', hint: '' };
  openSheet({
    type: 'form', title: 'Add', confirm: 'Add', st,
    body: () => `<div class="section"><div class="group"><label class="row searchrow" for="add-input">${ICON.search}
        <input class="field" id="add-input" type="text" data-act="addinput" value="${esc(st.text)}" placeholder="Paste a link or search for a place"
          autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="go" aria-label="Link or place name"></label></div>
        <div class="section-f" id="add-hint">${st.hint || 'TikTok, Instagram and YouTube links find every place in the video. Google Maps and Apple Maps links add that place.'}</div></div>
      <div id="add-results">${st.results}</div>
      <div class="section"><div class="group tiles">
        <label class="row" for="add-trip">${tile('blue', 'trips')}<span class="main"><span class="t">Also add to</span></span>
          <select class="select" id="add-trip" data-act="addtrip">
            <option value="">Just save it</option>
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
    const res = await api(path, { method: 'POST', body: { ...body, folder_id: S.sheet && S.sheet.st && S.sheet.st.folder || null } });
    const trip = res.place.trip_id ? await loadTrip(res.place.trip_id) : null;
    await afterLibraryChange();
    closeSheet();
    const where = trip ? trip.name : 'your saved places';
    toast(res.created ? `Saved ${res.place.name}${trip ? ` to ${trip.name}` : ''}` : `${res.place.name} is already in ${where}`);
    go(placeHref(res.place));
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

// ---------- Bookings: flights, stays, tables and cars ----------

const BOOKING_KINDS = {
  flight: ['Flight', 'blue', 'plane'], hotel: ['Hotel', 'indigo', 'stay'], reservation: ['Table', 'gold', 'food'],
  car: ['Car', 'green', 'drive'], other: ['Booking', 'gray', 'tag'],
};
const BOOKING_FIELDS = ['kind', 'title', 'start_at', 'end_at', 'origin', 'destination', 'address', 'confirmation', 'party_size', 'notes'];

/** "2026-11-07T19:25" → {date, time, day}; local wall-clock times, shown as printed on the booking. */
function parseWhen(value) {
  if (!value) return null;
  const [date, time = null] = value.split('T');
  const [y, m, d] = date.split('-').map(Number);
  return { date, time, day: new Date(y, m - 1, d) };
}
const fmtDay = (day) => day.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
const mapsSearch = (query) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;

function bookingDetails(b) {
  const s = parseWhen(b.start_at);
  const e = parseWhen(b.end_at);
  const at = (w, prefix) => (w && w.time ? `${prefix} ${fmtClock(w.time)}` : '');
  let sub = '';
  let meta = '';
  if (b.kind === 'flight') {
    sub = [at(s, 'Departs'), b.notes].filter(Boolean).join(' · ');
    meta = e ? `Lands ${s && e.date !== s.date ? `${fmtDay(e.day)}${e.time ? ', ' : ''}` : ''}${e.time ? fmtClock(e.time) : ''}`.trim() : '';
  } else if (b.kind === 'hotel') {
    const nights = s && e ? Math.round((e.day - s.day) / 86400000) : 0;
    sub = [s && s.time ? `Check-in from ${fmtClock(s.time)}` : 'Check-in', nights > 0 ? plural(nights, 'night') : ''].filter(Boolean).join(' · ');
    meta = b.address || '';
  } else if (b.kind === 'reservation') {
    sub = [b.party_size ? `Table for ${b.party_size}` : 'Reservation', s && s.time ? fmtClock(s.time) : ''].filter(Boolean).join(' · ');
    meta = b.address || '';
  } else if (b.kind === 'car') {
    sub = [at(s, 'Pick-up'), e ? `Drop-off ${fmtDay(e.day)}` : ''].filter(Boolean).join(' · ');
    meta = [b.origin, b.destination].filter(Boolean).join(' → ');
  } else {
    sub = [s && s.time ? fmtClock(s.time) : '', b.notes].filter(Boolean).join(' · ');
    meta = b.address || '';
  }
  return { sub, meta };
}

function bookingCard(b, { trip = null } = {}) {
  const [label, color, icon] = BOOKING_KINDS[b.kind] || BOOKING_KINDS.other;
  const { sub, meta } = bookingDetails(b);
  const tripChip = trip ? `<a class="tripchip" href="#/trip/${b.trip_id}" data-act="link">${ICON.trips}${esc(trip)}</a>` : '';
  const route = b.kind === 'flight' && b.origin && b.destination
    ? `<div class="route"><span>${esc(b.origin)}</span><span class="line">${ICON.plane}</span><span>${esc(b.destination)}</span></div>` : '';
  const place = b.place_id ? `<a class="linkbtn pl" href="#/place/${b.place_id}" data-act="link">Open place</a>` : '';
  const directions = b.kind === 'hotel' && b.address
    ? `<a class="linkbtn pl" href="${esc(mapsSearch(`${b.title} ${b.address}`))}" target="_blank" rel="noopener" data-act="link">Directions</a>` : '';
  const lounges = b.kind === 'flight' && b.origin
    ? `<button class="linkbtn pl" data-act="lounges" data-id="${b.id}">${ICON.sparkle}Lounges at ${esc(b.origin)}</button>` : '';
  return `<div class="bcard" data-act="bookingmenu" data-id="${b.id}" role="button" tabindex="0" aria-label="${esc(label)}: ${esc(b.title)}. Tap for options">
    <div class="top">${tile(color, icon)}<span class="main"><span class="t">${esc(b.title)}</span><span class="s">${esc(sub)}</span></span><span class="pill2">${esc(label)}</span></div>
    ${route}
    ${meta || b.confirmation ? `<div class="meta"><span>${esc(meta)}</span>${b.confirmation ? `<span class="conf">${esc(b.confirmation)}</span>` : ''}</div>` : ''}
    ${place || directions || lounges || tripChip ? `<div class="bactions">${tripChip}${directions}${place}${lounges}</div>` : ''}</div>`;
}

/** Lounges at the airport a flight leaves from: name, terminal, how to get in. */
async function loungeSheet(trip, b, refresh = false) {
  const st = { res: null, error: '' };
  const draw = () => { if (S.sheet && S.sheet.st === st) renderOverlay(); };
  openSheet({
    type: 'form', title: `Lounges at ${b.origin || 'the airport'}`, confirm: 'Done', st,
    body: () => {
      if (st.error) return `<div class="section"><div class="section-f">${esc(st.error)}</div></div>`;
      if (!st.res) return '<div class="section"><div class="section-f"><span class="spinner"></span> Looking up lounges…</div></div>';
      if (st.res.status === 'no_airport') return '<div class="section"><div class="section-f">We couldn’t tell which airport this is. Edit the flight and put the departure airport’s code (like JFK) in From.</div></div>';
      if (st.res.status === 'error') return '<div class="section"><div class="section-f">Couldn’t look up lounges right now. Try again in a moment.</div></div>';
      const { lounges, airport_name: name } = st.res;
      if (!lounges.length) return `<div class="section"><div class="section-f">No lounges we’re confident about at ${esc(name || b.origin)}.</div></div>`;
      return `<div class="section"><div class="section-h">${esc(name || b.origin)}</div>${lounges.map((l) => `<div class="group tiles"><div class="row lounge">
        <span class="main"><span class="t">${esc(l.name)}</span>
        <span class="s">${esc([l.terminal, l.location, l.hours ? `Open ${l.hours}` : ''].filter(Boolean).join(' · ') || 'Terminal not confirmed')}</span>
        ${l.access.length ? `<span class="s"><b>Access:</b> ${esc(l.access.join(' · '))}</span>` : '<span class="s">Access rules not confirmed</span>'}</span></div></div>`).join('')}
        <div class="section-f">From Claude’s knowledge, not a live feed. Lounges change hours, terminals and access rules, so check with the airport, your card or your airline before you rely on one.</div></div>`;
    },
    ok: async () => closeSheet(),
  });
  try { st.res = await api(`/v1/trips/${trip.id}/bookings/${b.id}/lounges${refresh ? '?refresh=true' : ''}`); }
  catch (e) { st.error = e.message; }
  draw();
}

/** On a trip's page: a way into its bookings on the Bookings tab. */
function bookingsCard(trip) {
  const n = (trip.bookings || []).length;
  if (!n || trip.kind === 'local') return '';
  return `<div class="section"><a class="group tiles packcard" href="#/bookings?trip=${trip.id}"><span class="row">${tile('blue', 'bookings')}<span class="main"><span class="t">Bookings</span>
    <span class="s">${plural(n, 'booking')} for this trip</span></span>${ICON.chev}</span></a></div>`;
}

function bookingsView(trip) {
  const list = trip.bookings || [];
  if (!list.length) {
    return emptyState('blue', 'plane', 'No bookings yet',
      'Keep your flights, hotel and table reservations here, next to your places. Add one from a screenshot or the confirmation email text, or enter it yourself.',
      `<button class="btn" data-act="addbooking" data-id="${trip.id}">${ICON.plus}Add a booking</button>`);
  }
  const groups = [];
  list.forEach((b) => {
    const key = b.start_at ? b.start_at.slice(0, 10) : '';
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(b); else groups.push({ key, items: [b] });
  });
  return `${groups.map((g) => `<div class="datehead">${g.key ? esc(fmtDay(parseWhen(g.key).day)) : 'No date'}</div>${g.items.map(bookingCard).join('')}`).join('')}
    <div class="section"><button class="btn tint wide" data-act="addbooking" data-id="${trip.id}">${ICON.plus}Add a booking</button>
    <div class="section-f">Keep confirmation numbers handy for the airport or front desk. Bookings stay private: shared trip links never include them.</div></div>`;
}

/** Bookings for a day of the itinerary (needs the trip's start date). A table booked for a saved place shows as that stop instead. */
function dayBookings(trip, day) {
  if (!trip.start_date || !trip.bookings) return [];
  const [y, m, d] = trip.start_date.split('-').map(Number);
  const iso = isoDate(new Date(y, m - 1, d + day - 1));
  return trip.bookings.filter((b) => b.start_at && b.start_at.slice(0, 10) === iso && !(b.kind === 'reservation' && b.place_id));
}
function bookingRows(list) {
  return `<div class="group tiles bookstrip">${list.map((b) => {
    const [label, color, icon] = BOOKING_KINDS[b.kind] || BOOKING_KINDS.other;
    const s = parseWhen(b.start_at);
    const route = b.kind === 'flight' && b.origin && b.destination ? ` ${b.origin} → ${b.destination}` : '';
    return `<div class="row">${tile(color, icon)}<span class="main"><span class="t">${esc(b.title)}${esc(route)}</span>
      <span class="s">${esc([label, s && s.time ? fmtClock(s.time) : '', b.confirmation ? `Ref ${b.confirmation}` : ''].filter(Boolean).join(' · '))}</span></span></div>`;
  }).join('')}</div>`;
}

function addBookingSheet(trip, { choose = false } = {}) {
  S.bkflow = null;
  const st = { tripId: trip.id };
  const opt = (act, color, icon, title, sub) => `<button class="row" data-act="${act}" data-id="${st.tripId}">${tile(color, icon)}<span class="main"><span class="t">${title}</span><span class="s">${sub}</span></span>${ICON.chev}</button>`;
  const trips = (S.trips || []).filter((t) => t.kind !== 'local' || t.id === trip.id);
  const picker = choose && trips.length > 1 ? `<div class="section"><div class="group tiles"><label class="row" for="bk-trip">${tile('blue', 'trips')}<span class="main"><span class="t">For</span></span>
      <select class="select" id="bk-trip" data-act="bktripsel">${trips.map((t) => `<option value="${t.id}" ${t.id === st.tripId ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label></div></div>` : '';
  openSheet({
    type: 'form', title: 'Add a booking', st,
    body: () => `${picker}<div class="section"><div class="group tiles">
      ${opt('bkshot', 'green', 'photo', 'Screenshot or photo', 'Of a confirmation, e-ticket or itinerary')}
      ${opt('bktext', 'orange', 'note', 'Paste the email text', 'Claude reads flight, hotel and reservation details')}
      ${opt('bkmanual', 'gray', 'plus', 'Enter it yourself', 'Flight, stay, car or table')}
      </div><div class="section-f">Claude shows what it read so you can check it before saving. A confirmation number alone can’t be looked up, so The Travel Edit reads the confirmation itself.</div></div>`,
  });
}

function pickBookingShots(trip) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.multiple = true;
  input.onchange = async () => {
    const files = [...input.files].slice(0, 6);
    if (!files.length) return;
    try {
      const images = [];
      for (const f of files) images.push(await toJpegDataUrl(f));
      await readBookings(trip, { images });
    } catch (e) { toast(e.message, true); }
  };
  input.click();
}

function pasteBookingSheet(trip) {
  const st = { text: '' };
  openSheet({
    type: 'form', title: 'Paste a confirmation', confirm: 'Read', st,
    body: () => `<div class="section"><div class="group"><div class="row"><textarea class="notes" data-act="bkfield" data-f="text" rows="8"
      placeholder="Paste the confirmation email or itinerary here" aria-label="Confirmation text">${esc(st.text)}</textarea></div></div>
      <div class="section-f">You can paste more than one booking at once. Names and card details aren’t needed; leave them out if you like.</div></div>`,
    async ok() {
      if (!st.text.trim()) { toast('Paste the confirmation first', true); return; }
      await readBookings(trip, { text: st.text.trim() });
    },
  });
}

async function readBookings(trip, { text = null, images = [] }) {
  openSheet({ type: 'form', title: 'Reading your confirmation', busy: true, st: {},
    body: () => '<div class="section"><div class="section-f">Claude is reading it. This takes a few seconds.</div></div>' });
  try {
    const drafts = await api(`/v1/trips/${trip.id}/bookings/read`, { method: 'POST', body: { text, images } });
    closeSheet();
    if (!drafts.length) { toast('No bookings found there. You can enter it yourself.', true); return; }
    S.bkflow = { tripId: trip.id, drafts, i: 0, source: images.length ? 'screenshot' : 'text' };
    nextDraft();
  } catch (e) {
    closeSheet();
    toast(e.message, true);
  }
}

function nextDraft() {
  const f = S.bkflow;
  if (!f || f.i >= f.drafts.length) { S.bkflow = null; return; }
  bookingForm(S.trip[f.tripId], { ...f.drafts[f.i], source: f.source }, { step: f.drafts.length > 1 ? `${f.i + 1} of ${f.drafts.length}` : null, flow: true });
}

const KIND_LABELS = { flight: 'Flight', hotel: 'Hotel', reservation: 'Table reservation', car: 'Car rental', other: 'Other' };
const FORM_FIELDS = {
  flight: { title: ['Flight number', 'BA 178'], origin: ['From', 'JFK'], destination: ['To', 'LHR'], start_at: ['Departs', 'datetime-local'], end_at: ['Arrives', 'datetime-local'] },
  hotel: { title: ['Hotel', 'The Hoxton'], address: ['Address', ''], start_at: ['Check-in', 'datetime-local'], end_at: ['Check-out', 'date'] },
  reservation: { title: ['Restaurant or venue', ''], start_at: ['Date and time', 'datetime-local'], party_size: ['Guests', 'number'], address: ['Address', ''] },
  car: { title: ['Rental company', 'Hertz'], origin: ['Pick-up location', ''], destination: ['Drop-off location', ''], start_at: ['Pick-up', 'datetime-local'], end_at: ['Drop-off', 'datetime-local'] },
  other: { title: ['What is it?', 'Train, tour, event…'], start_at: ['When', 'datetime-local'], end_at: ['Until', 'datetime-local'], address: ['Where', ''] },
};

/** Add or edit one booking. `initial` can be a draft Claude read, or a saved booking when `id` is given. */
function bookingForm(trip, initial = {}, { id = null, title = null, step = null, flow = false } = {}) {
  const st = { ...Object.fromEntries(BOOKING_FIELDS.map((f) => [f, null])), kind: 'flight', source: 'manual', place_id: null, ...initial };
  openSheet({
    type: 'form', title: title || (id ? 'Edit booking' : step ? `Check booking (${step})` : 'Add a booking'), confirm: 'Save', st,
    body: () => {
      const spec = FORM_FIELDS[st.kind] || FORM_FIELDS.other;
      const input = (f, [label, hint]) => {
        const isDate = ['date', 'datetime-local', 'number'].includes(hint);
        const type = hint === 'datetime-local' && st[f] && !st[f].includes('T') ? 'date' : hint;
        const value = type === 'date' && st[f] ? st[f].slice(0, 10) : (st[f] ?? '');
        return `<div class="row"><label class="main"><span class="s">${label}</span>
          <input class="field" type="${isDate ? type : 'text'}" data-act="bkfield" data-f="${f}" value="${esc(value)}" ${isDate ? (type === 'number' ? 'min="1" max="100" inputmode="numeric"' : '') : `placeholder="${esc(hint)}"`} autocomplete="off"></label></div>`;
      };
      return `<div class="section"><div class="group">
        <div class="row"><label class="main"><span class="s">Type</span><select class="select wideselect" data-act="bkfield" data-f="kind">
          ${Object.entries(KIND_LABELS).map(([k, l]) => `<option value="${k}" ${st.kind === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>
        ${Object.entries(spec).map(([f, def]) => input(f, def)).join('')}
        ${input('confirmation', ['Confirmation number', ''])}${input('notes', ['Notes', 'Terminal, seat, room type…'])}</div>
        ${flow ? `<div class="section-f">Check what was read against your confirmation. Anything it couldn’t find is left blank.</div>
          <div class="section"><button class="btn tint wide" data-act="bkskip">Skip this one</button></div>` : ''}</div>`;
    },
    async ok() {
      const name = (st.title || '').trim();
      if (!name) { toast('Add a name for this booking', true); return; }
      S.sheet.busy = true; renderOverlay();
      try {
        const body = Object.fromEntries(BOOKING_FIELDS.map((f) => [f, typeof st[f] === 'string' ? (st[f].trim() || null) : (st[f] ?? null)]));
        let res;
        if (id) {
          res = await api(`/v1/trips/${trip.id}/bookings/${id}`, { method: 'PATCH', body });
        } else {
          const create = { source: st.source };
          Object.entries(body).forEach(([k, v]) => { if (v !== null) create[k] = v; });
          if (st.kind === 'reservation' && st.place_id) create.place_id = st.place_id;
          res = await api(`/v1/trips/${trip.id}/bookings`, { method: 'POST', body: create });
        }
        syncTrip(res);
        closeSheet();
        toast(id ? 'Booking updated' : 'Booking saved');
        render();
        if (flow && S.bkflow) { S.bkflow.i += 1; nextDraft(); }
      } catch (e) {
        S.sheet.busy = false; renderOverlay();
        toast(e.message, true);
      }
    },
  });
}

/** Bookings for a table at a place show on its page: the booking itself, or a Reserve link. */
function reservationSection(p, trip) {
  const booking = (trip.bookings || []).find((b) => b.place_id === p.id && b.kind === 'reservation');
  const link = safeUrl(p.reserve_url);
  const provider = esc(p.reserve_provider || 'the restaurant');
  if (booking) {
    const s = parseWhen(booking.start_at);
    return `<div class="section"><div class="section-h">Reservation</div><div class="group tiles">
      <button class="row" data-act="bookingmenu" data-id="${booking.id}">${tile('green', 'done')}<span class="main"><span class="t">${esc([s ? fmtDay(s.day) : '', s && s.time ? fmtClock(s.time) : ''].filter(Boolean).join(' · ') || 'Booked')}</span>
        <span class="s">${esc([booking.party_size ? `Table for ${booking.party_size}` : '', booking.confirmation ? `Confirmation ${booking.confirmation}` : ''].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</button>
      ${link ? `<a class="row" href="${esc(link)}" target="_blank" rel="noopener" data-act="link">${tile('gray', 'link')}<span class="main"><span class="t link">Change or cancel on ${provider}</span></span>${ICON.chev}</a>` : ''}</div></div>`;
  }
  const chatgpt = `<button class="row" data-act="chatgptbook" data-id="${p.id}">${tile('green', 'sparkle')}<span class="main"><span class="t">Book with ChatGPT</span><span class="s">Opens ChatGPT with the details filled in</span></span>${ICON.chev}</button>`;
  if (!MENU_CATS.has(p.category)) return '';
  if (!link) return `<div class="section"><div class="section-h">Reservation</div><div class="group tiles">${chatgpt}</div></div>`;
  return `<div class="section"><div class="section-h">Reservation</div><div class="group tiles">
    <a class="row" href="${esc(link)}" target="_blank" rel="noopener" data-reserve="${p.id}" data-act="link">${tile('gold', 'calendarPlus')}<span class="main"><span class="t">Reserve a table</span>
      <span class="s">Opens ${provider} in your browser</span></span><span class="brandchip">${provider}</span>${ICON.chev}</a>
    ${chatgpt}
    <button class="row" data-act="bookedplace" data-id="${p.id}">${tile('green', 'done')}<span class="main"><span class="t">I already booked</span><span class="s">Add the time and confirmation</span></span>${ICON.chev}</button></div>
    <div class="section-f">The Travel Edit can’t see availability. It takes you to the restaurant’s own booking page, then asks whether you booked so it can save the time.</div></div>`;
}

const RESERVE_KEY = 'tripit.reserve';
function noteReserveClick(placeId) {
  try { localStorage.setItem(RESERVE_KEY, JSON.stringify({ placeId, at: Date.now() })); } catch { /* private mode */ }
}
/** Back from a booking page: ask whether it was booked, so the time can be saved. */
function checkReservePending() {
  let pending = null;
  try { pending = JSON.parse(localStorage.getItem(RESERVE_KEY) || 'null'); } catch { /* ignore */ }
  if (!pending || S.sheet) return;
  const age = Date.now() - pending.at;
  if (age < 4000) return; // still leaving the app
  try { localStorage.removeItem(RESERVE_KEY); } catch { /* ignore */ }
  if (age > 6 * 3600 * 1000) return;
  const p = findAnyPlace(pending.placeId);
  const trip = p && (S.trip[p.trip_id] || (p.trip_ids && p.trip_ids.length === 1 ? S.trip[p.trip_ids[0]] : null));
  if (!p || !trip || (trip.bookings || []).some((b) => b.place_id === p.id && b.kind === 'reservation')) return;
  bookingForm(trip, { kind: 'reservation', title: p.name, place_id: p.id, source: 'reserve', address: p.address || null },
    { title: `Did you book ${p.name}?` });
}

// ---------- Packing list ----------

const PACK_GROUPS = [['clothes', 'Clothes'], ['shoes', 'Shoes & accessories'], ['toiletries', 'Toiletries & health'], ['tech', 'Tech & power'],
  ['documents', 'Documents & money'], ['daybag', 'Day bag'], ['other', 'Other']];
const useFahrenheit = /^en-US/i.test(navigator.language || '');
const fmtTemp = (c) => `${Math.round(useFahrenheit ? (c * 9) / 5 + 32 : c)}°`;
const dayList = (days) => (days.length > 3 ? `Days ${days[0]}–${days[days.length - 1]}` : `Day${days.length > 1 ? 's' : ''} ${days.join(', ')}`);

function weatherStrip(list) {
  if (!list.weather.length) return '';
  const typical = list.weather.every((w) => w.source === 'typical');
  return `<div class="section"><div class="section-h">${ICON.sun}Weather</div><div class="wxstrip">${list.weather.map((w) => `<div class="wx">
      <span class="d">${w.date ? esc(fmtDay(parseWhen(w.date).day)) : `Day ${w.day}`}</span><span class="t">${fmtTemp(w.temp_max)} / ${fmtTemp(w.temp_min)}</span>
      <span class="s">${esc(w.summary)}${w.rain_chance != null ? ` · ${w.rain_chance}%` : ''}</span></div>`).join('')}</div>
    <div class="section-f">${typical ? 'Too far ahead for a forecast, so these are last year’s conditions for the same dates.' : 'Forecast. It can change, so check again before you pack.'}</div></div>`;
}

function packItem(i) {
  return `<div class="row prow"><button class="pitem${i.packed ? ' picked' : ''}" data-act="packtick" data-id="${i.id}" aria-pressed="${i.packed}">
      <span class="check" aria-hidden="true">${i.packed ? ICON.done : ''}</span>
      <span class="main"><span class="t ${i.packed ? 'strike' : ''}">${esc(i.text)}</span>
        ${i.reason || i.days.length ? `<span class="s">${esc(i.reason || '')}${i.days.length ? `<span class="daychip">${esc(dayList(i.days))}</span>` : ''}</span>` : ''}</span></button>
    <button class="starbtn" data-act="packmenu" data-id="${i.id}" aria-label="Options for ${esc(i.text)}">${ICON.more}</button></div>`;
}

async function packingView(trip) {
  if (S.packing[trip.id] === undefined) {
    try { S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing`); } catch (e) { return `<div class="error" role="alert">${esc(e.message)}</div>`; }
  }
  const list = S.packing[trip.id];
  if (S.packBusy[trip.id]) {
    return `<div class="empty"><span class="spinner big"></span><h3>Packing for ${esc(trip.city || trip.name)}</h3>
      <p>Looking at your days, the weather and your taste. This can take up to a minute.</p></div>`;
  }
  if (!list) {
    return emptyState('teal', 'bag', 'A packing list for this trip',
      `Built from your ${trip.day_count ? plural(trip.day_count, 'planned day') : 'saved places'}${trip.start_date ? ', the weather on your dates' : ''} and your taste, with a reason for what’s on it. Not a list you could write in a notes app.`,
      `<button class="btn" data-act="makepacking" data-id="${trip.id}">${ICON.sparkle}Make my list</button>
       ${trip.start_date ? '' : '<div class="section-f">Add a start date to your trip and it will use the weather too.</div>'}`);
  }
  const packed = list.items.filter((i) => i.packed).length;
  const groups = PACK_GROUPS.map(([id, label]) => [id, label, list.items.filter((i) => i.group === id)]).filter(([, , items]) => items.length);
  return `<div class="planbar"><span class="planned-by">${list.generated_by === 'claude' ? `${ICON.sparkle}Made for this trip` : 'Basic list (Claude unavailable)'}</span>
      <span class="planlinks"><button class="linkbtn" data-act="makepacking" data-id="${trip.id}" data-again="1">Remake</button></span></div>
    <div class="homectl"><button class="pillbtn${list.carry_on_only ? ' on' : ''}" data-act="packcarry" data-id="${trip.id}" aria-pressed="${list.carry_on_only}">Carry-on only</button></div>
    ${list.notes ? `<div class="section"><div class="group"><div class="notecard">${esc(list.notes)}</div></div></div>` : ''}
    ${weatherStrip(list)}
    <div class="section"><div class="progress big" aria-label="${packed} of ${list.items.length} packed"><i style="width:${list.items.length ? Math.round((packed / list.items.length) * 100) : 0}%"></i></div>
      <div class="section-f">${packed} of ${list.items.length} packed</div></div>
    ${groups.map(([id, label, items]) => `<div class="section"><h2 class="section-title">${esc(label)}<span class="count">${items.length}</span></h2>
      <div class="group thumbs">${items.map(packItem).join('')}</div></div>`).join('')}
    <div class="section"><button class="btn tint wide" data-act="packadd" data-id="${trip.id}">${ICON.plus}Add an item</button>
      <div class="section-f">Back from the trip? Tap ••• on anything you didn’t use and it’s left off next time. Things you add stay when you remake the list.</div></div>`;
}

function packingCard(trip) {
  const list = S.packing[trip.id];
  const packed = list ? list.items.filter((i) => i.packed).length : 0;
  return `<div class="section"><a class="group tiles packcard" href="#/packing/${trip.id}"><span class="row">${tile('teal', 'bag')}<span class="main"><span class="t">Packing list</span>
    <span class="s">${list ? `${packed} of ${list.items.length} packed` : 'Made for this trip, with the weather'}</span></span>${ICON.chev}</span></a></div>`;
}

/** Today's bag: what to carry out for the day, from the trip's packing list. */
async function todayBag(trip, day) {
  try { S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing`); } catch { /* offline or none: use what we have */ }
  const list = S.packing[trip.id];
  if (!list) return '';
  const items = list.items.filter((i) => i.day_bag && (!i.days.length || i.days.includes(day)));
  if (!items.length) return '';
  return `<div class="section"><div class="section-h">${ICON.bag}Today’s bag</div><div class="group tiles">${items.map((i) => `<a class="row" href="#/packing/${trip.id}">
    <span class="main"><span class="t">${esc(i.text)}</span>${i.reason ? `<span class="s">${esc(i.reason)}</span>` : ''}</span></a>`).join('')}</div></div>`;
}

function packAddSheet(trip) {
  const st = { text: '', group: 'other' };
  openSheet({
    type: 'form', title: 'Add an item', confirm: 'Add', st,
    body: () => `<div class="section"><div class="group"><div class="row"><input class="field" data-act="packfield" data-f="text" placeholder="e.g. Camera charger" value="${esc(st.text)}" aria-label="Item" autocomplete="off"></div>
      <div class="row"><label class="main"><span class="s">Group</span><select class="select wideselect" data-act="packfield" data-f="group">
        ${PACK_GROUPS.map(([id, label]) => `<option value="${id}" ${st.group === id ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div></div></div>`,
    async ok() {
      if (!st.text.trim()) { toast('What should be on the list?', true); return; }
      S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing/items`, { method: 'POST', body: { text: st.text.trim(), group: st.group } });
      closeSheet();
      render();
    },
  });
}

async function makePacking(trip, body = {}) {
  S.packBusy[trip.id] = true;
  render();
  try {
    S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing`, { method: 'POST', body });
  } catch (e) {
    toast(e.message, true);
  } finally {
    delete S.packBusy[trip.id];
    render();
  }
}

// ---------- What's on: events during the trip ----------

const EVENT_FILTERS = [['all', 'All'], ['match', 'For you'], ['music', 'Music'], ['arts', 'Arts & theatre'], ['sports', 'Sports'], ['family', 'Family'], ['other', 'More']];
const fmtMoney = (n, cur) => { try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur || 'USD', maximumFractionDigits: 0 }).format(n); } catch { return `${Math.round(n)}`; } };
const eventPrice = (e) => (e.price_min != null ? (e.price_max && e.price_max > e.price_min ? `${fmtMoney(e.price_min, e.currency)} – ${fmtMoney(e.price_max, e.currency)}` : `From ${fmtMoney(e.price_min, e.currency)}`) : '');

function loadEvents(tripId, force = false) {
  if (!force && S.events[tripId] !== undefined) return;
  S.events[tripId] = null; // asked; the answer renders quietly when it arrives
  api(`/v1/trips/${tripId}/events`).then((ev) => { S.events[tripId] = ev; render({ quiet: true }); }).catch(() => { delete S.events[tripId]; });
}

/** A card on the trip page: how many events, and a way in. Hidden when the feature isn't set up or finds nothing. */
function eventsCard(trip) {
  const ev = S.events[trip.id];
  if (!ev || ev.status === 'disabled' || ev.status === 'error' || ev.status === 'no_location') return '';
  if (ev.status === 'no_dates') {
    return `<div class="section"><a class="group tiles packcard" href="#/events/${trip.id}"><span class="row">${tile('pink', 'ticket')}<span class="main"><span class="t">What’s on</span>
      <span class="s">Add dates to your trip to see events</span></span>${ICON.chev}</span></a></div>`;
  }
  if (!ev.events.length) return '';
  const mine = ev.events.filter((e) => e.match).length;
  return `<div class="section"><a class="group tiles packcard" href="#/events/${trip.id}"><span class="row">${tile('pink', 'ticket')}<span class="main"><span class="t">What’s on</span>
    <span class="s">${plural(ev.events.length, 'event')} during your trip${mine ? `, ${mine} picked for you` : ''}</span></span>${ICON.chev}</span></a></div>`;
}

function eventCard(e, trip) {
  const s = parseWhen(e.start_at);
  const onTrip = trip.places.some((p) => p.name.toLowerCase() === e.name.toLowerCase());
  const meta = [s && s.time ? fmtClock(s.time) : 'Time to be confirmed', e.venue].filter(Boolean).join(' · ');
  const flag = e.status === 'postponed' || e.status === 'rescheduled' ? `<span class="pill2 warnpill">${e.status === 'postponed' ? 'Postponed' : 'Rescheduled'}</span>` : '';
  return `<article class="evcard${e.match ? ' pick' : ''}">
    ${e.image ? `<img class="evimg" src="${esc(e.image)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()">` : ''}
    <div class="evbody"><div class="evtop"><span class="pill2">${esc(e.genre || { music: 'Music', arts: 'Arts & theatre', sports: 'Sports', family: 'Family', other: 'Event' }[e.category])}</span>${e.match ? '<span class="brandchip">For you</span>' : ''}${flag}</div>
      <h3 class="evname">${esc(e.name)}</h3>
      <div class="s">${esc(meta)}</div>
      ${e.why ? `<div class="daynote">${esc(e.why)}</div>` : ''}
      ${eventPrice(e) ? `<div class="s">${esc(eventPrice(e))}</div>` : ''}
      <div class="evactions"><a class="btn small" href="${esc(e.url)}" target="_blank" rel="noopener" data-act="link">Tickets</a>
        ${onTrip ? `<span class="s evon">${ICON.done}On your trip</span>` : `<button class="btn tint small" data-act="addevent" data-id="${e.id}" data-trip="${trip.id}">Add to Day ${e.day}</button>`}</div></div></article>`;
}

function eventsView(trip) {
  const ev = S.events[trip.id];
  if (ev === undefined || ev === null) {
    loadEvents(trip.id);
    return '<div class="empty"><span class="spinner big"></span><h3>Looking for events</h3><p>Checking what’s on near where you’re staying.</p></div>';
  }
  if (ev.status === 'disabled') return emptyState('gray', 'ticket', 'Events aren’t switched on', 'Add a free Ticketmaster key to the server to see concerts, theatre and sport during your trips. The README says how.');
  if (ev.status === 'no_dates') return emptyState('pink', 'ticket', 'Add dates to see what’s on', 'Set a start date for this trip (••• then Plan, or Re-plan) and The Travel Edit will look for events on those days.');
  if (ev.status === 'no_location') return emptyState('gray', 'pinslash', 'No places on the map yet', 'Save a few places so The Travel Edit knows where you’ll be, then it can look for events nearby.');
  if (ev.status === 'error') return emptyState('gray', 'warn', 'Couldn’t load events', 'Ticketmaster didn’t answer. Try again in a moment.', `<button class="btn tint" data-act="eventsrefresh" data-id="${trip.id}">Try again</button>`);
  const filter = S.eventFilter[trip.id] || 'all';
  const has = (id) => id === 'all' || ev.events.some((e) => (id === 'match' ? e.match : e.category === id));
  const shown = ev.events.filter((e) => filter === 'all' || (filter === 'match' ? e.match : e.category === filter)).sort((a, b) => a.start_at.localeCompare(b.start_at) || Number(b.match) - Number(a.match));
  const chips = `<div class="fchips" role="group" aria-label="Filter events">${EVENT_FILTERS.filter(([id]) => has(id)).map(([id, label]) =>
    `<button class="fchip${filter === id ? ' on' : ''}" data-act="eventfilter" data-trip="${trip.id}" data-f="${id}" aria-pressed="${filter === id}">${label}</button>`).join('')}</div>`;
  const groups = [];
  shown.forEach((e) => {
    const key = e.start_at.slice(0, 10);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(e); else groups.push({ key, items: [e] });
  });
  return `${ev.events.length ? chips : ''}
    ${groups.map((g) => `<div class="datehead">${esc(fmtDay(parseWhen(g.key).day))}${g.items[0].day ? ` · Day ${g.items[0].day}` : ''}</div>${g.items.map((e) => eventCard(e, trip)).join('')}`).join('')
      || emptyState('gray', 'ticket', ev.events.length ? 'Nothing in this filter' : 'Nothing found for these dates', ev.events.length ? 'Try another filter.' : 'Ticketmaster has no events near where you’ll be on these days. Coverage is best in North America and parts of Europe.')}
    <div class="section"><div class="section-f">Events and ticket links from Ticketmaster, which sells the tickets. The Travel Edit doesn’t sell or hold tickets, and prices and availability can change. Picked for you using your taste profile.</div>
      <button class="linkbtn" data-act="eventsrefresh" data-id="${trip.id}">Refresh</button></div>`;
}

/** Tonight's events for the Today view (evening ones, the ones picked for you first). */
function tonightEvents(trip, day) {
  const ev = S.events[trip.id];
  if (ev === undefined) loadEvents(trip.id);
  if (!ev || ev.status !== 'ok') return '';
  const list = ev.events.filter((e) => e.day === day && (!parseWhen(e.start_at).time || parseWhen(e.start_at).time >= '16:00'))
    .sort((a, b) => Number(b.match) - Number(a.match)).slice(0, 3);
  if (!list.length) return '';
  return `<div class="section"><div class="section-h">${ICON.ticket}On nearby</div><div class="group tiles">${list.map((e) => `<a class="row" href="#/events/${trip.id}">
    <span class="main"><span class="t">${esc(e.name)}</span><span class="s">${esc([parseWhen(e.start_at).time ? fmtClock(parseWhen(e.start_at).time) : '', e.venue].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</a>`).join('')}</div></div>`;
}

// ---------- Booking ahead: which places need a reservation or tickets, and a ChatGPT handoff ----------

const NEED_LABEL = {
  reservation: { required: 'Reservation required', recommended: 'Book ahead' },
  tickets: { required: 'Tickets required', recommended: 'Book tickets ahead' },
};
const needChip = (p) => (p.booking_need && NEED_LABEL[p.booking_kind]
  ? `<span class="needchip ${p.booking_need}" title="${esc(p.booking_note || '')}">${NEED_LABEL[p.booking_kind][p.booking_need]}</span>` : '');

/** Asks the server (once per place) which places need a reservation or tickets, then repaints quietly. */
function ensureNeeds(tripIds) {
  tripIds.filter((id) => !S.needsTried[id]).slice(0, 2).forEach((id) => {
    S.needsTried[id] = true;
    api(`/v1/trips/${id}/booking-needs`, { method: 'POST' }).then((res) => { syncTrip(res); render({ quiet: true }); }).catch(() => { /* try again next visit */ });
  });
}

function dateOfPlace(trip, p) {
  if (!trip || !trip.start_date || !p.day_number) return p.event_date || '';
  const [y, m, d] = trip.start_date.split('-').map(Number);
  return isoDate(new Date(y, m - 1, d + p.day_number - 1));
}

/** "Book with ChatGPT": a message with the restaurant and the details filled in, opened in ChatGPT. */
function chatgptSheet(p, trip) {
  const st = { date: dateOfPlace(trip, p), time: p.start_time || '19:30', guests: 2, text: (S.profile && S.profile.notes) || '' };
  openSheet({
    type: 'form', title: 'Book with ChatGPT', confirm: 'Open ChatGPT', st,
    body: () => `<div class="section"><div class="group">
      <div class="row">${tile('red', 'calendar')}<label class="main"><span class="s">Date</span><input class="field" type="date" data-act="packfield" data-f="date" value="${esc(st.date)}"></label></div>
      <div class="row">${tile('indigo', 'clock')}<label class="main"><span class="s">Time</span><input class="field" type="time" data-act="packfield" data-f="time" value="${esc(st.time)}"></label></div>
      <div class="row">${tile('teal', 'trips')}<label class="main"><span class="s">Guests</span><input class="field" type="number" min="1" max="20" inputmode="numeric" data-act="packfield" data-f="guests" value="${esc(st.guests)}"></label></div>
      <div class="row">${tile('gray', 'note')}<label class="main"><span class="s">Anything else? (allergies, a special occasion, seating)</span><input class="field" data-act="packfield" data-f="text" placeholder="Optional" value="${esc(st.text)}" autocomplete="off"></label></div></div>
      <div class="section-f">This opens ChatGPT with a message about ${esc(p.name)} already written. ChatGPT can book through OpenTable, Resy and Yelp where it’s available, and you’ll need to be signed in to ChatGPT. It sends what’s shown here, plus the restaurant’s phone, website and map link.</div></div>`,
    ok() {
      const where = [p.address || [p.neighborhood, p.city].filter(Boolean).join(', ')].filter(Boolean).join('');
      const when = st.date ? ` on ${new Date(`${st.date}T12:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}${st.time ? ` at around ${fmtClock(st.time)}` : ''}` : (st.time ? ` at around ${fmtClock(st.time)} (please ask me which day)` : '');
      const extras = [p.phone && `Phone: ${p.phone}`, safeUrl(p.website) && `Website: ${p.website}`, `Map: ${mapsLinks(p, trip).google}`].filter(Boolean).join('\n');
      const prompt = `Please book a table for ${Number(st.guests) || 2} at ${p.name}${where ? ` (${where})` : ''}${when}.\n\nFind real availability on OpenTable, Resy or Yelp, show me the open times, and book the best one once I confirm. If nothing fits, suggest the closest times or similar places nearby.\n\n${extras}${st.text.trim() ? `\n\nNotes: ${st.text.trim()}` : ''}`.slice(0, 1500);
      noteReserveClick(p.id); // when you come back, TripIt asks whether you booked
      window.open(`https://chatgpt.com/?q=${encodeURIComponent(prompt)}`, '_blank', 'noopener');
      closeSheet();
    },
  });
}

/** Brings a trip's places into the caches after the itinerary changed on the server. */
function syncTrip(res) {
  S.trip[res.id] = res;
  if (S.bookingsAll && res.bookings) { // the Bookings tab, kept in step without a reload
    const mine = res.bookings.map((b) => ({ ...b, trip_name: res.name, trip_kind: res.kind }));
    S.bookingsAll = [...S.bookingsAll.filter((b) => b.trip_id !== res.id), ...mine]
      .sort((a, b) => (a.start_at || '9999').localeCompare(b.start_at || '9999'));
  }
  fetchedAt.cal = 0;
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
  const tripId = route().name === 'trip' ? route().id : selTripId();
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
  const lines = [`${trip.name} — saved with The Travel Edit`, ''];
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
    navigator.share({ title: t.name, text: `${t.name}: my trip on The Travel Edit`, url }).catch((e) => {
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
    if (!quiet) toast('Offline saving needs Travel Edit opened from the Home Screen or a recent browser', true);
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
  urls.push(`/v1/trips/${tripId}/packing`);
  if (!quiet) toast(`Saving ${trip.name} for offline…`);
  let failed = 0;
  for (let i = 0; i < urls.length; i += 6) {
    await Promise.all(urls.slice(i, i + 6).map((u) => fetch(u, u.startsWith('/v1/trips/') ? { headers: authHeaders() } : {})
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
      if (EMBED) {
        if (embedDepth > 0) history.back(); else toNative({ back: true });
        return;
      }
      if (S.navigations > 0) history.back();
      else go(el.dataset.fallback);
      return;
    }
    case 'reload': render(); return;
    case 'feedback':
      openSheet({
        type: 'form', title: 'Send feedback', confirm: 'Send', st: {},
        body: () => `<div class="section"><div class="group"><div class="row"><textarea class="notes" id="feedback-text" rows="6" maxlength="4000"
            placeholder="What's working, what's broken, what you wish it did…" aria-label="Your feedback"></textarea></div></div>
          <div class="section-f">Goes straight to the team with your email, so we can reply.</div></div>`,
        async ok() {
          const message = $('#feedback-text').value.trim();
          if (!message) { toast('Write a few words first', true); return; }
          S.sheet.busy = true; renderOverlay();
          try {
            await api('/v1/feedback', { method: 'POST', body: { message, screen: route().name, platform: EMBED ? 'ios-web' : 'web' } });
            closeSheet(); toast('Thanks! Your feedback was sent');
          } catch (e) { S.sheet.busy = false; renderOverlay(); toast(e.message, true); }
        },
      });
      return;
    case 'add': { if (EMBED) { toNative({ open: '#/add' }); return; } const r = route(); addSheet({ tripId: ['trip', 'today'].includes(r.name) ? r.id : '' }); return; }
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
        { label: t.day_count ? 'Re-plan with AI' : 'Plan with AI', run: () => planSheet(t) },
        { label: 'Add from your saved places', run: () => onAction('tripaddplaces', { dataset: { id: t.id } }) },
        { label: 'Search for a new place', run: () => addSheet({ tripId: t.id }) },
        ...(t.day_count ? [{ label: 'Suggest places for quiet days', run: () => onAction('tripsuggest', { dataset: { id: t.id } }) }] : []),
        { label: 'Add a booking', run: () => addBookingSheet(t) },
        { label: 'Packing list', run: () => go(`#/packing/${t.id}`) },
        { label: 'Save for offline', run: () => saveOffline(t.id) },
        { label: 'Rename', run: () => renameSheet(t) },
        { label: 'Edit route', run: () => routeSheet(t) },
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
    case 'curateall': {
      toast('Finding new picks for your trips. This takes about a minute.');
      await Promise.all(el.dataset.ids.split(',').filter(Boolean).map((id) => curate(id, true)));
      S.allEdits = null;
      render({ quiet: true });
      return;
    }
    case 'saveeditentry': {
      el.disabled = true;
      try {
        const place = await api(`/v1/trips/${el.dataset.trip}/edits/${el.dataset.edit}/entries/${el.dataset.id}/save`, { method: 'POST' });
        S.edits[el.dataset.trip] = await api(`/v1/trips/${el.dataset.trip}/edits`);
        await afterLibraryChange();
        toast(`Saved ${place.name} to your library`);
        if (route().name === 'editplace') { location.replace(`#/place/${place.id}`); return; }
      } catch (e) { el.disabled = false; toast(e.message, true); }
      render({ quiet: true });
      return;
    }
    case 'bookmarkedit': {
      el.disabled = true;
      try {
        const folder = await api(`/v1/trips/${el.dataset.trip}/edits/${el.dataset.id}/bookmark`, { method: 'POST' });
        S.edits[el.dataset.trip] = await api(`/v1/trips/${el.dataset.trip}/edits`);
        S.allEdits = null;
        await afterLibraryChange();
        toast(`Saved as “${folder.name}” in your Library`);
      } catch (e) { el.disabled = false; toast(e.message, true); }
      render({ quiet: true });
      return;
    }
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
      if (!S.taste) { render(); return; }
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
      leave('#/profile');
      return;
    case 'tastenext': {
      if (!S.taste) { render(); return; }
      if (S.taste.step < TASTE_STEPS.length - 1) { S.taste.step++; S.taste.dir = 1; render(); return; }
      const notes = $('#taste-notes');
      if (notes) S.taste.p.notes = notes.value.trim() || null;
      const { food, interests, pace, budget, mornings } = S.taste.p;
      S.profile = await api('/v1/profile', { method: 'PUT', body: { food: food || [], interests: interests || [], pace, budget, mornings, notes: S.taste.p.notes } });
      fetchedAt.profile = Date.now();
      S.taste = null;
      toast('Your taste is saved');
      leave('#/');
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
    case 'libcat': {
      const f = libFilter(el.dataset.scope);
      if (f.cats.has(el.dataset.cat)) f.cats.delete(el.dataset.cat); else f.cats.add(el.dataset.cat);
      render({ quiet: true });
      return;
    }
    case 'libstar': { const f = libFilter(el.dataset.scope); f.starred = !f.starred; render({ quiet: true }); return; }
    case 'libclear': { delete S.libf[el.dataset.scope]; render({ quiet: true }); return; }
    case 'libmore': libMoreSheet(el.dataset.scope); return;
    case 'libcity': {
      const { st } = S.sheet;
      if (st.cities.has(el.dataset.city)) st.cities.delete(el.dataset.city); else st.cities.add(el.dataset.city);
      renderOverlay();
      return;
    }
    case 'libunplanned': S.sheet.st.unplanned = el.checked; return;
    case 'newfolder':
      folderNameSheet({ onDone: async (name) => {
        const fo = await api('/v1/folders', { method: 'POST', body: { name } });
        closeSheet(); await afterLibraryChange();
        go(`#/folder/${fo.id}`);
      } });
      return;
    case 'folderadd': {
      const fid = el.dataset.id;
      pickSavedSheet({ title: 'Add to folder', exclude: new Set((S.places || []).filter((p) => p.folder_ids.includes(fid)).map((p) => p.id)),
        onDone: async (ids) => {
          await api(`/v1/folders/${fid}/places`, { method: 'POST', body: { place_ids: ids } });
          await afterLibraryChange(); toast(`Added ${plural(ids.length, 'place')}`); render();
        } });
      return;
    }
    case 'foldermenu': {
      const fo = (S.folders || []).find((x) => x.id === el.dataset.id);
      if (!fo) return;
      openSheet({ type: 'actions', title: fo.name, actions: [
        { label: 'Add places', run: () => onAction('folderadd', el) },
        { label: 'Plan a trip from this folder', run: () => newTripSheet({ folderId: fo.id }) },
        { label: 'Rename', run: () => folderNameSheet({ title: 'Rename folder', name: fo.name, confirm: 'Save', onDone: async (name) => {
          await api(`/v1/folders/${fo.id}`, { method: 'PATCH', body: { name } });
          closeSheet(); await afterLibraryChange(); render();
        } }) },
        { label: 'Delete folder', destructive: true, run: () => openSheet({ type: 'actions', title: `Delete “${fo.name}”? Its places stay saved.`, actions: [
          { label: 'Delete folder', destructive: true, run: async () => {
            await api(`/v1/folders/${fo.id}`, { method: 'DELETE' });
            await afterLibraryChange(); toast('List deleted'); go('#/library');
          } }] }) },
      ] });
      return;
    }
    case 'newtrip': newTripSheet({ folderId: el.dataset.folder || null }); return;
    case 'citytrip': {
      const k = cityKey(el.dataset.city);
      newTripSheet({ placeIds: savedOnly(S.places || []).filter((p) => p.city && cityKey(p.city) === k).map((p) => p.id) });
      return;
    }
    case 'dinnergap': {
      const { trip: tripId, day } = el.dataset;
      const ids = el.dataset.ids.split(',');
      openSheet({ type: 'actions', title: 'Dinner tonight', actions: ids.map((id) => {
        const p = (S.places || []).find((x) => x.id === id);
        return { label: p ? p.name : id, run: async () => {
          const t = S.trip[tripId];
          if (!t.places.some((x) => x.id === id)) syncTrip(await api(`/v1/trips/${tripId}/places`, { method: 'POST', body: { place_ids: [id] } }));
          syncTrip(await api(`/v1/trips/${tripId}/add-to-day`, { method: 'POST', body: { place_ids: [id], day: Number(day) } }));
          await api(`/v1/places/${id}`, { method: 'PATCH', body: { time_of_day: 'dinner', trip_id: tripId } });
          await loadTrip(tripId);
          toast(`${p ? p.name : 'Place'} added for dinner`);
          render({ quiet: true });
        } };
      }) });
      return;
    }
    case 'routeadd': { const st = S.sheet.st; readRoute(st); st.stops.push({ city: '', days: 2, travel_mode: 'train', travel_minutes: null, travel_note: '' }); renderOverlay(); return; }
    case 'routedel': { const st = S.sheet.st; readRoute(st); st.stops.splice(Number(el.dataset.i), 1); renderOverlay(); return; }
    case 'settheme': try { localStorage.setItem(THEME_KEY, el.dataset.v); } catch { /* this visit only */ } applyTheme(); render({ quiet: true }); return;
    case 'visit': try { localStorage.setItem('tripit.visit', el.dataset.v); } catch { /* per-visit only */ } render({ quiet: true }); return;
    case 'allcities': S.allCities = !S.allCities; redrawLibMain(); return;
    case 'shuffle': S.shuffle = (S.shuffle || 0) + 1; render({ quiet: true }); return;
    case 'planweekend': {
      const ids = el.dataset.ids.split(',').filter(Boolean);
      const folders = S.folders || await loadFolders();
      let fo = folders.find((f) => f.name.toLowerCase() === 'this weekend');
      if (fo) await api(`/v1/folders/${fo.id}/places`, { method: 'POST', body: { place_ids: ids } });
      else fo = await api('/v1/folders', { method: 'POST', body: { name: 'This weekend', place_ids: ids } });
      await afterLibraryChange();
      go(`#/folder/${fo.id}`);
      return;
    }
    case 'ntcity': S.sheet.st.city = el.dataset.city; renderOverlay(); return;
    case 'ntdays': { const { st } = S.sheet; st.days = Math.max(1, Math.min(21, st.days + Number(el.dataset.d))); renderOverlay(); return; }
    case 'ntmode': { const { st } = S.sheet; st.mode = el.dataset.m; st.step = 3; S.sheet.confirm = 'Create trip'; renderOverlay(); return; }
    case 'ntfill': S.sheet.st.fill = el.checked; return;
    case 'ntback': { const { st } = S.sheet; st.step -= 1; S.sheet.confirm = st.step === 2 ? null : 'Next'; renderOverlay(); return; }
    case 'pkfolder': S.sheet.st.folder = el.dataset.f; renderOverlay(); return;
    case 'seladdfolder': await addToFolderSheet([...S.sel.picked]); return;
    case 'seladdtrip': await addToTripSheet([...S.sel.picked]); return;
    case 'selremovefolder': {
      const ids = [...S.sel.picked];
      for (const id of ids) await api(`/v1/folders/${el.dataset.id}/places/${id}`, { method: 'DELETE' });
      await afterLibraryChange(); resetSel(); toast(`Removed ${plural(ids.length, 'place')} from the folder`); render();
      return;
    }
    case 'selremovetrip': {
      const tripId = route().id;
      const ids = [...S.sel.picked];
      let res;
      for (const id of ids) res = await api(`/v1/trips/${tripId}/places/${id}`, { method: 'DELETE' });
      if (res) syncTrip(res);
      await afterLibraryChange(); resetSel(); toast(`Removed ${plural(ids.length, 'place')} from the trip. They’re still saved.`); render();
      return;
    }
    case 'tripaddplaces': {
      const trip = S.trip[el.dataset.id];
      pickSavedSheet({ title: `Add to ${trip.name}`, exclude: new Set(trip.places.map((p) => p.id)), onDone: async (ids) => {
        syncTrip(await api(`/v1/trips/${trip.id}/places`, { method: 'POST', body: { place_ids: ids } }));
        await afterLibraryChange(); toast(`Added ${plural(ids.length, 'place')}`); render();
      } });
      return;
    }
    case 'keepsugg':
      syncTrip(await api(`/v1/trips/${el.dataset.trip}/places/${el.dataset.id}/keep`, { method: 'POST' }));
      await afterLibraryChange(); toast('Kept, and added to your saved places'); render();
      return;
    case 'dropsugg':
      syncTrip(await api(`/v1/trips/${el.dataset.trip}/places/${el.dataset.id}`, { method: 'DELETE' }));
      toast('Suggestion removed'); render();
      return;
    case 'tripsuggest': {
      toast('Looking for places to fill quiet days…');
      const res = await api(`/v1/trips/${el.dataset.id}/suggest`, { method: 'POST' });
      const before = (S.trip[res.id].places || []).filter((p) => p.suggested).length;
      syncTrip(res);
      const n = res.places.filter((p) => p.suggested).length - before;
      toast(n > 0 ? `Added ${plural(n, 'suggestion')}` : 'No quiet days to fill');
      render();
      return;
    }
    case 'placefolders': await placeFoldersSheet(el.dataset.id); return;
    case 'placetrips': await placeTripsSheet(el.dataset.id); return;
    case 'removefromtrip': {
      const { trip: tripId, id } = el.dataset;
      syncTrip(await api(`/v1/trips/${tripId}/places/${id}`, { method: 'DELETE' }));
      await afterLibraryChange(); toast('Removed from the trip. It’s still saved.'); go(`#/trip/${tripId}`);
      return;
    }
    case 'pfnew':
      folderNameSheet({ onDone: async (name) => {
        await api('/v1/folders', { method: 'POST', body: { name, place_ids: [el.dataset.id] } });
        closeSheet(); await afterLibraryChange(); toast(`Saved to ${name}`); render();
      } });
      return;
    case 'pffolder': {
      const { st } = S.sheet;
      const on = !st.inside.has(el.dataset.f);
      await api(`/v1/folders/${el.dataset.f}/places${on ? '' : `/${st.place}`}`, on ? { method: 'POST', body: { place_ids: [st.place] } } : { method: 'DELETE' });
      if (on) st.inside.add(el.dataset.f); else st.inside.delete(el.dataset.f);
      afterLibraryChange().then(() => render({ quiet: true }));
      renderOverlay();
      return;
    }
    case 'disckind': S.disc.kind = el.dataset.kind; render(); return;
    case 'discrefresh': loadDiscover(true); render({ quiet: true }); return;
    case 'discarea': {
      const trips = (S.trips || []).filter((t) => t.kind !== 'local' && t.place_count);
      const mark = (on) => (on ? '✓ ' : '');
      openSheet({ type: 'actions', title: 'Look near', actions: [
        { label: `${mark(S.disc.area === 'here')}My location`, run: () => { S.disc.area = 'here'; S.disc.picked = true; render(); } },
        ...(S.homeCity ? [{ label: `${mark(S.disc.area === 'home')}${S.homeCity.city} (home)`, run: () => { S.disc.area = 'home'; S.disc.picked = true; render(); } }] : []),
        ...trips.map((t) => ({ label: `${mark(S.disc.area === 'trip' && S.disc.tripId === t.id)}${t.name}`, run: () => { S.disc.area = 'trip'; S.disc.tripId = t.id; S.disc.picked = true; render(); } })),
      ] });
      return;
    }
    case 'discsave': {
      const res = S.disc.data[discKey()];
      const it = res && res.items.find((x) => x.id === el.dataset.id);
      if (!it || it.saved) return;
      el.disabled = true;
      try {
        const out = await api('/v1/places', { method: 'POST', body: { candidate_id: it.id, trip_id: S.disc.area === 'trip' ? S.disc.tripId : null } });
        it.saved = true;
        fetchedAt.trips = 0; S.places = null;
        toast(out.created ? `Saved ${out.place.name}` : `${out.place.name} was already saved`);
      } catch (e) { toast(e.message, true); }
      render({ quiet: true });
      return;
    }
    case 'homecity': {
      const st = { city: S.homeCity ? S.homeCity.city : '' };
      openSheet({
        type: 'form', title: 'Home city', confirm: 'Save', st,
        body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="home-city" value="${esc(st.city)}" placeholder="e.g. Brooklyn, NY" maxlength="120" autocomplete="off" aria-label="Home city"></div></div>
          <div class="section-f">Discover looks for recommendations here first.</div></div>
          ${S.homeCity ? '<div class="section"><div class="group"><button class="row" data-act="homeclear2"><span class="main"><span class="t" style="color:var(--warn)">Remove home city</span></span></button></div></div>' : ''}`,
        async ok() {
          const city = $('#home-city').value.trim();
          if (!city) return;
          S.homeCity = await api('/v1/home', { method: 'PUT', body: { city } });
          S.disc.data = {};
          closeSheet(); toast(`Home is ${S.homeCity.city}`); render();
        },
      });
      return;
    }
    case 'homeclear2':
      await api('/v1/home', { method: 'DELETE' });
      S.homeCity = null; S.disc.data = {};
      closeSheet(); render();
      return;
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
      const cta = overlay.querySelector('.stickycta .btn');
      if (cta && st.step === 3) {
        const n = st.picked.size;
        cta.innerHTML = `${st.mode === 'ai' ? `${ICON.sparkle}Plan my trip` : 'Create trip'}${n ? ` · ${plural(n, 'place')}` : ''}`;
        const head = overlay.querySelector('.section-h.pad');
        if (head) head.textContent = `${n ? `${plural(n, 'place')} picked` : 'Pick places to include'}${st.city ? ` · ${st.city}` : ''}`;
      }
      return;
    }
    case 'tidy': tidySheet(S.trip[el.dataset.id]); return;
    case 'chatgptbook': { const p = findAnyPlace(el.dataset.id) || (placeDetail[el.dataset.id] || {}).place; chatgptSheet(p, S.trip[p.trip_id] || null); return; }
    case 'eventfilter': S.eventFilter[el.dataset.trip] = el.dataset.f; render(); return;
    case 'eventsrefresh': {
      const id = el.dataset.id;
      S.events[id] = null; render();
      try { S.events[id] = await api(`/v1/trips/${id}/events/refresh`, { method: 'POST' }); } catch (e) { delete S.events[id]; toast(e.message, true); }
      render();
      return;
    }
    case 'addevent': {
      const trip = S.trip[el.dataset.trip];
      const ev = S.events[trip.id].events.find((x) => x.id === el.dataset.id);
      syncTrip(await api(`/v1/trips/${trip.id}/events/${ev.id}/add`, { method: 'POST' }));
      toast(`Added to Day ${ev.day}`);
      render();
      return;
    }
    case 'makepacking': await makePacking(S.trip[el.dataset.id]); return;
    case 'packcarry': {
      const trip = S.trip[el.dataset.id];
      await makePacking(trip, { carry_on_only: !(S.packing[trip.id] && S.packing[trip.id].carry_on_only) });
      return;
    }
    case 'packadd': packAddSheet(S.trip[el.dataset.id]); return;
    case 'packfield': S.sheet.st[el.dataset.f] = el.value; return;
    case 'packtick': {
      const trip = Object.values(S.trip).find((t) => S.packing[t.id] && S.packing[t.id].items.some((i) => i.id === el.dataset.id));
      const item = trip && S.packing[trip.id].items.find((i) => i.id === el.dataset.id);
      if (!item) return;
      item.packed = !item.packed; // instant; the server catches up
      render({ quiet: true });
      try {
        S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing/items/${item.id}`, { method: 'PATCH', body: { packed: item.packed } });
      } catch (e) { item.packed = !item.packed; toast(e.message, true); }
      render({ quiet: true });
      return;
    }
    case 'packmenu': {
      const trip = Object.values(S.trip).find((t) => S.packing[t.id] && S.packing[t.id].items.some((i) => i.id === el.dataset.id));
      const item = trip && S.packing[trip.id].items.find((i) => i.id === el.dataset.id);
      if (!item) return;
      const patch = async (body, message) => { S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing/items/${item.id}`, { method: 'PATCH', body }); if (message) toast(message); render(); };
      openSheet({ type: 'actions', title: item.text, actions: [
        { label: item.unused ? 'I did use this' : 'I didn’t use this', run: () => patch({ unused: !item.unused }, item.unused ? 'Noted' : 'Noted. It’s left off next time') },
        { label: 'Delete', destructive: true, run: async () => { S.packing[trip.id] = await api(`/v1/trips/${trip.id}/packing/items/${item.id}`, { method: 'DELETE' }); render(); } },
      ] });
      return;
    }
    case 'link': return;
    case 'addbooking': addBookingSheet(S.trip[el.dataset.id]); return;
    case 'bkmanual': bookingForm(S.trip[el.dataset.id], {}, {}); return;
    case 'bktext': pasteBookingSheet(S.trip[el.dataset.id]); return;
    case 'bkshot': { const trip = S.trip[el.dataset.id]; closeSheet(); pickBookingShots(trip); return; }
    case 'bkfield': {
      const { st } = S.sheet;
      const f = el.dataset.f;
      st[f] = f === 'party_size' ? (el.value ? Number(el.value) : null) : el.value;
      if (f === 'kind') renderOverlay();
      return;
    }
    case 'bkskip': if (S.bkflow) { S.bkflow.i += 1; closeSheet(); nextDraft(); } return;
    case 'bookedplace': {
      const p = findAnyPlace(el.dataset.id) || (placeDetail[el.dataset.id] || {}).place;
      await withTripFor(p, (trip) => bookingForm(trip, { kind: 'reservation', title: p.name, place_id: p.id, source: 'manual', address: p.address || null }, { title: `Booked at ${p.name}` }));
      return;
    }
    case 'lounges': {
      const { trip, b } = await bookingWithTrip(el.dataset.id);
      if (b) loungeSheet(trip, b);
      return;
    }
    case 'calday': {
      const d = el.dataset.date;
      S.calv.day = S.calv.day === d ? null : d;
      S.calv.scrollTo = S.calv.day;
      render({ quiet: true });
      return;
    }
    case 'calmonth': {
      const [y, m] = S.calv.month.split('-').map(Number);
      const d = new Date(y, m - 1 + Number(el.dataset.step), 1);
      S.calv.month = isoDate(d).slice(0, 7); S.calv.day = null;
      render({ quiet: true });
      return;
    }
    case 'caltoday': S.calv.month = isoDate(new Date()).slice(0, 7); S.calv.day = null; render({ quiet: true }); return;
    case 'calnext': {
      const end = `${S.calv.month}-31`;
      const next = S.cal.items.find((i) => i.date > end && (S.calv.filter === 'all' || i.kind === S.calv.filter));
      if (next) { S.calv.month = next.date.slice(0, 7); S.calv.day = next.date; S.calv.scrollTo = next.date; render({ quiet: true }); }
      return;
    }
    case 'calfilter': S.calv.filter = el.dataset.f; render({ quiet: true }); return;
    case 'calopen': go(el.dataset.href); return;
    case 'calbooking': {
      const { trip, b } = await bookingWithTrip(el.dataset.id);
      if (b) openSheet({ type: 'actions', title: b.title, actions: bookingActions(trip, b) });
      return;
    }
    case 'caladd': { const it = calItem(el.dataset.id); if (it) addToCalendarSheet(it); return; }
    case 'calsync': await calSyncSheet(); return;
    case 'calfeedon': {
      S.sheet.busy = true; renderOverlay();
      try {
        const feed = await api('/v1/calendar/feed', { method: 'POST' });
        if (S.cal) S.cal.feed = feed;
        S.sheet.st.feed = feed;
      } catch (e) { toast(e.message, true); }
      if (S.sheet) { S.sheet.busy = false; renderOverlay(); }
      return;
    }
    case 'calfeedoff':
      await api('/v1/calendar/feed', { method: 'DELETE' });
      if (S.cal) S.cal.feed = null;
      closeSheet(); toast('Calendar link turned off. Subscribed calendars stop updating.');
      return;
    case 'eventdate': { const p = findAnyPlace(el.dataset.id); if (p) { if (S.sheet) closeSheet(); eventDateSheet(p); } return; }
    case 'eventdateclear': {
      const fresh = await api(`/v1/places/${el.dataset.id}`, { method: 'PATCH', body: { clear_event_date: true } });
      afterPlaceChange(fresh); closeSheet(); toast('Date removed'); render();
      return;
    }
    case 'eventcal': {
      const cal = await loadCal();
      const it = cal.items.find((i) => i.id === `event:${el.dataset.id}`);
      if (it) addToCalendarSheet(it);
      return;
    }
    case 'bkkind': S.bk.kind = el.dataset.k; render({ quiet: true }); return;
    case 'bkpast': S.bk.past = !S.bk.past; render({ quiet: true }); return;
    case 'bktrip': {
      const mark = (on) => (on ? '✓ ' : '');
      const trips = (S.trips || []).filter((t) => (S.bookingsAll || []).some((x) => x.trip_id === t.id));
      openSheet({ type: 'actions', title: 'Show bookings for', actions: [
        { label: `${mark(S.bk.trip === 'all')}All trips`, run: () => { S.bk.trip = 'all'; go('#/bookings'); } },
        ...trips.map((t) => ({ label: `${mark(S.bk.trip === t.id)}${t.name}`, run: () => { S.bk.trip = t.id; go(`#/bookings?trip=${t.id}`); } })),
      ] });
      return;
    }
    case 'addbookingany': {
      const trips = await cachedTrips();
      const pick = (S.bk.trip !== 'all' && trips.find((t) => t.id === S.bk.trip)) || likelyTrip(trips);
      if (!pick) { toast('Save a trip first, then add its bookings', true); return; }
      addBookingSheet(await loadTrip(pick.id), { choose: true });
      return;
    }
    case 'bookingmenu': {
      const { trip, b } = await bookingWithTrip(el.dataset.id);
      if (b) openSheet({ type: 'actions', title: b.title, actions: bookingActions(trip, b) });
      return;
    }
    case 'bktripsel': {
      await loadTrip(el.value);
      S.sheet.st.tripId = el.value;
      renderOverlay();
      return;
    }
    case 'findmenu': await runFindMenu(el.dataset.id, el.dataset.refresh === '1'); return;
    case 'menuupload': pickMenuFiles(el.dataset.id); return;
    case 'menuwebsite': {
      const p = findAnyPlace(el.dataset.id);
      const st = { text: p.website || '' };
      openSheet({
        type: 'form', title: 'Restaurant website', confirm: 'Find the menu', st,
        body: () => `<div class="section"><div class="group"><div class="row"><input class="field" type="url" inputmode="url" data-act="packfield" data-f="text" placeholder="https://…" value="${esc(st.text)}" aria-label="Website address" autocomplete="off"></div></div>
          <div class="section-f">Paste the address of the restaurant’s own website. The Travel Edit will look there for the menu.</div></div>`,
        async ok() {
          const url = st.text.trim();
          if (!url) { toast('Paste the website address', true); return; }
          S.sheet.busy = true; renderOverlay();
          try {
            const place = await api(`/v1/places/${p.id}`, { method: 'PATCH', body: { website: url } });
            updatePlaceEverywhere(place);
            delete S.menu[p.id];
            closeSheet();
            await runFindMenu(p.id, true);
          } catch (e) {
            S.sheet.busy = false; renderOverlay();
            toast(e.message, true);
          }
        },
      });
      return;
    }
    case 'menudiet': S.menuDiet[el.dataset.id] = S.menuDiet[el.dataset.id] === el.dataset.tag ? null : el.dataset.tag; render(); return;
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
        else if (state === 'denied') toast('Notifications are blocked. Allow them in Settings → Notifications → Travel Edit.', true);
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
      const place = allPlaces().find((x) => x.id === el.dataset.id) || (placeDetail[el.dataset.id] || {}).place;
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
    case 'pvisit': await patchPlace(el.dataset.id, { visited: el.dataset.v === '1' }); return;
    case 'shownote': (S.noteOpen ||= {})[el.dataset.id] = true; await render({ quiet: true }); const n = $('#notes'); if (n) n.focus(); return;
    case 'allhours': (S.allHours ||= {})[el.dataset.id] = !(S.allHours[el.dataset.id]); render({ quiet: true }); return;
    case 'slotday': case 'slottod': case 'slottime': {
      const v = el.value;
      const body = el.dataset.act === 'slotday' ? { day_number: Number(v) }
        : el.dataset.act === 'slottod' ? (v ? { time_of_day: v } : { clear_time_of_day: true })
          : (v ? { start_time: v } : { clear_start_time: true });
      const place = await api(`/v1/places/${el.dataset.id}`, { method: 'PATCH', body: { ...body, trip_id: el.dataset.trip } });
      updatePlaceEverywhere(place);
      await loadTrip(el.dataset.trip);
      render({ quiet: true });
      return;
    }
    case 'directionsmenu':
      openSheet({ type: 'actions', title: 'Directions', actions: [
        { label: 'Apple Maps', run: () => window.open(el.dataset.apple, '_blank', 'noopener') },
        { label: 'Google Maps', run: () => window.open(el.dataset.google, '_blank', 'noopener') },
      ] });
      return;
    case 'shareplace': {
      const place = (S.places || []).find((x) => x.id === el.dataset.id) || (placeDetail[el.dataset.id] && placeDetail[el.dataset.id].place) || findAnyPlace(el.dataset.id);
      const url = (place && safeUrl(place.maps_url)) || location.href;
      if (navigator.share) { try { await navigator.share({ title: place ? place.name : 'Place', url }); } catch { /* cancelled */ } } else await copy(url);
      return;
    }
    case 'placemore': {
      const id = el.dataset.id;
      const place = (S.places || []).find((x) => x.id === id) || (placeDetail[id] && placeDetail[id].place) || findAnyPlace(id);
      if (!place) return;
      const t = el.dataset.trip ? S.trip[el.dataset.trip] : null;
      const actions = [
        { label: place.must_do ? 'Remove star' : 'Star', run: async () => { await patchPlace(id, { must_do: !place.must_do }); toast(place.must_do ? 'Star removed' : 'Starred. It stays at the top of your lists'); } },
        { label: 'Add to a trip…', run: () => placeTripsSheet(id) },
        { label: 'Add to a list…', run: () => placeFoldersSheet(id) },
        { label: located(place) ? 'Wrong pin? Search again' : 'Find on the map', run: () => onAction('relocate', { dataset: { id } }) },
      ];
      if (t && !place.suggested) actions.push({ label: `Remove from ${t.name}`, destructive: true, run: () => onAction('removefromtrip', { dataset: { trip: t.id, id } }) });
      actions.push({ label: 'Delete place', destructive: true, run: () => onAction('askdeleteplace', { dataset: { id, trip: route().params.get('trip') || '' } }) });
      openSheet({ type: 'actions', title: place.name, actions });
      return;
    }
    case 'setday': await patchPlace(el.dataset.id, { day_number: Number(el.value) }); return;
    case 'settod': await patchPlace(el.dataset.id, el.value ? { time_of_day: el.value } : { clear_time_of_day: true }); return;
    case 'setcat': await patchPlace(el.dataset.id, { category: el.value }); return;
    case 'notes':
      clearTimeout(notesTimer);
      notesTimer = setTimeout(() => patchPlace(el.dataset.id, { user_notes: el.value }, false), 600);
      return;
    case 'relocate': {
      const place = allPlaces().find((p) => p.id === el.dataset.id) || (S.places || []).find((p) => p.id === el.dataset.id)
        || (placeDetail[el.dataset.id] && placeDetail[el.dataset.id].place);
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
        type: 'actions', title: 'Delete this place everywhere? It leaves your saved places, folders and trips.',
        actions: [{ label: 'Delete place', destructive: true, run: async () => {
          await api(`/v1/places/${el.dataset.id}`, { method: 'DELETE' });
          const t = S.trip[el.dataset.trip];
          if (t) t.places = t.places.filter((p) => p.id !== el.dataset.id);
          if (S.places) S.places = S.places.filter((p) => p.id !== el.dataset.id);
          fetchedAt.trips = 0;
          await afterLibraryChange();
          toast('Place deleted');
          go(el.dataset.trip ? `#/trip/${el.dataset.trip}` : '#/library');
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
    case 'changepw':
      openSheet({ type: 'form', title: 'Change password', confirm: 'Save', st: {},
        body: () => `<div class="section"><div class="group">
          <label class="row authrow" for="pw-cur"><span class="lbl">Current</span><input class="field" id="pw-cur" type="password" autocomplete="current-password"></label>
          <label class="row authrow" for="pw-new"><span class="lbl">New</span><input class="field" id="pw-new" type="password" autocomplete="new-password" placeholder="At least 8 characters"></label>
        </div></div>`,
        async ok() {
          try {
            await api('/v1/me/password', { method: 'POST', body: { current: $('#pw-cur').value, new: $('#pw-new').value } });
            closeSheet(); toast('Password changed');
          } catch (e) { toast(e.message, true); }
        } });
      return;
    case 'importkey': {
      const { key } = await api('/v1/me/import-key', { method: 'POST' });
      S.me = { ...S.me, has_import_key: true };
      openSheet({ type: 'form', title: 'Your Shortcut key', confirm: 'Done', st: {},
        body: () => `<div class="section"><div class="group"><div class="copyline"><code>${esc(key)}</code>
          <button class="copybtn" data-act="copy" data-value="${esc(key)}" aria-label="Copy key">Copy</button></div></div>
          <div class="section-f">Paste it as the X-API-Key header in your Travel Edit Shortcut. It's shown only now, and it can only send links and screenshots to your library.</div></div>`,
        ok() { closeSheet(); render({ quiet: true }); } });
      return;
    }
    case 'usagelimits': {
      const { config, limit_labels: labels } = S.usage;
      const field = (key, label, step) => `<label class="row authrow" for="lim-${key}"><span class="lbl">${esc(label)}</span>
        <input class="field" id="lim-${key}" type="number" inputmode="decimal" min="0" step="${step}" value="${config[key]}"></label>`;
      openSheet({ type: 'form', title: 'Budgets and limits', confirm: 'Save', st: {},
        body: () => `<div class="section"><div class="section-h">Budgets (US$)</div><div class="group tiles">
            ${field('monthly_budget_usd', 'Monthly, everyone', '1')}${field('user_daily_budget_usd', 'Daily, per person', '0.5')}</div>
            <div class="section-f">AI pauses for everyone once the month's spend reaches the monthly budget. You skip the per-person limits.</div></div>
          <div class="section"><div class="section-h">Per person, per day</div><div class="group tiles">
            ${Object.entries(labels).map(([k, label]) => field(`limit_${k}`, cap(label), '1')).join('')}</div>
            <div class="section-f">0 turns a limit off. Limits reset at midnight UTC.</div></div>`,
        async ok() {
          const body = {};
          for (const key of Object.keys(config)) {
            const v = parseFloat(($(`#lim-${key}`) || {}).value);
            if (Number.isFinite(v) && v >= 0) body[key] = v;
          }
          S.usage.config = await api('/v1/admin/usage/limits', { method: 'PUT', body });
          closeSheet(); render({ quiet: true });
        } });
      return;
    }
    case 'invites': {
      const st = { list: await api('/v1/admin/invites'), code: null };
      openSheet({ type: 'form', title: 'Invite people', confirm: 'Done', st,
        body: () => `<div class="section">${st.code ? `<div class="group"><div class="copyline"><code class="bigcode">${esc(st.code)}</code>
            <button class="copybtn" data-act="copy" data-value="${esc(st.code)}" aria-label="Copy code">Copy</button></div></div>
            <div class="section-f">Send this to one person. It works once, and it's only shown now.</div>` : ''}
          <div class="group tiles"><div class="row"><input class="field" id="invite-note" placeholder="Who it's for (optional)" maxlength="80"></div></div>
          <button class="btn wide" data-act="newinvite" style="margin-top:12px">${ICON.plus}Make an invite code</button></div>
          ${st.list.length ? `<div class="section"><div class="section-h">Codes</div><div class="group tiles">${st.list.map((i) => `<div class="row"><span class="main">
            <span class="t">…${esc(i.hint)}${i.note ? ` · ${esc(i.note)}` : ''}</span><span class="s">${i.used_by ? `Used by ${esc(i.used_by)}` : 'Not used yet'}</span></span>
            ${i.used_by ? '' : `<button class="linkbtn" data-act="delinvite" data-id="${i.id}">Cancel</button>`}</div>`).join('')}</div></div>` : ''}`,
        ok() { closeSheet(); } });
      return;
    }
    case 'newinvite': {
      const { st } = S.sheet;
      const { code } = await api('/v1/admin/invites', { method: 'POST', body: { note: ($('#invite-note') || {}).value || '' } });
      st.code = code; st.list = await api('/v1/admin/invites');
      renderOverlay();
      return;
    }
    case 'delinvite':
      await api(`/v1/admin/invites/${el.dataset.id}`, { method: 'DELETE' });
      S.sheet.st.list = await api('/v1/admin/invites'); renderOverlay();
      return;
    case 'people': {
      const st = { users: await api('/v1/admin/users'), temp: null };
      openSheet({ type: 'form', title: 'People', confirm: 'Done', st,
        body: () => `<div class="section">${st.temp ? `<div class="group"><div class="copyline"><code class="bigcode">${esc(st.temp.password)}</code>
            <button class="copybtn" data-act="copy" data-value="${esc(st.temp.password)}" aria-label="Copy password">Copy</button></div></div>
            <div class="section-f">A temporary password for ${esc(st.temp.email)}. They can change it in their Profile after signing in.</div>` : ''}
          <div class="group tiles">${st.users.map((u) => `<div class="row"><span class="main"><span class="t">${esc(u.email)}</span>
            <span class="s">${u.is_admin ? 'Owner' : `Joined ${esc(new Date(u.created_at).toLocaleDateString())}`}</span></span>
            ${u.is_admin ? '' : `<button class="linkbtn" data-act="resetpw" data-id="${u.id}" data-email="${esc(u.email)}">Reset password</button>`}</div>`).join('')}</div></div>`,
        ok() { closeSheet(); } });
      return;
    }
    case 'resetpw': {
      const { password } = await api(`/v1/admin/users/${el.dataset.id}/reset-password`, { method: 'POST' });
      S.sheet.st.temp = { email: el.dataset.email, password }; renderOverlay();
      return;
    }
    case 'deleteaccount':
      openSheet({ type: 'form', title: 'Delete account', confirm: 'Delete', st: {},
        body: () => `<div class="section"><div class="section-f">This removes your account and everything in it: saved places, folders, trips, bookings and photos. It can't be undone.</div>
          <div class="group"><label class="row authrow" for="del-pw"><span class="lbl">Password</span><input class="field" id="del-pw" type="password" autocomplete="current-password"></label></div></div>`,
        async ok() {
          try {
            await api('/v1/me', { method: 'DELETE', body: { password: $('#del-pw').value } });
            setKey(''); clearOfflineData(); location.hash = '#/signin'; location.reload();
          } catch (e) { toast(e.message, true); }
        } });
      return;
    case 'signout':
      await api('/v1/auth/logout', { method: 'POST' }).catch(() => {});
      setKey(''); S.config = null; S.me = undefined; clearOfflineData();
      location.hash = '#/signin'; location.reload();
      return;
    default:
  }
}

/** Day, time slot and exact time are per trip; star, notes and the rest belong to the place everywhere. */
const TRIP_FIELDS = ['trip_id', 'day_number', 'day_order', 'time_of_day', 'day_note', 'start_time', 'suggested', 'suggestion_note'];
function updatePlaceEverywhere(place) {
  const shared = Object.fromEntries(Object.entries(place).filter(([k]) => !TRIP_FIELDS.includes(k)));
  Object.values(S.trip).forEach((t) => {
    t.places = t.places.map((x) => (x.id !== place.id ? x : (place.trip_id === t.id ? place : { ...x, ...shared })));
  });
  if (S.places) S.places = S.places.map((x) => (x.id === place.id ? { ...x, ...shared } : x));
  if (placeDetail[place.id]) placeDetail[place.id].place = { ...placeDetail[place.id].place, ...shared };
}

async function patchPlace(id, body, rerender = true) {
  try {
    const ctx = contextTrip();
    if (ctx && ['day_number', 'time_of_day', 'start_time', 'clear_time_of_day', 'clear_start_time'].some((k) => k in body)) body = { ...body, trip_id: ctx };
    const place = await api(`/v1/places/${id}`, { method: 'PATCH', body });
    updatePlaceEverywhere(place);
    if ('day_number' in body && place.trip_id) await loadTrip(place.trip_id); // day count may have changed
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
    updatePlaceEverywhere(place);
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
  const reserve = ev.target.closest('a[data-reserve]');
  if (reserve) noteReserveClick(reserve.dataset.reserve);
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return;
  if (el.tagName === 'A' && el.dataset.act !== 'back') return;
  ev.preventDefault();
  onAction(el.dataset.act, el).catch((e) => { reportError(e, `Action ${el.dataset.act}`); toast(e.message || 'Something went wrong', true); });
});

document.addEventListener('change', (ev) => {
  const el = ev.target;
  if (el.dataset && el.dataset.act && ['INPUT', 'SELECT'].includes(el.tagName) && el.type !== 'text') {
    onAction(el.dataset.act, el).catch((e) => { reportError(e, `Action ${el.dataset.act}`); toast(e.message, true); });
  }
});

document.addEventListener('input', (ev) => {
  const el = ev.target;
  if (el.dataset && ['notes', 'prefs'].includes(el.dataset.act)) onAction(el.dataset.act, el);
  if (el.dataset && el.dataset.act === 'bkfield' && el.dataset.f !== 'kind' && S.sheet && S.sheet.st) onAction('bkfield', el);
  if (el.dataset && el.dataset.act === 'packfield' && S.sheet && S.sheet.st) onAction('packfield', el);
  if (el.dataset && el.dataset.act === 'addinput') addInputChanged(el.value);
  if (el.dataset && el.dataset.act === 'tastenotes' && S.taste) S.taste.p.notes = el.value;
  if (el.dataset && el.dataset.act === 'tidytext' && S.sheet && S.sheet.st) S.sheet.st.text = el.value;
  if (el.dataset && el.dataset.act === 'ntfield' && S.sheet && S.sheet.st) S.sheet.st[el.dataset.f] = el.value;
  if (el.dataset && el.dataset.act === 'libq') { libFilter(el.dataset.scope).q = el.value; redrawLibList(el.dataset.scope); }
  if (el.dataset && el.dataset.act === 'libsearch') { S.libq = el.value; redrawLibMain(); }
  if (el.dataset && el.dataset.act === 'pkq' && S.sheet && S.sheet.st) {
    S.sheet.st.q = el.value;
    const box = document.getElementById('pklist');
    if (box) { const tmp = document.createElement('div'); tmp.innerHTML = pickerBody(S.sheet.st); box.replaceWith(tmp.querySelector('#pklist')); hydrateIcons(overlay); }
  }
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
  } else if (form.dataset.form === 'signin' || form.dataset.form === 'signup') {
    const data = Object.fromEntries(new FormData(form));
    const err = $('#auth-error');
    const btn = form.querySelector('button[type=submit]');
    err.textContent = '';
    if (!String(data.email || '').includes('@')) { err.textContent = 'Enter your email address.'; return; }
    if (!data.password) { err.textContent = 'Enter your password.'; return; }
    btn.disabled = true;
    try {
      const path = form.dataset.form === 'signin' ? '/v1/auth/login' : '/v1/auth/signup';
      const res = await api(path, { method: 'POST', body: { email: data.email, password: data.password, invite: data.invite || '' } });
      setKey(''); // the session cookie replaces any key saved from before accounts
      S.me = res.user;
      S.config = await api('/v1/config');
      configureMaps({ googleMapsKey: S.config.google_maps_key });
      toast(form.dataset.form === 'signin' ? 'Signed in' : 'Welcome to The Travel Edit');
      await start();
    } catch (e) {
      btn.disabled = false;
      err.textContent = e.message;
    }
  }
});

document.addEventListener('keydown', (ev) => {
  if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.classList && ev.target.classList.contains('bcard')) {
    ev.preventDefault();
    onAction('bookingmenu', ev.target).catch((e) => { reportError(e, 'Action bookingmenu'); toast(e.message, true); });
    return;
  }
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
  if (document.visibilityState === 'visible' && route().name !== 'signin') { schedulePoll(true); setTimeout(checkReservePending, 800); }
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
  if (route().name === 'signin') location.hash = '#/';
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
    if (S.config === null) return;
    ['/v1/config', '/v1/trips', '/v1/jobs?limit=40', '/v1/places'].forEach((u) => fetch(u, { headers: authHeaders() }).catch(() => {}));
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
    if (e.status === 401) { location.hash = '#/signin'; render(); return; }
  }
  await start();
})();
