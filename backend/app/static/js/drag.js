// Drag and drop for the itinerary's edit mode. Rows ([data-drag-id]) live in lists (.droplist[data-day]);
// a row is lifted by its handle (.handle), follows the finger, and the others slide out of its way.
// Arrow keys on a focused handle do the same for keyboard and VoiceOver users.

const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const SLIDE = { duration: 200, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' };

const items = (list, except) => [...list.querySelectorAll(':scope > [data-drag-id]')].filter((el) => el !== except);

function position(row) {
  const list = row.closest('.droplist');
  return { day: Number(list.dataset.day), index: items(list).indexOf(row) };
}

/** Animates elements from where they were (rects) to where they are now. */
function flip(rects) {
  if (reduced.matches) return;
  rects.forEach((before, el) => {
    const now = el.getBoundingClientRect();
    const dy = before.top - now.top;
    if (Math.abs(dy) > 1) el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], SLIDE);
  });
}

function snapshot(root) {
  const rects = new Map();
  root.querySelectorAll('.droplist > [data-drag-id], .droplist > .drop-ph, .droplist > .dropempty').forEach((el) => rects.set(el, el.getBoundingClientRect()));
  return rects;
}

export function enableDrag(root, onDrop) {
  root.addEventListener('pointerdown', (ev) => {
    const handle = ev.target.closest('.handle');
    if (!handle || !root.contains(handle) || ev.button > 0) return;
    const row = handle.closest('[data-drag-id]');
    if (row) { ev.preventDefault(); lift(root, row, handle, ev, onDrop); }
  });

  root.addEventListener('keydown', (ev) => {
    const handle = ev.target.closest && ev.target.closest('.handle');
    if (!handle || !['ArrowUp', 'ArrowDown'].includes(ev.key)) return;
    ev.preventDefault();
    const row = handle.closest('[data-drag-id]');
    const lists = [...root.querySelectorAll('.droplist')];
    const { day, index } = position(row);
    const listIdx = lists.indexOf(row.closest('.droplist'));
    const count = items(lists[listIdx]).length;
    const up = ev.key === 'ArrowUp';
    if (up && index > 0) onDrop(row.dataset.dragId, day, index - 1);
    else if (!up && index < count - 1) onDrop(row.dataset.dragId, day, index + 1);
    else if (up && listIdx > 0) onDrop(row.dataset.dragId, Number(lists[listIdx - 1].dataset.day), items(lists[listIdx - 1]).length);
    else if (!up && listIdx < lists.length - 1) onDrop(row.dataset.dragId, Number(lists[listIdx + 1].dataset.day), 0);
  });
}

function lift(root, row, handle, down, onDrop) {
  const start = position(row);
  const rect = row.getBoundingClientRect();
  const grabY = down.clientY - rect.top;
  const placeholder = document.createElement('div');
  placeholder.className = 'drop-ph';
  placeholder.style.height = `${rect.height}px`;
  row.parentNode.insertBefore(placeholder, row);

  document.body.appendChild(row);
  row.classList.add('dragging');
  Object.assign(row.style, { left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px` });
  handle.setPointerCapture(down.pointerId);
  if (navigator.vibrate) navigator.vibrate(8);

  let pointerY = down.clientY;
  let scrolling = 0;
  const lists = [...root.querySelectorAll('.droplist')];

  const place = () => {
    row.style.top = `${pointerY - grabY}px`;
    // The list under the finger (or the nearest one), then the first row whose middle is below it.
    let target = lists.find((l) => { const r = l.getBoundingClientRect(); return pointerY >= r.top && pointerY <= r.bottom; });
    if (!target) {
      target = lists.reduce((best, l) => {
        const r = l.getBoundingClientRect();
        const d = Math.min(Math.abs(pointerY - r.top), Math.abs(pointerY - r.bottom));
        return !best || d < best.d ? { l, d } : best;
      }, null)?.l;
    }
    if (!target) return;
    const before = items(target, row).find((el) => { const r = el.getBoundingClientRect(); return pointerY < r.top + r.height / 2; });
    const already = before ? placeholder.nextElementSibling === before && placeholder.parentNode === target
      : placeholder.parentNode === target && !items(target, row).some((el) => placeholder.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
    if (already) return;
    const rects = snapshot(root);
    if (before) target.insertBefore(placeholder, before);
    else target.appendChild(placeholder);
    flip(rects);
  };

  const autoScroll = () => {
    const edge = 90;
    const speed = pointerY < edge ? -(edge - pointerY) / 4 : pointerY > innerHeight - edge - 70 ? (pointerY - (innerHeight - edge - 70)) / 4 : 0;
    if (speed) { window.scrollBy(0, speed); place(); }
    scrolling = requestAnimationFrame(autoScroll);
  };
  scrolling = requestAnimationFrame(autoScroll);

  const move = (ev) => { pointerY = ev.clientY; place(); };
  const drop = () => {
    cancelAnimationFrame(scrolling);
    handle.removeEventListener('pointermove', move);
    handle.removeEventListener('pointerup', drop);
    handle.removeEventListener('pointercancel', drop);
    const list = placeholder.parentNode;
    const day = Number(list.dataset.day);
    const index = [...list.children].filter((el) => el.matches('[data-drag-id]') || el === placeholder).indexOf(placeholder);
    const to = placeholder.getBoundingClientRect();
    const settle = () => {
      row.classList.remove('dragging');
      row.removeAttribute('style');
      list.replaceChild(row, placeholder);
      if (day !== start.day || index !== start.index) onDrop(row.dataset.dragId, day, index);
    };
    if (reduced.matches) { settle(); return; }
    row.animate([{ top: row.style.top }, { top: `${to.top}px` }], { duration: 160, easing: 'ease-out' }).onfinish = settle;
    row.style.top = `${to.top}px`;
  };
  handle.addEventListener('pointermove', move);
  handle.addEventListener('pointerup', drop);
  handle.addEventListener('pointercancel', drop);
}
