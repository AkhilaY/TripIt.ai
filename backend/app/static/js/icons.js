// Simplified SF Symbols-style icons.
const sv = (d, extra = '') =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
const P = (d) => `<path d="${d}"/>`;

export const ICON = {
  food: sv(P('M7 3v18M4 3v5a3 3 0 0 0 6 0V3M18 21V3c-2.5 0-4 2.5-4 6v4h4')),
  cafe: sv(P('M4 9h12v4a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM16 10h1.5a2.5 2.5 0 0 1 0 5H16M8 3v3M12 3v3')),
  dessert: sv(P('M4 21h16v-8H4zM4 16c2.7 1.5 5.3 1.5 8 0s5.3-1.5 8 0M12 8v5M12 3.5v.5')),
  drinks: sv(P('M7 3h10l-.8 6.5a4.2 4.2 0 0 1-8.4 0zM12 14v7M8 21h8')),
  nightlife: sv(P('M9 18V5l11-2v13') + '<circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>'),
  attraction: sv(P('M3 21h18M4 10h16M12 3l8.5 5h-17zM6 10v8M10 10v8M14 10v8M18 10v8')),
  activity: sv('<circle cx="13" cy="4.5" r="1.8"/>' + P('M10 21l2-6-2.5-3 1.5-4.5 4 3.5 3 1M8.5 12l2-4.5')),
  nature: sv(P('M5 19c0-8 5-13.5 15-15-1 10-6.5 15-15 15zM5 19l8-8')),
  shopping: sv(P('M5 8h14l-1.2 13H6.2zM9 8V6.5a3 3 0 0 1 6 0V8')),
  stay: sv(P('M3 19V6M3 14h18v5M21 14a3.5 3.5 0 0 0-3.5-3.5H11V14') + '<circle cx="7" cy="11" r="1.5"/>'),
  other: sv(P('M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z') + '<circle cx="12" cy="9.5" r="2.5"/>'),
  back: sv(P('M15 4l-8 8 8 8'), 'stroke-width="2.6"'),
  chev: '<svg class="chev" viewBox="0 0 8 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 1l6 6-6 6"/></svg>',
  plus: sv(P('M12 5v14M5 12h14'), 'stroke-width="2.4"'),
  share: sv(P('M12 3v12M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7')),
  more: sv('<circle cx="12" cy="12" r="9.5"/><circle cx="8" cy="12" r=".6" fill="currentColor"/><circle cx="12" cy="12" r=".6" fill="currentColor"/><circle cx="16" cy="12" r=".6" fill="currentColor"/>'),
  trips: sv(P('M4 8h16v12H4zM9 8V5h6v3M4 13h16')),
  map: sv(P('M9 4L3 6.5v13.5L9 17.5l6 2.5 6-2.5V4l-6 2.5zM9 4v13.5M15 6.5V20')),
  tray: sv(P('M12 3v10M8 9l4 4 4-4M3 14l2-8h3M21 14l-2-8h-3M3 14v6h18v-6h-5a4 4 0 0 1-8 0z')),
  gear: sv('<circle cx="12" cy="12" r="3"/>' + P('M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1')),
  calendar: sv(P('M4 6h16v14H4zM4 10h16M8 3v4M16 3v4')),
  plane: sv(P('M2 16l20-8-7.5 11.5-3-5zM11.5 14.5L22 8')),
  check: sv('<circle cx="12" cy="12" r="9.5"/>' + P('M7.5 12.5l3 3 6-6.5')),
  warn: sv(P('M12 3l10 18H2zM12 10v5M12 18v.5')),
  star: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z"/></svg>',
  globe: sv('<circle cx="12" cy="12" r="9.5"/>' + P('M2.5 12h19M12 2.5c3 3 3 16 0 19M12 2.5c-3 3-3 16 0 19')),
  up: sv(P('M6 15l6-6 6 6'), 'stroke-width="2.6"'),
  down: sv(P('M6 9l6 6 6-6'), 'stroke-width="2.6"'),
  sparkle: sv(P('M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z')),
  link: sv(P('M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1')),
  pinslash: sv(P('M12 21s-7-6.2-7-11.5c0-1.3.4-2.6 1-3.6M9 3.6A7 7 0 0 1 19 9.5c0 2-1 4-2.3 5.8M3 3l18 18')),
};

export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((el) => {
    el.innerHTML = ICON[el.dataset.icon] || '';
    el.removeAttribute('data-icon');
  });
}
