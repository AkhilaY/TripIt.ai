// Leaflet maps with OpenStreetMap tiles (free, no key). Dark mode inverts the tiles with a CSS filter.
import { ICON } from './icons.js';

const TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const live = new Set();

export function destroyMaps() {
  live.forEach(({ map }) => map.remove());
  live.clear();
}

function pinIcon(place, label, isNew) {
  return L.divIcon({
    className: 'pin-icon',
    html: `<div class="pin${isNew ? ' new' : ''}" style="--pc: var(--c-${place.category})">${label ? `<span class="num">${label}</span>` : ICON[place.category]}</div>`,
    iconSize: [30, 38],
    iconAnchor: [15, 38],
    popupAnchor: [0, -36],
  });
}

/**
 * Renders places as pins. Options:
 *  route: draw a dashed line through the places in order and number the pins
 *  interactive: false for small preview maps
 *  popup(place): HTML for a pin's popup
 */
export function renderMap(el, places, { route = false, interactive = true, popup = null, newIds = new Set(), zoom = null } = {}) {
  if (!window.L) {
    el.innerHTML = '<div class="loading"><span class="s">Map couldn’t load</span></div>';
    return null;
  }
  const map = L.map(el, {
    zoomControl: false,
    dragging: interactive,
    scrollWheelZoom: interactive,
    doubleClickZoom: interactive,
    touchZoom: interactive,
    boxZoom: interactive,
    keyboard: interactive,
    attributionControl: true,
    tap: interactive,
  });
  const layer = L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(map);
  live.add({ map, layer });
  if (interactive) L.control.zoom({ position: 'bottomright' }).addTo(map);

  const located = places.filter((p) => p.latitude != null && p.longitude != null);
  const points = located.map((p) => [p.latitude, p.longitude]);
  located.forEach((p, i) => {
    const marker = L.marker([p.latitude, p.longitude], {
      icon: pinIcon(p, route ? i + 1 : null, newIds.has(p.id)),
      title: p.name,
      keyboard: interactive,
    }).addTo(map);
    if (popup && interactive) marker.bindPopup(popup(p), { closeButton: false });
  });
  if (route && points.length > 1) {
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#FF6B57';
    L.polyline(points, { color: accent, weight: 3, dashArray: '7 6', opacity: 0.9 }).addTo(map);
  }

  if (zoom && points.length) map.setView(points[0], zoom);
  else if (points.length === 1) map.setView(points[0], 15);
  else if (points.length) map.fitBounds(points, { padding: [40, 40], maxZoom: 16 });
  else map.setView([20, 0], 2);

  // Leaflet measures its container on creation; re-measure once layout settles.
  requestAnimationFrame(() => map.invalidateSize());
  return map;
}
