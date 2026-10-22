// Read-only page for a trip someone shared with a link (/s/<token>). No API key needed.
import { ICON } from './icons.js';
import { dayHours, mondayIndex, openStatus } from './hours.js';
import { configureMaps, renderMap } from './map.js';

const CATS = {
  food: 'Food', cafe: 'Cafés', dessert: 'Sweets', drinks: 'Drinks', nightlife: 'Nightlife', attraction: 'Sights',
  activity: 'Things to do', nature: 'Outdoors', shopping: 'Shopping', stay: 'Stay', other: 'Other',
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '');
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
const tile = (color, icon, cls = '') => `<span class="tile ${cls}" style="--pc: var(--c-${color})">${ICON[icon] || ICON.other}</span>`;
const photoUrl = (photo, width) => `${photo.url}${photo.url.includes('?') ? '&' : '?'}w=${width}`;
const view = document.getElementById('view');
const token = location.pathname.split('/')[2] || '';

function fmtClock(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return `${h % 12 || 12}${m ? `:${String(m).padStart(2, '0')}` : ''} ${h < 12 ? 'AM' : 'PM'}`;
}

function links(p, trip) {
  const label = encodeURIComponent([p.resolved_name || p.name, p.address || p.city || trip.city].filter(Boolean).join(', '));
  const at = p.latitude != null ? `${p.latitude},${p.longitude}` : null;
  return {
    google: safeUrl(p.maps_url) || `https://www.google.com/maps/search/?api=1&query=${label}`,
    apple: at ? `https://maps.apple.com/?q=${encodeURIComponent(p.name)}&ll=${at}` : `https://maps.apple.com/?q=${label}`,
  };
}

function thumb(p) {
  const photo = p.photos && p.photos[0];
  return `<span class="thumb" style="--s:52px">${tile(p.category, ICON[p.category] ? p.category : 'other')}${photo
    ? `<img src="${esc(photoUrl(photo, 240))}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ''}</span>`;
}

function dayIndex(trip, day) {
  if (!trip.start_date) return null;
  const d = new Date(`${trip.start_date}T12:00:00`);
  d.setDate(d.getDate() + day - 1);
  return mondayIndex(d);
}

function placeRow(p, trip, num, dayIdx) {
  const l = links(p, trip);
  const when = p.start_time ? fmtClock(p.start_time) : cap(p.time_of_day || '');
  const hours = dayIdx != null ? dayHours(p.opening_hours, dayIdx) : (openStatus(p.opening_hours) || {}).label;
  return `<details class="srow">
    <summary class="row">${num ? `<span class="stopnum" style="--pc: var(--c-${p.category})">${num}</span>` : ''}${thumb(p)}
      <span class="main"><span class="t">${esc(p.name)}${p.must_do ? ` <span class="star-inline" aria-label="Starred">${ICON.star}</span>` : ''}</span>
      <span class="s">${esc([when, CATS[p.category], p.neighborhood].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</summary>
    <div class="sdetail">
      ${p.summary ? `<p>${esc(p.summary)}</p>` : ''}
      ${p.recommended_items.length ? `<p><b>Try:</b> ${esc(p.recommended_items.join(', '))}</p>` : ''}
      ${p.tips ? `<p><b>Tip:</b> ${esc(p.tips)}</p>` : ''}
      ${hours ? `<p class="s">${ICON.clock.replace('<svg', '<svg class="inline-ic"')}${esc(hours)}</p>` : ''}
      <div class="sbtns"><a class="btn tint small" href="${esc(l.apple)}" target="_blank" rel="noopener">Apple Maps</a>
        <a class="btn tint small" href="${esc(l.google)}" target="_blank" rel="noopener">Google Maps</a></div>
    </div></details>`;
}

