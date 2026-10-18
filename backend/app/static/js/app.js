import { api, ApiError, getKey, setKey } from './api.js';
import { ICON, hydrateIcons } from './icons.js';
import { dayHours, mondayIndex, openStatus, slotConflict } from './hours.js';
import { configureMaps, destroyMaps, mapProvider, renderMap } from './map.js';

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
  if (['map', 'imports', 'settings', 'setup', 'add'].includes(parts[0])) return { name: parts[0], params };
  return { name: 'trips', params };
}

const TAB_FOR = { trips: 'trips', trip: 'trips', place: 'trips', map: 'map', imports: 'imports', settings: 'settings', add: 'trips' };
const TAB_INDEX = { trips: 0, map: 1, imports: 2, settings: 3 };
const DEPTH = { trip: 1, place: 2 };
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

async function render({ quiet = false } = {}) {
  // Background refreshes never cancel a navigation that's still loading, or a field someone is typing in.
  if (quiet && (navigating || editing())) return;
  const r = route();
  const token = ++renderToken;
  const key = location.hash;
  if (!quiet) navigating = token;
  try {
    await paint(r, token, key, quiet);
  } finally {
    if (navigating === token) navigating = 0;
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
    tabbar.hidden = r.name === 'setup';
    const app = $('.app');
    app.classList.toggle('fullbleed', r.name === 'map' || (r.name === 'trip' && r.mode === 'map'));
    app.classList.toggle('notabs', r.name === 'setup');

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
  };

  lastKey = key;
  lastRoute = r;
  lastHtml = html;
  if (kind !== 'none' && document.startViewTransition && !reducedMotion.matches) {
    const root = document.documentElement;
    root.dataset.vt = kind;
    const vt = document.startViewTransition(swap);
    vt.finished.finally(() => { if (root.dataset.vt === kind) delete root.dataset.vt; });
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

window.addEventListener('hashchange', () => { S.navigations++; S.editDay = false; render(); });

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
  if (s.includes('tiktok')) return 'tiktok';
  if (s.includes('instagram')) return 'instagram';
  if (s.includes('youtu')) return 'youtube';
  return 'link';
}
const PLATFORM_NAMES = { tiktok: 'TikTok', instagram: 'Instagram', youtube: 'YouTube' };
const platformName = (p) => PLATFORM_NAMES[String(p || '').toLowerCase()] || cap(p);
function platformTile(platform, cls = '') {
  if (platform === 'tiktok') return `<span class="tile tt ${cls}">${ICON.note}</span>`;
  if (platform === 'instagram') return `<span class="tile ig ${cls}">${ICON.camera}</span>`;
  if (platform === 'youtube') return `<span class="tile ${cls}" style="--pc:#FF0033">${ICON.play}</span>`;
  return tile('gray', 'link', cls);
}

/** Photo thumbnail over the category tile, so a missing or failed image still shows something. */
function thumb(p, size = 56) {
  const photo = p.photos && p.photos[0];
  return `<span class="thumb" style="--s:${size}px">${catTile(p.category)}${photo
    ? `<img src="${esc(photoUrl(photo, 240))}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ''}</span>`;
}
const isNew = (p) => (S.newIds.has(p.id) ? '<span class="chip-new">NEW</span>' : '');

function segControl(key, items) {
  const i = Math.max(0, items.findIndex((x) => x.on));
  return `<nav class="seg${key.startsWith('modes') ? ' modes' : ''}" data-flip="${esc(key)}" style="--n:${items.length};--i:${i}">
    <span class="seg-thumb" aria-hidden="true"></span><span class="seg-items">${items.map((x) => x.html).join('')}</span></nav>`;
}

function placeRow(p) {
  return `<a class="row" href="#/place/${p.id}">
    ${thumb(p, 56)}
    <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${isNew(p)}${p.latitude == null ? ' <span class="flag" title="Not on the map yet">●</span>' : ''}</span>
    <span class="s">${esc([p.neighborhood, p.city].filter(Boolean).join(' · '))}</span>
    ${p.recommended_items.length ? `<span class="s clip">Try: ${esc(p.recommended_items.join(', '))}</span>` : ''}
    ${hoursLine(p)}${hereChip(p)}</span>
    ${ICON.chev}</a>`;
}

function jobRow(job) {
  const active = ACTIVE.has(job.status);
  const title = active ? (job.message || 'Waiting to process…') : job.status === 'failed' ? (job.message || 'Import failed') : (job.message || 'Done');
  const inner = `${platformTile(platformOf(job.url))}<span class="main"><span class="t" style="font-size:16px${job.status === 'failed' ? ';color:var(--warn)' : ''}">${esc(title)}</span>
    <span class="s clip">${esc(job.url.replace(/^https?:\/\/(www\.)?/, ''))} · ${timeAgo(job.created_at)}</span>
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
  if (!navigator.geolocation) throw new ApiError('This browser can’t share your location.', 0);
  const pos = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {
    enableHighAccuracy: false, timeout: 15000, maximumAge: 5 * 60 * 1000,
  })).catch((e) => {
    throw new ApiError(e.code === 1
      ? 'Location access is off. Allow it for TripIt in Settings → Privacy & Security → Location Services → Safari Websites.'
      : 'Couldn’t get your location. Try again outside or with Wi-Fi on.', 0);
  });
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

// ---------- Views ----------

const addButton = `<button class="gbtn tint" data-act="add" aria-label="Add a reel">${ICON.plus}</button>`;

const VIEWS = {
  async trips() {
    const trips = await cachedTrips();
    const inflightJobs = S.jobs.filter((j) => ACTIVE.has(j.status));
    const body = !trips.length && !inflightJobs.length
      ? emptyState('accent', 'plane', 'No trips yet',
        'Share a travel reel from TikTok or Instagram to TripIt, or paste a link. The places land here, pinned on a map.',
        `<button class="btn" data-act="add">${ICON.link}Paste a link</button><a class="linkbtn" href="#/settings">Set up the share button</a>`)
      : `${inflightJobs.length ? `<div class="section"><div class="group tiles">${inflightJobs.map(jobRow).join('')}</div></div>` : ''}
         ${trips.length ? `<div class="cards">${trips.map(tripCard).join('')}</div>` : ''}`;
    return {
      html: `${navbar('Trips', { right: addButton })}<h1 class="largetitle" data-anchor>Trips</h1>${body}`,
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
      <div class="subtitle"><span>${esc(meta)}</span><span class="tiles-inline" aria-hidden="true">${cats.slice(0, 6).map((c) => catTile(c, 'sm')).join('')}</span></div>${seg}`;

    if (mode === 'places') return head + placesList(trip);
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

  async place(r) {
    const trip = await findPlace(r.id);
    const p = tripPlace(trip, r.id);
    if (!p) throw new ApiError('This place was deleted.', 404);
    const links = mapsLinks(p, trip);
    const reel = trip.reels.find((x) => x.id === p.reel_id);
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
        </select></div>` : '';

    const html = `${navbar(p.name, { back: `#/trip/${trip.id}`, backLabel: trip.name })}
      ${hero}
      <div class="ph" style="${cvar(p.category)}">
        <span class="cat">${catTile(p.category, 'sm')}${CATS[p.category]}</span>
        <h1 data-anchor>${esc(p.name)}${isNew(p)}</h1>
        <span class="loc">${esc([p.neighborhood, p.city].filter(Boolean).join(' · '))}</span>
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

      ${reel ? `<div class="section"><div class="section-h">Saved from</div><div class="group tiles">
        ${safeUrl(reel.url) ? `<a class="row" href="${esc(reel.url)}" target="_blank" rel="noopener">` : '<div class="row">'}
        ${platformTile(platformOf(reel.platform || reel.url))}
        <span class="main"><span class="t">${esc(reel.title)}</span>
        <span class="s">${esc([platformName(reel.platform), reel.creator ? `@${reel.creator}` : ''].filter(Boolean).join(' · '))}</span></span>
        ${safeUrl(reel.url) ? `${ICON.chev}</a>` : '</div>'}</div></div>` : ''}

      <div class="section"><div class="group"><button class="row destructive" data-act="askdeleteplace" data-id="${p.id}" data-trip="${trip.id}">Delete place</button></div></div>`;
    return {
      html,
      after: () => { if (isLocated) renderMap($('#mini-map'), [p], { interactive: false, zoom: 15 }); },
    };
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
    const origin = location.origin;
    const key = getKey();
    const geocoder = { google: 'Google Places', openstreetmap: 'OpenStreetMap', none: 'Off' }[S.config.geocoder] || S.config.geocoder;
    const copyLine = (value, label) => `<div class="copyline"><code>${esc(value)}</code><button class="copybtn" data-act="copy" data-value="${esc(value)}" aria-label="Copy ${label}">Copy</button></div>`;
    return `${navbar('Settings')}<h1 class="largetitle" data-anchor>Settings</h1>

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
  if (ph.source === 'reel') return 'From the reel';
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
  return CAT_ORDER.filter((c) => trip.places.some((p) => p.category === c)).map((c) => {
    const list = trip.places.filter((p) => p.category === c);
    return `<div class="section"><h2 class="section-title">${catTile(c)}${CATS[c]}<span class="count">${list.length}</span></h2>
      <div class="group thumbs">${list.map(placeRow).join('')}</div></div>`;
  }).join('')
    + (trip.reels.length ? `<div class="section"><h2 class="section-title">Saved from</h2><div class="group tiles">${trip.reels.map((r) => `
      ${safeUrl(r.url) ? `<a class="row" href="${esc(r.url)}" target="_blank" rel="noopener">` : '<div class="row">'}${platformTile(platformOf(r.platform || r.url))}
      <span class="main"><span class="t" style="font-size:16px">${esc(r.title)}</span>
      <span class="s">${esc([platformName(r.platform), r.creator ? `@${r.creator}` : '', plural(r.place_count, 'place')].filter(Boolean).join(' · '))}</span></span>${safeUrl(r.url) ? `${ICON.chev}</a>` : '</div>'}`).join('')}</div></div>` : '');
}

function itinerary(trip) {
  if (!trip.day_count) {
    return emptyState('indigo', 'calendar', 'No itinerary yet',
      `Turn your ${plural(trip.places.length, 'saved place')} into a day-by-day plan grouped by neighborhood and time of day.`,
      `<button class="btn" data-act="plan" data-id="${trip.id}" ${trip.places.length ? '' : 'disabled'}>${ICON.sparkle}Plan my trip</button>`);
  }
  const by = trip.planned_by === 'claude'
    ? `<span class="planned-by">${ICON.sparkle}Planned with Claude</span>`
    : trip.planned_by === 'offline' ? '<span class="planned-by">Quick plan grouped by location</span>' : '<span></span>';
  let html = `<div class="planbar">${by}
    <span><button class="linkbtn" data-act="plan" data-id="${trip.id}">Re-plan</button>
    <button class="linkbtn" data-act="editday" style="margin-left:10px">${S.editDay ? 'Done' : 'Edit'}</button></span></div>`;
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
      <div class="dt">${esc(trip.day_titles[d - 1] || `Day ${d}`)}</div></div><span class="daytravel" data-day="${d}"></span></div>
      <div class="group">${list.map((p, i) => {
        const conflict = slotConflict(p.opening_hours, dayIdx, p.time_of_day);
        const todays = dayIdx != null ? dayHours(p.opening_hours, dayIdx) : null;
        const inner = `<span class="stopnum" style="${cvar(p.category)}">${i + 1}</span>
          ${thumb(p, 52)}
          <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${isNew(p)}</span>
          <span class="s">${esc([cap(p.time_of_day || ''), CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</span>
          ${todays && !conflict ? `<span class="s">${ICON.clock.replace('<svg', '<svg class="inline-ic"')}${esc(todays)}</span>` : ''}
          ${conflict ? `<span class="warnline">${ICON.warn}${esc(conflict)}${todays && todays !== 'Closed' ? ` (${esc(todays)})` : ''}</span>` : ''}
          ${p.day_note ? `<span class="daynote">${esc(p.day_note)}</span>` : ''}
          ${hereChip(p)}</span>`;
        const next = locatedList[locatedList.indexOf(p) + 1];
        const legRow = located(p) && next && !S.editDay
          ? `<div class="leg" data-day="${d}" data-from="${p.id}" data-to="${next.id}"><span class="spinner" style="width:14px;height:14px"></span></div>` : '';
        return (S.editDay
          ? `<div class="row">${inner}<span class="movers">
              <button class="mover" data-act="move" data-trip="${trip.id}" data-day="${d}" data-id="${p.id}" data-dir="-1" aria-label="Move ${esc(p.name)} up" ${i === 0 ? 'disabled' : ''}>${ICON.up}</button>
              <button class="mover" data-act="move" data-trip="${trip.id}" data-day="${d}" data-id="${p.id}" data-dir="1" aria-label="Move ${esc(p.name)} down" ${i === list.length - 1 ? 'disabled' : ''}>${ICON.down}</button></span></div>`
          : `<a class="row" href="#/place/${p.id}">${inner}${ICON.chev}</a>`) + legRow;
      }).join('') || '<div class="row"><span class="s">Nothing planned. Move places here from their page.</span></div>'}</div></div>`;
  }
  html += '<div class="section" id="travel-note" hidden><div class="section-f">Travel times are estimates from distance. Real routes and transit times need a Google key with the Routes API (see the README).</div></div>';
  if (!trip.start_date && trip.places.some((p) => p.opening_hours && p.opening_hours.weekly)) {
    html += '<div class="section"><div class="section-f">Set a start date when you re-plan to check each stop is open on the day it’s scheduled.</div></div>';
  }
  const un = trip.places.filter((p) => p.day_number == null);
  if (un.length) html += `<div class="section"><h2 class="section-title">Not scheduled<span class="count">${un.length}</span></h2><div class="group thumbs">${un.map(placeRow).join('')}</div></div>`;
  html += '<div class="section"><div class="section-f">Open a place to move it to another day or change its time.</div></div>';
  return html;
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

function addSheet() {
  openSheet({
    type: 'form', title: 'Add a reel', confirm: 'Add',
    body: () => `<div class="section"><div class="group"><div class="row">
      <input class="field" id="add-url" type="url" inputmode="url" placeholder="https://www.tiktok.com/…" autocomplete="off" autocapitalize="off" aria-label="Reel link"></div></div>
      <div class="section-f">Paste a TikTok, Instagram Reel or YouTube Shorts link. Sharing straight from the app is faster once the shortcut is set up.</div></div>`,
    async ok() {
      const v = $('#add-url').value.trim();
      if (!v) return;
      closeSheet();
      await submitLink(v);
      go('#/');
    },
  });
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
    case 'add': addSheet(); return;
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
        { label: 'Rename', run: () => renameSheet(t) },
        { label: 'Update hours & photos', run: async () => {
          toast('Looking up hours and photos…');
          S.trip[t.id] = await api(`/v1/trips/${t.id}/refresh-details`, { method: 'POST' });
          fetchedAt.trips = 0;
          toast('Hours and photos updated');
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
    case 'sharetrip': shareTrip(S.trip[el.dataset.id]); return;
    case 'editday': S.editDay = !S.editDay; render(); return;
    case 'move': {
      const t = S.trip[el.dataset.trip];
      const day = Number(el.dataset.day);
      const ids = stops(t, day).map((p) => p.id);
      const i = ids.indexOf(el.dataset.id);
      const j = i + Number(el.dataset.dir);
      if (j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      S.trip[t.id] = await api(`/v1/trips/${t.id}/days/${day}/order`, { method: 'POST', body: { place_ids: ids } });
      render();
      return;
    }
    case 'mode': setTravelMode(el.dataset.mode); render(); return;
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
    case 'signout': setKey(''); S.config = null; go('#/setup'); return;
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
    if ('category' in body) fetchedAt.trips = 0;
    if (rerender) render();
  } catch (e) {
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
  const segLink = ev.target.closest('.seg-items a[href]');
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
});

document.addEventListener('submit', async (ev) => {
  const form = ev.target.closest('[data-form]');
  if (!form) return;
  ev.preventDefault();
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
  if (ev.key === 'Escape' && S.sheet) closeSheet();
  if (S.sheet && S.sheet.type === 'photos' && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
    const n = S.sheet.place.photos.length;
    S.sheet.index = (S.sheet.index + (ev.key === 'ArrowRight' ? 1 : -1) + n) % n;
    renderOverlay();
  }
  if (ev.key === 'Enter' && S.sheet && S.sheet.ok && ev.target.matches('.sheet input.field')) { ev.preventDefault(); S.sheet.ok(); }
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
  if (route().name === 'setup') location.hash = '#/';
  else render();
}

document.addEventListener('tripit:maps-fallback', () => {
  toast('Google Maps rejected the API key, so OpenStreetMap is shown. Check the key’s website restrictions.', true);
  render();
});

hydrateIcons(document.getElementById('tabbar'));
(async () => {
  try {
    S.config = await api('/v1/config');
    configureMaps({ googleMapsKey: S.config.google_maps_key });
  } catch (e) {
    if (e.status === 401) { location.hash = '#/setup'; render(); return; }
  }
  await start();
})();
