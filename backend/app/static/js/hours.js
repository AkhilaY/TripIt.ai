// Opening-hours helpers. Hours are the place's local times; "now" uses this device's clock, which is
// right when you're on the trip in that city.

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
// Rough clock windows for the itinerary's time-of-day slots, in minutes after midnight.
const SLOTS = { morning: [540, 690], lunch: [720, 840], afternoon: [840, 1020], dinner: [1080, 1260], evening: [1200, 1380] };

const toMin = (t) => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
export const mondayIndex = (date) => (date.getDay() + 6) % 7;

export function fmtTime(t) {
  const [h, m] = t.split(':').map(Number);
  if (h === 24 || (h === 0 && m === 0 && t === '24:00')) return 'midnight';
  const suffix = h < 12 ? 'AM' : 'PM';
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, '0')} ${suffix}` : `${h12} ${suffix}`;
}

const span = (r) => {
  const open = toMin(r.open);
  let close = toMin(r.close);
  if (close <= open) close += 1440; // closes after midnight
  return [open, close];
};
const is24h = (ranges) => ranges.length === 1 && ranges[0].open === '00:00' && ranges[0].close === '24:00';

export function dayHours(hours, dayIdx) {
  if (!hours || !hours.weekly) return null;
  const ranges = hours.weekly[dayIdx] || [];
  if (!ranges.length) return 'Closed';
  if (is24h(ranges)) return 'Open 24 hours';
  return ranges.map((r) => `${fmtTime(r.open)} – ${fmtTime(r.close)}`).join(', ');
}

/** {state: 'open' | 'closing' | 'closed', label} for right now, or null if hours are unknown. */
export function openStatus(hours, now = new Date()) {
  if (!hours || !hours.weekly) return null;
  const today = mondayIndex(now);
  const minute = now.getHours() * 60 + now.getMinutes();
  const yesterday = (today + 6) % 7;
  for (const r of hours.weekly[yesterday] || []) {
    const [o, c] = span(r);
    if (c > 1440 && minute < c - 1440) return closingLabel(c - 1440 - minute, r.close);
  }
  for (const r of hours.weekly[today] || []) {
    const [o, c] = span(r);
    if (minute >= o && minute < c) {
      if (is24h(hours.weekly[today])) return { state: 'open', label: 'Open 24 hours' };
      return closingLabel(c - minute, r.close);
    }
  }
  const later = (hours.weekly[today] || []).map(span).filter(([o]) => o > minute).sort((a, b) => a[0] - b[0])[0];
  if (later) return { state: 'closed', label: `Closed · opens ${fmtTime(minToStr(later[0]))}` };
  for (let i = 1; i <= 7; i++) {
    const day = (today + i) % 7;
    const ranges = hours.weekly[day] || [];
    if (ranges.length) {
      const first = ranges.map(span).sort((a, b) => a[0] - b[0])[0];
      return { state: 'closed', label: `Closed · opens ${i === 1 ? 'tomorrow' : SHORT[day]} ${fmtTime(minToStr(first[0]))}` };
    }
  }
  return { state: 'closed', label: 'Closed' };
}

/** {open: true, minutes} until it closes, or {open: false, minutes} until it opens (within a day); null if unknown. */
export function nextChange(hours, now = new Date()) {
  if (!hours || !hours.weekly) return null;
  const today = mondayIndex(now);
  const minute = now.getHours() * 60 + now.getMinutes();
  for (const r of hours.weekly[(today + 6) % 7] || []) {
    const [, c] = span(r);
    if (c > 1440 && minute < c - 1440) return { open: true, minutes: c - 1440 - minute };
  }
  const spans = (hours.weekly[today] || []).map(span).sort((a, b) => a[0] - b[0]);
  if (is24h(hours.weekly[today] || [])) return { open: true, minutes: Infinity };
  for (const [o, c] of spans) if (minute >= o && minute < c) return { open: true, minutes: c - minute };
  const later = spans.find(([o]) => o > minute);
  if (later) return { open: false, minutes: later[0] - minute };
  const tomorrow = (hours.weekly[(today + 1) % 7] || []).map(span).sort((a, b) => a[0] - b[0])[0];
  return { open: false, minutes: tomorrow ? 1440 - minute + tomorrow[0] : Infinity };
}

function closingLabel(minutesLeft, close) {
  return minutesLeft <= 60
    ? { state: 'closing', label: `Closes soon · ${fmtTime(close)}` }
    : { state: 'open', label: `Open · closes ${fmtTime(close)}` };
}

const minToStr = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

/** Warning text if the place is closed on that day or during that time-of-day slot, else null. */
export function slotConflict(hours, dayIdx, timeOfDay, startTime = null) {
  if (!hours || !hours.weekly || dayIdx == null) return null;
  const ranges = hours.weekly[dayIdx] || [];
  if (!ranges.length) return `Closed on ${DAY_NAMES[dayIdx]}s`;
  // An exact time (e.g. a reservation) is checked as the hour after it.
  const slot = startTime ? [toMin(startTime), toMin(startTime) + 60] : SLOTS[timeOfDay];
  if (!slot || is24h(ranges)) return null;
  const spans = ranges.map(span);
  if (spans.some(([o, c]) => o < slot[1] && c > slot[0])) return null;
  const first = spans.sort((a, b) => a[0] - b[0])[0];
  if (first[0] >= slot[1]) return `Opens at ${fmtTime(minToStr(first[0]))}`;
  return `Closes at ${fmtTime(minToStr(spans[spans.length - 1][1]))}`;
}

export { DAY_NAMES };
