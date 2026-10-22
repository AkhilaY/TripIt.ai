const KEY_STORAGE = 'tripit.apiKey';

export function getKey() {
  try { return localStorage.getItem(KEY_STORAGE) || ''; } catch { return ''; }
}

export function setKey(key) {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch { /* private mode: key lasts for this visit only */ }
  memoryKey = key;
}

let memoryKey = null;

/** Headers for calls to the server: the sign-in cookie goes along by itself; the header tells the server the
 * request came from the app (it refuses changes without it). A key saved from before accounts still works. */
export function authHeaders() {
  const key = memoryKey ?? getKey();
  return { 'X-TripIt': '1', ...(key ? { 'X-API-Key': key } : {}) };
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

let offline = false;
function network(isOffline) {
  if (isOffline === offline) return;
  offline = isOffline;
  window.dispatchEvent(new CustomEvent('tripit:network', { detail: { offline } }));
}
export const isOffline = () => offline;

export async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    network(true);
    throw new ApiError("You're offline. This needs a connection.", 0);
  }
  // The service worker marks answers it served from the copy saved on this phone.
  const saved = res.headers.get('X-TripIt-Offline') === '1';
  network(saved);
  if (saved && res.status === 503) throw new ApiError("You're offline, and this hasn't been saved on your phone yet.", 0);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* empty or non-JSON body */ }
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail[0] && detail[0].msg;
    throw new ApiError(detail || `Server error (${res.status})`, res.status);
  }
  return data;
}
