// Installed-app plumbing: the service worker (offline copy, updates) and push notifications.
import { api } from './api.js';

const hasSW = 'serviceWorker' in navigator;

export function registerServiceWorker() {
  if (!hasSW) return;
  navigator.serviceWorker.register('/sw.js').catch((e) => console.warn('Service worker not registered', e));

  // A new version activates right away; reload the page the next time it's in the background, so the
  // switch never happens under someone's thumb.
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    const reload = () => { refreshing = true; location.reload(); };
    if (document.visibilityState === 'hidden') reload();
    else document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') reload(); }, { once: true });
  });

  // Tapping a notification while the app is open.
  navigator.serviceWorker.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'open' && event.data.url) {
      const url = new URL(event.data.url);
      if (url.hash && url.hash !== location.hash) location.hash = url.hash;
    }
  });
}

/** Forget saved trips and photos on this phone (after signing out). */
export function clearOfflineData() {
  if (hasSW && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: 'clear-data' });
}

const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
export const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;

/**
 * 'on' | 'off' | 'denied' | 'install' (iPhone Safari: add to Home Screen first) | 'unsupported'
 */
export async function pushState() {
  const supported = hasSW && 'PushManager' in window && 'Notification' in window;
  if (!supported) return isIOS() && !isStandalone() ? 'install' : 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    return sub && Notification.permission === 'granted' ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

function keyBytes(base64url) {
  const raw = atob(base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Must start from a tap: iOS only shows the permission prompt for a user gesture. */
export async function enablePush(publicKey) {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off';
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
  await api('/v1/push/subscriptions', { method: 'POST', body: sub.toJSON() });
  return 'on';
}

export async function disablePush() {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await api('/v1/push/subscriptions', { method: 'DELETE', body: { endpoint: sub.endpoint } }).catch(() => {});
  await sub.unsubscribe();
}
