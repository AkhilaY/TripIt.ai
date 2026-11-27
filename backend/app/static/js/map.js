// Maps: Google Maps when the server has a browser key (GOOGLE_MAPS_BROWSER_KEY), otherwise Leaflet with
// free OpenStreetMap tiles. Both draw the same pins, routes and popups.
import { ICON } from './icons.js';

const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const live = new Set();
let googleKey = '';
let googleReady = null; // Promise<google.maps> once loading starts
let generation = 0;

/** Called once the app knows the server config. */
export function configureMaps({ googleMapsKey } = {}) {
  googleKey = googleMapsKey || '';
}

export function mapProvider() {
  return googleKey ? 'google' : 'openstreetmap';
}

export function destroyMaps() {
  generation++;
  live.forEach((m) => m.destroy());
  live.clear();
}

function pinHtml(place, label, isNew) {
  return `<div class="pin${isNew ? ' new' : ''}" style="--pc: var(--c-${place.category})">${label ? `<span class="num">${label}</span>` : ICON[place.category]}</div>`;
}

function accentColor() {
  return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#FF6B57';
}

/**
 * Renders places as pins. Options:
 *  route: draw a dashed line through the places in order and number the pins
 *  interactive: false for small preview maps
 *  popup(place): HTML for a pin's popup
 *  pad: {top, bottom} extra fit padding for controls floating over the map
 */
export function renderMap(el, places, opts = {}) {
  const located = places.filter((p) => p.latitude != null && p.longitude != null);
  if (googleKey) {
    const gen = generation;
    loadGoogle()
      .then((maps) => { if (gen === generation && el.isConnected) renderGoogle(maps, el, located, opts); })
      .catch((e) => {
        console.warn('Google Maps failed to load, using OpenStreetMap', e);
        if (gen === generation && el.isConnected) renderLeaflet(el, located, opts);
      });
  } else {
    renderLeaflet(el, located, opts);
  }
}

// ---------- OpenStreetMap (Leaflet) ----------

function renderLeaflet(el, located, { route = false, interactive = true, popup = null, newIds = new Set(), zoom = null, pad = {} }) {
  if (!window.L) {
    el.innerHTML = '<div class="loading"><span class="s">Map couldn’t load</span></div>';
    return;
  }
  const map = L.map(el, {
    zoomControl: false, dragging: interactive, scrollWheelZoom: interactive, doubleClickZoom: interactive,
    touchZoom: interactive, boxZoom: interactive, keyboard: interactive, attributionControl: true, tap: interactive,
  });
  L.tileLayer(OSM_TILES, { attribution: OSM_ATTRIBUTION, maxZoom: 19 }).addTo(map);
  live.add({ destroy: () => map.remove() });
  if (interactive) L.control.zoom({ position: 'bottomright' }).addTo(map);

  const points = located.map((p) => [p.latitude, p.longitude]);
  located.forEach((p, i) => {
    const marker = L.marker([p.latitude, p.longitude], {
      icon: L.divIcon({ className: 'pin-icon', html: pinHtml(p, route ? i + 1 : null, newIds.has(p.id)), iconSize: [30, 38], iconAnchor: [15, 38], popupAnchor: [0, -36] }),
      title: p.name,
      keyboard: interactive,
    }).addTo(map);
    if (popup && interactive) marker.bindPopup(popup(p), { closeButton: false });
  });
  if (route && points.length > 1) {
    L.polyline(points, { color: accentColor(), weight: 3, dashArray: '7 6', opacity: 0.9 }).addTo(map);
  }

  if (zoom && points.length) map.setView(points[0], zoom);
  else if (points.length === 1) map.setView(points[0], 15);
  else if (points.length) map.fitBounds(points, { paddingTopLeft: [40, pad.top || 40], paddingBottomRight: [40, pad.bottom || 40], maxZoom: 16 });
  else map.setView([20, 0], 2);
  requestAnimationFrame(() => map.invalidateSize());
}

// ---------- Google Maps ----------

