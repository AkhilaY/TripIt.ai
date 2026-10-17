import { api, ApiError, getKey, setKey } from './api.js';
import { ICON, hydrateIcons } from './icons.js';
import { destroyMaps, renderMap } from './map.js';

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

// ---------- State ----------

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
  scroll: {},
};

const view = $('#view');
const overlay = $('#overlay');

// ---------- Routing ----------

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
let renderToken = 0;
let lastKey = '';

async function render() {
  const r = route();
  const token = ++renderToken;
  const key = location.hash;
  if (lastKey) S.scroll[lastKey] = window.scrollY;

  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.tab === TAB_FOR[r.name]));
  $('#tabbar').hidden = r.name === 'setup';
  $('.app').classList.toggle('fullbleed', r.name === 'map' || (r.name === 'trip' && r.mode === 'map'));

  let html;
  let after = () => {};
  try {
    const out = await VIEWS[r.name](r);
    html = typeof out === 'string' ? out : out.html;
    if (out.after) after = out.after;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { location.hash = '#/setup'; return; }
    html = `${navbar('', {})}<div class="error" role="alert">${esc(e.message || 'Something went wrong')}</div>
      <div class="section"><button class="btn tint" data-act="reload">Try again</button></div>`;
  }
  if (token !== renderToken) return; // a newer render started

  destroyMaps();
  view.innerHTML = html;
  hydrateIcons(view);
  after();
  window.scrollTo(0, key === lastKey ? (S.scroll[key] || 0) : (S.scroll[key] || 0));
  lastKey = key;
}

function go(hash) {
  if (location.hash === hash) render();
  else location.hash = hash;
}

window.addEventListener('hashchange', () => { S.navigations++; S.editDay = false; render(); });

// ---------- Shared pieces ----------

function navbar(title, { back, backLabel, right = '', plain = false }) {
  const backHtml = back
    ? `<a class="navbtn" href="${back}" data-act="back" data-fallback="${back}">${ICON.back}${esc(backLabel || 'Back')}</a>`
    : '';
  return `<header class="navbar${plain ? ' plain' : ''}"><div class="left">${backHtml}</div>
    <div class="title">${esc(title)}</div><div class="right">${right}</div></header>`;
}

const badge = (cat) => `<span class="badge" style="${cvar(cat)}">${ICON[cat] || ICON.other}</span>`;
const isNew = (p) => (S.newIds.has(p.id) ? '<span class="chip-new">NEW</span>' : '');

function placeRow(p) {
  return `<a class="row indent" href="#/place/${p.id}">
    ${badge(p.category)}
    <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${isNew(p)}${p.latitude == null ? ' <span class="flag" title="Not on the map yet">●</span>' : ''}</span>
    <span class="s">${esc([p.neighborhood, p.city].filter(Boolean).join(' · '))}</span>
    ${p.recommended_items.length ? `<span class="s clip">Try: ${esc(p.recommended_items.join(', '))}</span>` : ''}</span>
    ${ICON.chev}</a>`;
}

function jobRow(job) {
  const active = ACTIVE.has(job.status);
  const icon = active ? '<span class="spinner"></span>'
    : job.status === 'failed' ? `<span style="color:var(--warn);width:20px">${ICON.warn}</span>`
    : `<span style="color:var(--ok);width:20px">${ICON.check}</span>`;
  const title = active ? (job.message || 'Waiting to process…') : job.status === 'failed' ? (job.message || 'Import failed') : (job.message || 'Done');
  const inner = `${icon}<span class="main"><span class="t" style="font-size:15px">${esc(title)}</span>
    <span class="s clip">${esc(job.url.replace(/^https?:\/\/(www\.)?/, ''))} · ${timeAgo(job.created_at)}</span>
    ${(job.warnings || []).map((w) => `<span class="s" style="color:var(--warn)">${esc(w)}</span>`).join('')}</span>`;
  if (job.status === 'done' && job.trip_id) return `<a class="row" href="#/trip/${job.trip_id}">${inner}${ICON.chev}</a>`;
  if (job.status === 'failed') return `<div class="row">${inner}<button class="btn tint" style="padding:6px 12px" data-act="retry" data-id="${job.id}">Retry</button></div>`;
  return `<div class="row">${inner}</div>`;
}

