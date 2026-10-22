// TripIt service worker: keeps the app, your trips, their photos and the map tiles you've viewed
// available offline, and shows push notifications. The server fills in VERSION from the app's files.
const VERSION = '__VERSION__';
const SHELL = `tripit-shell-${VERSION}`;
const DATA = 'tripit-data';      // last good copy of each API response
const PHOTOS = 'tripit-photos';  // place photos (their URLs never change)
const TILES = 'tripit-tiles';    // OpenStreetMap tiles you've looked at
const LIMITS = { [PHOTOS]: 800, [TILES]: 2500, [DATA]: 300 };
const NETWORK_TIMEOUT_MS = 6000;

const SHELL_FILES = [
  '/', '/styles.css', '/manifest.webmanifest',
  '/js/app.js', '/js/api.js', '/js/icons.js', '/js/hours.js', '/js/map.js', '/js/pwa.js', '/js/drag.js', '/js/images.js',
  '/vendor/leaflet/leaflet.css', '/vendor/leaflet/leaflet.js',
  '/vendor/inter/inter-latin-wght-normal.woff2', '/vendor/inter/inter-latin-ext-wght-normal.woff2',
  '/vendor/cormorant/cormorant-garamond-latin-wght-normal.woff2', '/vendor/cormorant/cormorant-garamond-latin-wght-italic.woff2',
  '/icons/apple-touch-icon.png', '/icons/favicon.png', '/icons/icon-192.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL)
      .then((cache) => cache.addAll(SHELL_FILES.map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('tripit-shell-') && name !== SHELL) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

let puts = 0;
async function store(cacheName, request, response) {
  const cache = await caches.open(cacheName);
  await cache.put(request, response);
  if (++puts % 25 === 0) trim(cacheName);
}

async function trim(cacheName) {
  const limit = LIMITS[cacheName];
  if (!limit) return;
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(key);
}

function offlineCopy(cached) {
  const headers = new Headers(cached.headers);
  headers.set('X-TripIt-Offline', '1');
  return new Response(cached.body, { status: cached.status, statusText: cached.statusText, headers });
}

/** Network first (so data is fresh), the saved copy when offline or when the network stalls. */
async function networkFirst(event, cacheName) {
  const { request } = event;
  const network = fetch(request).then((response) => {
    if (response.ok) event.waitUntil(store(cacheName, request, response.clone()));
    return response;
  });
  const cachedPromise = caches.match(request, { cacheName });
  const slow = new Promise((resolve) => { setTimeout(resolve, NETWORK_TIMEOUT_MS); });
  try {
    return await Promise.race([network, slow.then(async () => {
      const cached = await cachedPromise;
      return cached ? offlineCopy(cached) : network;
    })]);
  } catch {
    const cached = await cachedPromise;
    if (cached) return offlineCopy(cached);
    if (request.mode === 'navigate') {
      const shell = await caches.match('/', { cacheName: SHELL });
      if (shell) return shell;
    }
    return new Response(JSON.stringify({ detail: 'You’re offline, and this hasn’t been saved on your phone yet.' }), {
      status: 503, headers: { 'Content-Type': 'application/json', 'X-TripIt-Offline': '1' },
    });
  }
}

async function cacheFirst(event, cacheName) {
  const { request } = event;
  const cached = await caches.match(request, { cacheName });
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === 'opaque') event.waitUntil(store(cacheName, request, response.clone()));
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    if (url.hostname.endsWith('tile.openstreetmap.org')) event.respondWith(cacheFirst(event, TILES));
    return; // Google Maps and other services handle their own caching
  }
  if (url.pathname === '/sw.js' || url.pathname.includes('/export.') || url.pathname.endsWith('/trip.ics') || url.pathname.endsWith('/trip.kml')) return;
  if (/^\/v1\/places\/[^/]+\/photos\//.test(url.pathname)) { event.respondWith(cacheFirst(event, PHOTOS)); return; }
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/s/')) { event.respondWith(networkFirst(event, DATA)); return; }
  if (request.mode === 'navigate') { event.respondWith(networkFirst(event, url.pathname === '/' ? SHELL : DATA)); return; }
  event.respondWith(caches.match(request, { ignoreSearch: true }).then((cached) => cached || fetch(request).then((response) => {
    if (response.ok) event.waitUntil(store(SHELL, request, response.clone()));
    return response;
  })));
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'clear-data') {
    event.waitUntil(Promise.all([caches.delete(DATA), caches.delete(PHOTOS)]));
  }
});

// ---------- Push notifications ----------

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'The Travel Edit', {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.tag,
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if ('focus' in client) {
        await client.focus();
        client.postMessage({ type: 'open', url });
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