function loadGoogle() {
  if (window.google && window.google.maps && window.google.maps.Map) return Promise.resolve(window.google.maps);
  if (googleReady) return googleReady;
  googleReady = new Promise((resolve, reject) => {
    const callback = `__tripitGoogleMaps${Date.now()}`;
    window[callback] = () => { delete window[callback]; resolve(window.google.maps); };
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(googleKey)}&v=weekly&loading=async&callback=${callback}`;
    script.async = true;
    script.onerror = () => { googleReady = null; reject(new Error('Google Maps script failed to load')); };
    // Google calls this when the key is rejected (wrong key, API not enabled, referrer not allowed).
    window.gm_authFailure = () => {
      console.warn('Google Maps rejected the API key; switching to OpenStreetMap.');
      googleKey = '';
      document.dispatchEvent(new CustomEvent('tripit:maps-fallback'));
    };
    document.head.appendChild(script);
  });
  return googleReady;
}

function renderGoogle(maps, el, located, { route = false, interactive = true, popup = null, newIds = new Set(), zoom = null, pad = {} }) {
  const map = new maps.Map(el, {
    center: { lat: 20, lng: 0 },
    zoom: 2,
    colorScheme: 'FOLLOW_SYSTEM',
    disableDefaultUI: true,
    zoomControl: interactive,
    zoomControlOptions: { position: maps.ControlPosition.RIGHT_CENTER },
    gestureHandling: interactive ? 'greedy' : 'none',
    keyboardShortcuts: interactive,
    clickableIcons: false,
  });
  const info = new maps.InfoWindow();
  const overlays = [];

  // HTML pins (same look as the OpenStreetMap ones) via a small OverlayView.
  class Pin extends maps.OverlayView {
    constructor(place, label) {
      super();
      this.place = place;
      this.position = new maps.LatLng(place.latitude, place.longitude);
      this.div = document.createElement('div');
      this.div.className = 'gpin';
      this.div.innerHTML = pinHtml(place, label, newIds.has(place.id));
      this.div.title = place.name;
      if (popup && interactive) {
        this.div.style.cursor = 'pointer';
        this.div.addEventListener('click', (ev) => {
          ev.stopPropagation();
          info.setContent(`<div class="gpopup">${popup(place)}</div>`);
          info.setPosition(this.position);
          info.setOptions({ pixelOffset: new maps.Size(0, -38) });
          info.open({ map });
        });
      }
    }
    onAdd() { this.getPanes().overlayMouseTarget.appendChild(this.div); }
    draw() {
      const point = this.getProjection().fromLatLngToDivPixel(this.position);
      if (point) {
        this.div.style.left = `${point.x - 15}px`;
        this.div.style.top = `${point.y - 38}px`;
      }
    }
    onRemove() { this.div.remove(); }
  }

  located.forEach((p, i) => {
    const pin = new Pin(p, route ? i + 1 : null);
    pin.setMap(map);
    overlays.push(pin);
  });

  if (route && located.length > 1) {
    overlays.push(new maps.Polyline({
      map,
      path: located.map((p) => ({ lat: p.latitude, lng: p.longitude })),
      strokeOpacity: 0,
      icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.9, strokeColor: accentColor(), strokeWeight: 3, scale: 3 }, offset: '0', repeat: '14px' }],
    }));
  }

  if (zoom && located.length) {
    map.setCenter({ lat: located[0].latitude, lng: located[0].longitude });
    map.setZoom(zoom);
  } else if (located.length === 1) {
    map.setCenter({ lat: located[0].latitude, lng: located[0].longitude });
    map.setZoom(15);
  } else if (located.length) {
    const bounds = new maps.LatLngBounds();
    located.forEach((p) => bounds.extend({ lat: p.latitude, lng: p.longitude }));
    map.fitBounds(bounds, { top: pad.top || 48, bottom: pad.bottom || 48, left: 48, right: 48 });
    maps.event.addListenerOnce(map, 'idle', () => { if (map.getZoom() > 16) map.setZoom(16); });
  }

  live.add({ destroy: () => { info.close(); overlays.forEach((o) => o.setMap(null)); } });
}
