// Display scale: your account's default (preferences.scale) follows you; any browser can
// override it for itself (kept in that browser only). Applied with CSS zoom on the page.
// Pointer positions and getBoundingClientRect() are in screen pixels while styles are in page
// pixels, so code that turns one into the other goes through screenToCss().

const DEVICE_KEY = "ch-scale-device"; // this browser's own scale, or absent
const LAST_KEY = "ch-scale-last"; // last scale shown here: painted before signing in
export const MIN = 75;
export const MAX = 150;
export const STEP = 5;

export const clamp = (pct) => Math.min(MAX, Math.max(MIN, Math.round(Number(pct) / STEP) * STEP));

function read(key) {
  try {
    const v = Number(localStorage.getItem(key));
    return v ? clamp(v) : null;
  } catch {
    return null; // storage blocked: just don't remember
  }
}

export const deviceScale = () => read(DEVICE_KEY);

export function setDeviceScale(pct) {
  try {
    if (pct === null) localStorage.removeItem(DEVICE_KEY);
    else localStorage.setItem(DEVICE_KEY, String(clamp(pct)));
  } catch { /* storage blocked */ }
}

/** The scale this browser shows: its own if set, else the account's. */
export const effectiveScale = (prefs) => deviceScale() ?? clamp(prefs?.scale ?? 100);

export function applyScale(pct) {
  const z = clamp(pct) / 100;
  const root = document.documentElement;
  root.style.zoom = z === 1 ? "" : String(z);
  root.style.setProperty("--scale", String(z));
  try { localStorage.setItem(LAST_KEY, String(clamp(pct))); } catch { /* storage blocked */ }
}

export function applyCachedScale() {
  const last = read(LAST_KEY);
  if (last) applyScale(last);
}

export const zoom = () => parseFloat(document.documentElement.style.zoom) || 1;

/** Screen pixels (pointer events, getBoundingClientRect) -> page pixels (style values). */
export const screenToCss = (px) => px / zoom();