function render(trip) {
  configureMaps({ googleMapsKey: trip.google_maps_key });
  document.title = `${trip.name} · The Travel Edit`;
  const cats = [...new Set(trip.places.map((p) => p.category))];
  const meta = [trip.country, plural(trip.places.length, 'place'), trip.day_count ? `${trip.day_count}-day plan` : ''].filter(Boolean).join(' · ');
  const cover = trip.cover_photo ? `<img src="${esc(photoUrl(trip.cover_photo, 1200))}" alt="" decoding="async" onerror="this.remove()">` : '';
  const located = trip.places.filter((p) => p.latitude != null);
  const canCalendar = trip.start_date && trip.day_count;

  let body = '';
  if (trip.day_count) {
    for (let d = 1; d <= trip.day_count; d++) {
      const list = trip.places.filter((p) => p.day_number === d).sort((a, b) => a.day_order - b.day_order);
      if (!list.length) continue;
      let date = '';
      if (trip.start_date) {
        const dt = new Date(`${trip.start_date}T12:00:00`);
        dt.setDate(dt.getDate() + d - 1);
        date = dt.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
      }
      body += `<div class="section"><div class="dayhead"><div>${date ? `<div class="date">${esc(date)}</div>` : ''}<div class="d">Day ${d}</div>
        <div class="dt">${esc(trip.day_titles[d - 1] || '')}</div></div></div>
        <div class="group">${list.map((p, i) => placeRow(p, trip, i + 1, dayIndex(trip, d))).join('')}</div></div>`;
    }
    const rest = trip.places.filter((p) => p.day_number == null);
    if (rest.length) body += `<div class="section"><h2 class="section-title">Also saved</h2><div class="group">${rest.map((p) => placeRow(p, trip)).join('')}</div></div>`;
  } else {
    for (const c of Object.keys(CATS)) {
      const list = trip.places.filter((p) => p.category === c);
      if (!list.length) continue;
      body += `<div class="section"><h2 class="section-title">${tile(c, c)}${CATS[c]}<span class="count">${list.length}</span></h2>
        <div class="group">${list.map((p) => placeRow(p, trip)).join('')}</div></div>`;
    }
  }

  const credits = trip.reels.filter((r) => safeUrl(r.url));
  view.innerHTML = `
    <div class="shero" style="--g1: var(--c-${cats[0] || 'other'}); --g2: var(--c-${cats[1] || 'indigo'})">${cover}
      <div class="shero-body"><span class="pill">${ICON.plane}Shared with The Travel Edit</span><h1>${esc(trip.name)}</h1><span class="meta">${esc(meta)}</span></div></div>
    ${trip.plan_notes ? `<p class="para" style="padding-top:18px">${esc(trip.plan_notes)}</p>` : '<div style="height:18px"></div>'}
    <div class="quick">
      <a class="qbtn" href="#map" data-scroll="map">${tile('green', 'map')}Map</a>
      ${canCalendar ? `<a class="qbtn" href="/s/${encodeURIComponent(token)}/trip.ics">${tile('red', 'calendar')}Calendar</a>` : ''}
      ${located.length ? `<a class="qbtn" href="/s/${encodeURIComponent(token)}/trip.kml" download>${tile('blue', 'globe')}My Maps file</a>` : ''}
    </div>
    ${located.length ? '<div class="section" id="map"><div class="group"><div class="map" style="height:280px"><div id="shared-map" style="position:absolute;inset:0"></div></div></div></div>' : ''}
    ${body}
    ${credits.length ? `<div class="section"><h2 class="section-title">From these reels</h2><div class="group">${credits.map((r) =>
      `<a class="row" href="${esc(r.url)}" target="_blank" rel="noopener"><span class="main"><span class="t" style="font-size:16px">${esc(r.title)}</span>
        <span class="s">${esc([cap(r.platform), r.creator ? `@${r.creator}` : ''].filter(Boolean).join(' · '))}</span></span>${ICON.chev}</a>`).join('')}</div></div>` : ''}
    <div class="section"><div class="section-f" style="text-align:center">Made with The Travel Edit: share a travel reel, get the places on a map and a day-by-day plan.</div></div>`;
  if (located.length) {
    renderMap(document.getElementById('shared-map'), located, {
      popup: (p) => `<strong>${esc(p.name)}</strong><br><span style="color:var(--secondary);font-size:13px">${esc(CATS[p.category])}</span>`,
    });
  }
}

view.addEventListener('click', (ev) => {
  const a = ev.target.closest('[data-scroll]');
  if (!a) return;
  ev.preventDefault();
  document.getElementById(a.dataset.scroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
});

(async () => {
  try {
    const res = await fetch(`/v1/shared/${encodeURIComponent(token)}`);
    if (!res.ok) throw new Error(res.status === 404 ? 'This trip link isn’t available. It may have been turned off.' : 'Couldn’t load this trip.');
    render(await res.json());
  } catch (e) {
    view.innerHTML = `<div class="empty">${tile('gray', 'pinslash', 'xl')}<h3>Trip unavailable</h3><p>${esc(e.message)}</p></div>`;
  }
})();
