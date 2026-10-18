// Pure layout maths for the window manager: no DOM, so it's unit-tested with node.
// A rect is {x, y, w, h} in pixels, relative to the desktop area.

export const MIN_W = 260;
export const MIN_H = 160;

/** Which snap zone the pointer is in while dragging a window, or null. */
export function snapZone(px, py, area, edge = 18, corner = 72) {
  const left = px <= area.x + edge;
  const right = px >= area.x + area.w - edge;
  const top = py <= area.y + edge;
  const nearTop = py <= area.y + corner;
  const nearBottom = py >= area.y + area.h - corner;
  if (left && nearTop) return "tl";
  if (left && nearBottom) return "bl";
  if (right && nearTop) return "tr";
  if (right && nearBottom) return "br";
  if (left) return "left";
  if (right) return "right";
  if (top) return "max";
  return null;
}

/** The rect a window fills when dropped in a snap zone. */
export function zoneRect(zone, area, gap = 8) {
  const hw = Math.floor((area.w - gap * 3) / 2);
  const hh = Math.floor((area.h - gap * 3) / 2);
  const x2 = area.x + gap * 2 + hw;
  const y2 = area.y + gap * 2 + hh;
  const full = { x: area.x + gap, y: area.y + gap, w: area.w - gap * 2, h: area.h - gap * 2 };
  switch (zone) {
    case "max": return full;
    case "left": return { ...full, w: hw };
    case "right": return { ...full, x: x2, w: hw };
    case "tl": return { x: full.x, y: full.y, w: hw, h: hh };
    case "tr": return { x: x2, y: full.y, w: hw, h: hh };
    case "bl": return { x: full.x, y: y2, w: hw, h: hh };
    case "br": return { x: x2, y: y2, w: hw, h: hh };
    default: return null;
  }
}

/** n windows in an even grid (columns first), filling the area. */
export function gridLayout(n, area, gap = 8) {
  if (n <= 0) return [];
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const rects = [];
  for (let i = 0; i < n; i++) {
    const row = Math.floor(i / cols);
    // The last row may have fewer windows: stretch them across the full width.
    const inRow = row === rows - 1 ? n - cols * (rows - 1) : cols;
    const col = i - row * cols;
    const w = (area.w - gap * (inRow + 1)) / inRow;
    const h = (area.h - gap * (rows + 1)) / rows;
    rects.push(round({ x: area.x + gap + col * (w + gap), y: area.y + gap + row * (h + gap), w, h }));
  }
  return rects;
}

/** One large "master" window on the left, the rest stacked on the right. */
export function masterLayout(n, area, gap = 8, ratio = 0.58) {
  if (n <= 0) return [];
  if (n === 1) return [round({ x: area.x + gap, y: area.y + gap, w: area.w - gap * 2, h: area.h - gap * 2 })];
  const mw = (area.w - gap * 3) * ratio;
  const sw = area.w - gap * 3 - mw;
  const stack = n - 1;
  const sh = (area.h - gap * (stack + 1)) / stack;
  const rects = [round({ x: area.x + gap, y: area.y + gap, w: mw, h: area.h - gap * 2 })];
  for (let i = 0; i < stack; i++) {
    rects.push(round({ x: area.x + gap * 2 + mw, y: area.y + gap + i * (sh + gap), w: sw, h: sh }));
  }
  return rects;
}

/** Keep a window inside the desktop and at least its minimum size. */
export function clampRect(r, area, minW = MIN_W, minH = MIN_H) {
  const w = Math.max(minW, Math.min(r.w, area.w));
  const h = Math.max(minH, Math.min(r.h, area.h));
  const x = Math.max(area.x, Math.min(r.x, area.x + area.w - w));
  const y = Math.max(area.y, Math.min(r.y, area.y + area.h - h));
  return round({ x, y, w, h });
}

/** A new window's spot: cascade from the top-left, wrapping before it leaves the area. */
export function cascade(index, size, area, step = 28) {
  const slots = Math.max(1, Math.floor((Math.min(area.w - size.w, area.h - size.h) - 24) / step));
  const k = index % slots;
  return clampRect({ x: area.x + 24 + k * step, y: area.y + 20 + k * step, w: size.w, h: size.h }, area);
}

function round(r) {
  return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h) };
}