// ---------- Data ----------

async function loadTrips() { S.trips = await api('/v1/trips'); return S.trips; }
async function loadTrip(id) { S.trip[id] = await api(`/v1/trips/${id}`); return S.trip[id]; }

async function findPlace(id) {
  for (const t of Object.values(S.trip)) {
    const p = t.places.find((x) => x.id === id);
    if (p) return { trip: await loadTrip(t.id), id };
  }
  const all = await api('/v1/places');
  const p = all.find((x) => x.id === id);
  if (!p) throw new ApiError('This place was deleted.', 404);
  return { trip: await loadTrip(p.trip_id), id };
}

const tripPlace = (trip, id) => trip.places.find((p) => p.id === id);
const stops = (trip, day) => trip.places.filter((p) => p.day_number === day).sort((a, b) => a.day_order - b.day_order);

// ---------- Views ----------

const VIEWS = {
  async trips() {
    const trips = await loadTrips();
    const inflight = S.jobs.filter((j) => ACTIVE.has(j.status));
    const rows = trips.map((t) => `<a class="row" href="#/trip/${t.id}">
      <span class="main"><span class="t b">${esc(t.name)}</span>
      <span class="s">${plural(t.place_count, 'place')}${t.day_count ? ` · ${t.day_count}-day plan` : ''}${t.country ? ` · ${esc(t.country)}` : ''}</span>
      <span class="mini-icons">${t.categories.map((c) => `<span style="${cvar(c)}">${ICON[c] || ''}</span>`).join('')}</span></span>
      ${ICON.chev}</a>`).join('');
    const body = !trips.length && !inflight.length
      ? `<div class="empty">${ICON.plane}<h3>No trips yet</h3>
          <p>Share a travel reel from TikTok or Instagram to TripIt, or paste a link. The places land here, pinned on a map.</p>
          <button class="btn" data-act="add">Paste a link</button>
          <a href="#/settings" style="font-size:15px;margin-top:6px">Set up the share button</a></div>`
      : `${inflight.length ? `<div class="section"><div class="group">${inflight.map(jobRow).join('')}</div></div>` : ''}
         ${trips.length ? `<div class="section"><div class="group">${rows}</div></div>` : ''}`;
    return `${navbar('', { plain: true, right: `<button class="navbtn" data-act="add" aria-label="Add a reel">${ICON.plus}</button>` })}
      <h1 class="largetitle">Trips</h1>${body}`;
  },

  async trip(r) {
    const trip = await loadTrip(r.id);
    const mode = ['places', 'itinerary', 'map'].includes(r.mode) ? r.mode : 'places';
    const right = `<button class="navbtn" data-act="sharetrip" data-id="${trip.id}" aria-label="Share trip">${ICON.share}</button>
      <button class="navbtn" data-act="tripmenu" data-id="${trip.id}" aria-label="More">${ICON.more}</button>`;
    const seg = `<nav class="seg">${['places', 'itinerary', 'map'].map((m) =>
      `<a href="#/trip/${trip.id}${m === 'places' ? '' : `/${m}`}" class="${m === mode ? 'on' : ''}" ${m === mode ? 'aria-current="page"' : ''}>${cap(m)}</a>`).join('')}</nav>`;
    const head = `${navbar(trip.name, { back: '#/', backLabel: 'Trips', right })}${seg}`;

    if (mode === 'places') return head + placesList(trip);
    if (mode === 'itinerary') return head + itinerary(trip);

    const day = S.mapDay[trip.id] || 0;
    const shown = day ? stops(trip, day) : trip.places;
    const chips = trip.day_count
      ? `<div class="mapchips">${[0, ...Array.from({ length: trip.day_count }, (_, i) => i + 1)].map((d) =>
          `<button class="mapchip ${d === day ? 'on' : ''}" data-act="mapday" data-trip="${trip.id}" data-day="${d}">${d ? `Day ${d}` : 'All'}</button>`).join('')}</div>`
      : '';
    const missing = shown.filter((p) => p.latitude == null).length;
    return {
      html: `${head}<div class="map trip-map"><div id="trip-map" style="position:absolute;inset:0"></div>${chips}
        ${missing ? `<div class="mapnote">${plural(missing, 'place')} not on the map yet</div>` : ''}</div>`,
      after: () => renderMap($('#trip-map'), shown, { route: !!day, popup: popupHtml, newIds: S.newIds }),
    };
  },

  async place(r) {
    const { trip } = await findPlace(r.id);
    const p = tripPlace(trip, r.id);
    if (!p) throw new ApiError('This place was deleted.', 404);
    const links = mapsLinks(p, trip);
    const reel = trip.reels.find((x) => x.id === p.reel_id);
    const located = p.latitude != null;
    const dayRows = trip.day_count ? `
      <div class="row"><label class="main" for="day-select"><span class="t">Day</span></label>
        <select class="select" id="day-select" data-act="setday" data-id="${p.id}">
          <option value="0">Not scheduled</option>
          ${Array.from({ length: trip.day_count }, (_, i) => `<option value="${i + 1}" ${p.day_number === i + 1 ? 'selected' : ''}>Day ${i + 1}</option>`).join('')}
        </select></div>
      <div class="row"><label class="main" for="tod-select"><span class="t">Time</span></label>
        <select class="select" id="tod-select" data-act="settod" data-id="${p.id}">
          <option value="">Any time</option>
          ${TODS.map((x) => `<option value="${x}" ${p.time_of_day === x ? 'selected' : ''}>${cap(x)}</option>`).join('')}
        </select></div>` : '';

    const html = `${navbar(p.name, { back: `#/trip/${trip.id}`, backLabel: trip.name })}
      <div class="section" style="margin-top:8px"><div class="group">
        ${located ? '<div class="map mini-map"><div id="mini-map" style="position:absolute;inset:0"></div></div>' : ''}
        <div class="ph" style="${cvar(p.category)}">
          <span class="cat">${ICON[p.category] || ''}${CATS[p.category]}</span>
          <h2>${esc(p.name)}${isNew(p)}</h2>
          ${p.resolved_name ? `<span class="s">On maps as ${esc(p.resolved_name)}</span>` : ''}
          <span class="loc">${esc([p.neighborhood, p.city].filter(Boolean).join(' · '))}</span>
          ${p.confidence === 'low' ? '<span class="flag">The name was hard to make out in the reel; double-check it.</span>' : ''}
        </div>
        ${p.summary ? `<div class="para">${esc(p.summary)}</div>` : ''}
      </div></div>

      ${located ? '' : `<div class="section"><div class="section-h">Not on the map yet</div><div class="group">
        <form class="row" data-form="locate" data-id="${p.id}"><span class="inline-form">
          <input class="field" id="locate-q" name="q" placeholder="Search, e.g. ${esc(p.name)}, ${esc(p.city)}" value="${esc(`${p.name}, ${p.neighborhood ? `${p.neighborhood}, ` : ''}${p.city}`)}" autocomplete="off">
          <button class="btn" type="submit" style="padding:7px 12px">Find</button></span></form>
        </div><div class="section-f">Add a street or neighborhood if the first search didn’t find it.</div></div>`}

      <div class="section"><div class="section-h">Open in</div><div class="group">
        <div class="twobtn">
          <a class="btn tint" href="${esc(links.apple)}" target="_blank" rel="noopener">${ICON.map}Apple Maps</a>
          <a class="btn tint" href="${esc(links.google)}" target="_blank" rel="noopener">${ICON.globe}Google Maps</a>
        </div>
        <a class="row" href="${esc(links.appleDir)}" target="_blank" rel="noopener"><span class="main"><span class="t link">Directions in Apple Maps</span></span></a>
        <a class="row" href="${esc(links.googleDir)}" target="_blank" rel="noopener"><span class="main"><span class="t link">Directions in Google Maps</span></span></a>
      </div></div>

      ${(p.recommended_items.length || p.tips || p.price_hint) ? `<div class="section"><div class="section-h">From the reel</div><div class="group">
        ${p.recommended_items.map((i) => `<div class="row"><span class="reelitem">${ICON.star}<span>${esc(i)}</span></span></div>`).join('')}
        ${p.price_hint ? `<div class="row"><span class="main"><span class="s">Price</span><span class="t">${esc(p.price_hint)}</span></span></div>` : ''}
        ${p.tips ? `<div class="row"><span class="main"><span class="s">Tip</span><span class="t">${esc(p.tips)}</span></span></div>` : ''}
      </div></div>` : ''}

      <div class="section"><div class="section-h">Details</div><div class="group">
        ${p.address ? `<div class="row"><span class="main"><span class="s">Address</span><span class="t">${esc(p.address)}</span></span></div>` : ''}
        <label class="row" for="visited-toggle"><span class="main"><span class="t">Visited</span></span>
          <input class="switch" type="checkbox" id="visited-toggle" data-act="visited" data-id="${p.id}" ${p.visited ? 'checked' : ''}></label>
        ${dayRows}
        <div class="row"><label class="main" for="cat-select"><span class="t">Category</span></label>
          <select class="select" id="cat-select" data-act="setcat" data-id="${p.id}">
            ${CAT_ORDER.map((c) => `<option value="${c}" ${p.category === c ? 'selected' : ''}>${CATS[c]}</option>`).join('')}
          </select></div>
        ${located ? `<button class="row" data-act="relocate" data-id="${p.id}"><span class="main"><span class="t link">Wrong pin? Search again</span></span></button>` : ''}
      </div></div>

      <div class="section"><div class="section-h">My notes</div><div class="group"><div class="row">
        <textarea class="notes" id="notes" data-act="notes" data-id="${p.id}" placeholder="Add a note" rows="3">${esc(p.user_notes)}</textarea>
      </div></div></div>

      ${reel ? `<div class="section"><div class="section-h">Saved from</div><div class="group">
        ${safeUrl(reel.url) ? `<a class="row" href="${esc(reel.url)}" target="_blank" rel="noopener">` : '<div class="row">'}
        <span class="main"><span class="t">${esc(reel.title)}</span>
        <span class="s">${esc([cap(reel.platform), reel.creator ? `@${reel.creator}` : ''].filter(Boolean).join(' · '))}</span></span>
        ${safeUrl(reel.url) ? `${ICON.chev}</a>` : '</div>'}</div></div>` : ''}

      <div class="section"><div class="group"><button class="row destructive" data-act="askdeleteplace" data-id="${p.id}" data-trip="${trip.id}">Delete place</button></div></div>`;
    return {
      html,
      after: () => { if (located) renderMap($('#mini-map'), [p], { interactive: false, zoom: 15 }); },
    };
  },

  async map() {
    const [trips, places] = await Promise.all([loadTrips(), api('/v1/places')]);
    S.places = places;
    if (!S.mapTrip || (S.mapTrip !== 'all' && !trips.some((t) => t.id === S.mapTrip))) S.mapTrip = trips[0] ? trips[0].id : 'all';
    const shown = S.mapTrip === 'all' ? places : places.filter((p) => p.trip_id === S.mapTrip);
    const chips = `<div class="mapchips">${[{ id: 'all', name: 'All' }, ...trips].map((t) =>
      `<button class="mapchip ${S.mapTrip === t.id ? 'on' : ''}" data-act="maptrip" data-id="${t.id}">${esc(t.name)}${t.place_count != null ? ` · ${t.place_count}` : ''}</button>`).join('')}</div>`;
    return {
      html: `${navbar('All places', {})}<div class="map all-map"><div id="all-map" style="position:absolute;inset:0"></div>${trips.length ? chips : ''}
        ${!places.length ? '<div class="mapnote">No places yet. Share a reel to start.</div>' : ''}</div>`,
      after: () => renderMap($('#all-map'), shown, { popup: popupHtml, newIds: S.newIds }),
    };
  },

  async imports() {
    S.jobs = await api('/v1/jobs?limit=40');
    schedulePoll();
    return `${navbar('', { plain: true, right: `<button class="navbtn" data-act="add" aria-label="Add a reel">${ICON.plus}</button>` })}
      <h1 class="largetitle">Imports</h1>
      ${S.jobs.length ? `<div class="section"><div class="group">${S.jobs.map(jobRow).join('')}</div>
        <div class="section-f">Tap a finished import to open its trip.</div></div>`
        : `<div class="empty">${ICON.tray}<h3>Nothing imported yet</h3><p>Reels you share to TripIt show up here while they’re processed.</p></div>`}`;
  },

  async settings() {
    if (!S.config) S.config = await api('/v1/config');
    const origin = location.origin;
    const key = getKey();
    const geocoder = { google: 'Google Places', openstreetmap: 'OpenStreetMap (free)', none: 'Off' }[S.config.geocoder] || S.config.geocoder;
    const copyLine = (value, label) => `<div class="copyline"><code>${esc(value)}</code><button class="copybtn" data-act="copy" data-value="${esc(value)}" aria-label="Copy ${label}">Copy</button></div>`;
    return `${navbar('', { plain: true })}<h1 class="largetitle">Settings</h1>

      <div class="section"><div class="section-h">Share from TikTok &amp; Instagram (iPhone)</div><div class="group">
        <ol class="steps">
          <li>Open the <b>Shortcuts</b> app, tap <b>+</b> and name the shortcut <b>TripIt</b>.</li>
          <li>Tap the <b>ⓘ</b> button (or the name at the top) and turn on <b>Show in Share Sheet</b>. Tap <b>Done</b>.</li>
          <li>At the top it now says “Receive <i>Any</i> input from Share Sheet”. Tap <i>Any</i> and keep only <b>URLs</b> and <b>Text</b>.</li>
          <li>Add the action <b>Get Contents of URL</b>. Set the URL to the address below.</li>
          <li>Tap the <b>›</b> arrow on that action: set <b>Method</b> to <b>POST</b>; under <b>Headers</b> add <span class="kbd">X-API-Key</span> with your key below; set <b>Request Body</b> to <b>JSON</b> and add a <b>Text</b> field named <span class="kbd">url</span> whose value is the <b>Shortcut Input</b> variable.</li>
          <li>Optional: add <b>Show Notification</b> with the text “Saved to TripIt”.</li>
          <li>In TikTok tap <b>Share → More (•••)</b>, or in Instagram tap the <b>paper plane → Share to…</b>, then choose <b>TripIt</b>. The first time, you may need to scroll the app row and add TripIt to your favorites.</li>
        </ol>
        <div class="section-h" style="padding-top:4px">Shortcut URL</div>${copyLine(`${origin}/v1/jobs`, 'shortcut URL')}
        <div class="section-h" style="padding-top:4px">X-API-Key</div>${key ? copyLine(key, 'API key') : '<div class="copyline"><span class="s">This server doesn’t require a key.</span></div>'}
      </div>
      <div class="section-f">Simpler but opens TripIt each time: make the shortcut a single <b>Open URLs</b> action with <span class="kbd">${esc(origin)}/share?url=</span> followed by the <b>Shortcut Input</b> variable. It opens in Safari, so sign in there once too.</div></div>

      <div class="section"><div class="section-h">Add TripIt to your Home Screen</div><div class="group">
        <ol class="steps">
          <li>Open this page in <b>Safari</b>.</li>
          <li>Tap the <b>Share</b> button, then <b>Add to Home Screen</b>.</li>
          <li>TripIt opens full screen, like an app. On Android, use Chrome’s <b>Install app</b> and TripIt appears in the share sheet automatically.</li>
        </ol></div></div>

      <div class="section"><div class="section-h">Server</div><div class="group">
        <div class="row"><span class="main"><span class="s">Address</span><span class="t">${esc(origin)}</span></span></div>
        <div class="row"><span class="main"><span class="t">Finding places on the map</span></span><span class="val">${esc(geocoder)}</span></div>
        ${key ? '<button class="row destructive" data-act="signout">Sign out on this device</button>' : ''}
      </div></div>`;
  },

  async setup() {
    return `<div class="empty" style="padding-top:80px">${ICON.map}<h3>Welcome to TripIt</h3>
      <p>Enter the API key you set as <span class="kbd">APP_API_KEY</span> on your server. You only do this once per device.</p></div>
      <div class="section"><div class="group"><form class="row" data-form="setkey"><span class="inline-form">
        <input class="field" id="key-input" name="key" type="password" placeholder="API key" autocomplete="current-password" required>
        <button class="btn" type="submit" style="padding:7px 14px">Continue</button></span></form></div>
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

function placesList(trip) {
  if (!trip.places.length) return `<div class="empty">${ICON.pinslash}<h3>No places</h3><p>Places you save from reels appear here.</p></div>`;
  return CAT_ORDER.filter((c) => trip.places.some((p) => p.category === c)).map((c) => `
    <div class="section"><div class="section-h" style="${cvar(c)};color:var(--pc)">${ICON[c]}${CATS[c]}</div>
    <div class="group">${trip.places.filter((p) => p.category === c).map(placeRow).join('')}</div></div>`).join('')
    + (trip.reels.length ? `<div class="section"><div class="section-h">Saved from</div><div class="group">${trip.reels.map((r) => `
      ${safeUrl(r.url) ? `<a class="row" href="${esc(r.url)}" target="_blank" rel="noopener">` : '<div class="row">'}<span class="main"><span class="t" style="font-size:15px">${esc(r.title)}</span>
      <span class="s">${esc([cap(r.platform), r.creator ? `@${r.creator}` : '', plural(r.place_count, 'place')].filter(Boolean).join(' · '))}</span></span>${safeUrl(r.url) ? '</a>' : '</div>'}`).join('')}</div></div>` : '');
}

function itinerary(trip) {
  if (!trip.day_count) {
    return `<div class="empty">${ICON.calendar}<h3>No itinerary yet</h3>
      <p>Turn your ${plural(trip.places.length, 'saved place')} into a day-by-day plan grouped by neighborhood and time of day.</p>
      <button class="btn" data-act="plan" data-id="${trip.id}" ${trip.places.length ? '' : 'disabled'}>Plan my trip</button></div>`;
  }
  const by = trip.planned_by === 'claude'
    ? `<span class="planned-by">${ICON.sparkle.replace('<svg', '<svg width="14" height="14"')}Planned with Claude</span>`
    : trip.planned_by === 'offline' ? 'Quick plan grouped by location' : '';
  let html = `<div class="section" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;gap:8px">
    <span class="s">${by}</span>
    <span style="display:flex;gap:4px"><button class="navbtn" data-act="plan" data-id="${trip.id}">Re-plan</button>
    <button class="navbtn bold" data-act="editday">${S.editDay ? 'Done' : 'Edit'}</button></span></div>`;
  if (trip.plan_notes) html += `<div class="section"><div class="group"><div class="para" style="border:0">${esc(trip.plan_notes)}</div></div></div>`;
  for (let d = 1; d <= trip.day_count; d++) {
    const list = stops(trip, d);
    const date = dayDate(trip.start_date, d);
    html += `<div class="section"><div class="dayhead"><div class="d">Day ${d}${date ? `<span>${date}</span>` : ''}</div>
      <div class="dt">${esc(trip.day_titles[d - 1] || `Day ${d}`)}</div></div>
      <div class="group">${list.map((p, i) => {
        const inner = `<span class="tod" style="${cvar(p.category)}"><i></i><span>${cap(p.time_of_day || '')}</span></span>
          <span class="main"><span class="t ${p.visited ? 'strike' : ''}">${esc(p.name)}${isNew(p)}</span>
          <span class="s">${CATS[p.category]}${p.neighborhood ? ` · ${esc(p.neighborhood)}` : ''}</span>
          ${p.day_note ? `<span class="daynote">${esc(p.day_note)}</span>` : ''}</span>`;
        return S.editDay
          ? `<div class="row">${inner}<span class="movers">
              <button class="mover" data-act="move" data-trip="${trip.id}" data-day="${d}" data-id="${p.id}" data-dir="-1" aria-label="Move ${esc(p.name)} up" ${i === 0 ? 'disabled' : ''}>${ICON.up}</button>
              <button class="mover" data-act="move" data-trip="${trip.id}" data-day="${d}" data-id="${p.id}" data-dir="1" aria-label="Move ${esc(p.name)} down" ${i === list.length - 1 ? 'disabled' : ''}>${ICON.down}</button></span></div>`
          : `<a class="row" href="#/place/${p.id}">${inner}${ICON.chev}</a>`;
      }).join('') || '<div class="row"><span class="s">Nothing planned. Move places here from their page.</span></div>'}</div></div>`;
  }
  const un = trip.places.filter((p) => p.day_number == null);
  if (un.length) html += `<div class="section"><div class="section-h">Not scheduled</div><div class="group">${un.map(placeRow).join('')}</div></div>`;
  html += '<div class="section"><div class="section-f">Open a place to move it to another day or change its time.</div></div>';
  return html;
}

function popupHtml(p) {
  return `<strong>${esc(p.name)}</strong><br><span style="color:var(--secondary);font-size:13px">${esc(CATS[p.category])}${p.neighborhood ? ` · ${esc(p.neighborhood)}` : ''}</span>
    <a class="popup-link" href="#/place/${p.id}">Details ›</a>`;
}

// ---------- Sheets ----------

function renderOverlay() {
  const sh = S.sheet;
  let html = '';
  if (sh) {
    if (sh.type === 'actions') {
      html = `<div class="dim" data-act="close"></div><div class="actionsheet" role="dialog" aria-label="${esc(sh.title || 'Actions')}">
        <div class="group">${sh.title ? `<div class="row centered"><span class="s">${esc(sh.title)}</span></div>` : ''}
        ${sh.actions.map((a, i) => `<button class="row ${a.destructive ? 'destructive' : ''}" style="${a.destructive ? '' : 'color:var(--accent)'}" data-act="action" data-index="${i}">${esc(a.label)}</button>`).join('')}</div>
        <div class="group"><button class="row" style="font-weight:600;color:var(--accent)" data-act="close">Cancel</button></div></div>`;
    } else {
      html = `<div class="dim" data-act="close"></div><div class="sheet" role="dialog" aria-label="${esc(sh.title)}"><div class="grab"></div>
        <div class="navbar"><div class="left"><button class="navbtn" data-act="close">Cancel</button></div>
        <div class="title">${esc(sh.title)}</div>
        <div class="right">${sh.busy ? '<span class="spinner" style="margin:12px"></span>' : sh.confirm ? `<button class="navbtn bold" data-act="sheetok">${esc(sh.confirm)}</button>` : ''}</div></div>
        <div class="sheet-body">${sh.body()}</div></div>`;
    }
  }
  if (S.toast) html += `<div class="toast ${S.toast.error ? 'err' : ''}" role="status">${S.toast.error ? ICON.warn : ICON.check}<span>${esc(S.toast.text)}</span></div>`;
  overlay.innerHTML = html;
  const first = overlay.querySelector('.sheet input:not([type=checkbox]), .sheet textarea');
  if (first && sh && !sh.focused) { first.focus(); sh.focused = true; }
}

function openSheet(sheet) { S.sheet = sheet; renderOverlay(); }
function closeSheet() { S.sheet = null; renderOverlay(); }

let toastTimer;
function toast(text, error = false) {
  S.toast = { text, error };
  renderOverlay();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { S.toast = null; renderOverlay(); }, error ? 4000 : 2600);
}

function addSheet() {
  openSheet({
    type: 'form', title: 'Add a reel', confirm: 'Add',
    body: () => `<div class="section"><div class="group"><div class="row">
      <input class="field" id="add-url" type="url" inputmode="url" placeholder="https://www.tiktok.com/…" autocomplete="off" autocapitalize="off"></div></div>
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
    body: () => `<div class="section"><div class="group">
        <div class="row"><span class="main"><span class="t">${plural(st.days, 'day')}</span></span>
          <span class="stepper"><button type="button" data-act="days" data-d="-1" aria-label="Fewer days">−</button><button type="button" data-act="days" data-d="1" aria-label="More days">+</button></span></div>
        <label class="row" for="start-toggle"><span class="main"><span class="t">Set start date</span></span>
          <input class="switch" type="checkbox" id="start-toggle" data-act="starttoggle" ${st.hasStart ? 'checked' : ''}></label>
        ${st.hasStart ? `<div class="row"><label class="main" for="start-date"><span class="t">Start</span></label><input class="datefield" type="date" id="start-date" data-act="startdate" value="${st.start}"></div>` : ''}
      </div><div class="section-f">${plural(trip.places.length, 'saved place')} in ${esc(trip.city)}. Claude groups nearby places and puts meals at sensible times. It can take up to a minute.</div></div>
      <div class="section"><div class="section-h">Anything to keep in mind?</div><div class="group"><div class="row">
        <input class="field" id="prefs" data-act="prefs" placeholder="e.g. slow mornings, vegetarian, museums on day 1" value="${esc(st.prefs)}"></div></div></div>`,
    async ok() {
      S.sheet.busy = true; renderOverlay();
      try {
        const res = await api(`/v1/trips/${trip.id}/plan`, {
          method: 'POST',
          body: { days: st.days, start_date: st.hasStart ? st.start : null, preferences: st.prefs || null },
        });
        S.trip[trip.id] = res;
        S.mapDay[trip.id] = 0;
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
    body: () => `<div class="section"><div class="group"><pre id="share-text" style="margin:0;padding:12px 16px;white-space:pre-wrap;font-family:var(--mono);font-size:12px;line-height:1.5;overflow-wrap:anywhere">${esc(text)}</pre></div>
      <div class="section-f">Each place links to Google Maps, so friends can save it there.</div></div>`,
    async ok() { await copy(text, $('#share-text')); closeSheet(); },
  });
}

function renameSheet(trip) {
  openSheet({
    type: 'form', title: 'Rename trip', confirm: 'Save',
    body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="rename" value="${esc(trip.name)}" maxlength="120"></div></div></div>`,
    async ok() {
      const name = $('#rename').value.trim();
      if (!name) return;
      S.trip[trip.id] = await api(`/v1/trips/${trip.id}`, { method: 'PATCH', body: { name } });
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
    S.jobs = await api('/v1/jobs?limit=40');
  } catch {
    pollTimer = setTimeout(poll, 8000); // offline for a moment; keep trying slowly
    return;
  }
  const finished = S.jobs.filter((j) => before.has(j.id) && ACTIVE.has(before.get(j.id)) && !ACTIVE.has(j.status));
  for (const job of finished) {
    if (job.status === 'done') {
      if (job.trip_id) {
        const trip = await loadTrip(job.trip_id).catch(() => null);
        if (trip) trip.places.filter((p) => new Date(p.created_at) >= new Date(job.created_at)).forEach((p) => S.newIds.add(p.id));
      }
      toast(job.added_places ? `${job.message} · ${plural(job.added_places, 'new place')}` : job.message || 'Import finished');
    } else {
      toast(job.message || 'Import failed', true);
    }
  }
  const r = route();
  const refresh = ['trips', 'imports'].includes(r.name) || (finished.length && ['trip', 'map'].includes(r.name));
  if (refresh) render();
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
      ];
      if (t.day_count) actions.push({ label: 'Clear itinerary', destructive: true, run: async () => { S.trip[t.id] = await api(`/v1/trips/${t.id}/plan`, { method: 'DELETE' }); render(); } });
      actions.push({ label: 'Delete trip', destructive: true, run: () => openSheet({
        type: 'actions', title: `Delete ${t.name} and its ${plural(t.places.length, 'place')}?`,
        actions: [{ label: 'Delete trip', destructive: true, run: async () => { await api(`/v1/trips/${t.id}`, { method: 'DELETE' }); delete S.trip[t.id]; toast('Trip deleted'); go('#/'); } }],
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
      const place = Object.values(S.trip).flatMap((t) => t.places).find((p) => p.id === el.dataset.id);
      openSheet({
        type: 'form', title: 'Search again', confirm: 'Find',
        body: () => `<div class="section"><div class="group"><div class="row"><input class="field" id="relocate-q" value="${esc(`${place.name}, ${place.city}`)}"></div></div>
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
    toast('Pinned on the map');
    render();
  } catch (e) {
    toast(e.message, true);
  }
}

document.addEventListener('click', (ev) => {
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
      await start();
    } catch (e) {
      setKey('');
      $('#setup-error').textContent = e.status === 401 ? 'That key didn’t work. Check APP_API_KEY on the server.' : e.message;
    }
  }
});

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && S.sheet) closeSheet();
  if (ev.key === 'Enter' && S.sheet && S.sheet.ok && ev.target.matches('.sheet input.field')) { ev.preventDefault(); S.sheet.ok(); }
});

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
  try { S.jobs = await api('/v1/jobs?limit=40'); } catch { /* shown by the views */ }
  schedulePoll();
  if (route().name === 'setup') location.hash = '#/';
  else render();
}

hydrateIcons(document.getElementById('tabbar'));
(async () => {
  try {
    S.config = await api('/v1/config');
  } catch (e) {
    if (e.status === 401) { location.hash = '#/setup'; render(); return; }
  }
  await start();
})();
