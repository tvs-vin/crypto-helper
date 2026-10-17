// Applying themes. A theme is data only (.ctheme): every value is checked again here before
// it becomes a CSS variable, even for themes the server already validated.

import { ICON_NAMES, setThemeIcons } from "./dom.js";

export const BUILTIN = ["dark", "light", "terminal", "template"];
const COLOR_KEYS = ["desktop", "desktop_glow", "surface", "surface_alt", "titlebar",
  "titlebar_active", "taskbar", "border", "border_strong", "text", "text_muted", "heading",
  "accent", "accent_hover", "accent_text", "positive", "negative", "warning", "focus", "overlay",
  "selection"];
const COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const FONT_STACKS = {
  "Inter": '"Inter", system-ui, sans-serif',
  "Mona Sans": '"Mona Sans", "Inter", system-ui, sans-serif',
  "JetBrains Mono": '"JetBrains Mono", ui-monospace, monospace',
  "system-ui": "system-ui, sans-serif",
  "sans-serif": "sans-serif",
  "serif": "Georgia, serif",
  "monospace": "ui-monospace, monospace",
};
const CACHE_KEY = "crypto-helper:last-theme";
// Optional extras (bundles): same rules as app/themes.py.
const PATH_RE = /^[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s+-]{1,600}$/;
const PNG_RE = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;
const WALLPAPER_RE = /^(builtin:[a-z0-9-]{1,32}|user:\d{1,9})$/;
let current = null;
export const currentTheme = () => current;

export function validateTheme(t) {
  const errors = [];
  if (!t || typeof t !== "object" || t.format !== "crypto-helper-theme" || t.version !== 1) {
    return ["not a crypto-helper theme"];
  }
  for (const key of COLOR_KEYS) {
    const v = t.colors?.[key];
    if (!(typeof v === "string" && (COLOR_RE.test(v) || (key === "desktop_glow" && v === "none")))) {
      errors.push(`colors.${key}`);
    }
  }
  for (const key of ["body", "heading", "mono"]) {
    if (!(t.fonts?.[key] in FONT_STACKS)) errors.push(`fonts.${key}`);
  }
  const n = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
  if (!n(t.shape?.radius, 0, 16) || !n(t.shape?.window_radius, 0, 20) || !n(t.shape?.border_width, 0, 3)) {
    errors.push("shape");
  }
  if (!["dark", "light"].includes(t.mode)) errors.push("mode");
  if (!["compact", "comfortable"].includes(t.density)) errors.push("density");
  if (!["none", "soft", "strong"].includes(t.effects?.shadow) || typeof t.effects?.glow !== "boolean") {
    errors.push("effects");
  }
  const isMap = (v) => v === undefined || (v && typeof v === "object" && !Array.isArray(v));
  if (!isMap(t.icons) || Object.entries(t.icons || {}).some(([k, v]) => !ICON_NAMES.includes(k)
    || !Array.isArray(v) || v.length < 1 || v.length > 8 || !v.every((p) => typeof p === "string" && PATH_RE.test(p)))) {
    errors.push("icons");
  }
  if (!isMap(t.icon_images) || Object.entries(t.icon_images || {}).some(([k, v]) => !ICON_NAMES.includes(k)
    || typeof v !== "string" || v.length > 22000 || !PNG_RE.test(v))) {
    errors.push("icon_images");
  }
  if (t.wallpaper != null && !(typeof t.wallpaper === "string" && WALLPAPER_RE.test(t.wallpaper))) errors.push("wallpaper");
  return errors;
}

export function applyTheme(theme) {
  const errors = validateTheme(theme);
  if (errors.length) throw new Error(`Invalid theme (${errors.join(", ")})`);
  const root = document.documentElement;
  for (const key of COLOR_KEYS) {
    const name = key === "desktop_glow" ? "--c-glow" : `--c-${key.replaceAll("_", "-")}`;
    const value = theme.colors[key];
    if (value !== "none") root.style.setProperty(name, value);
  }
  root.style.setProperty("--font-body", FONT_STACKS[theme.fonts.body]);
  root.style.setProperty("--font-heading", FONT_STACKS[theme.fonts.heading]);
  root.style.setProperty("--font-mono", FONT_STACKS[theme.fonts.mono]);
  root.style.setProperty("--radius", `${theme.shape.radius}px`);
  root.style.setProperty("--radius-window", `${theme.shape.window_radius}px`);
  root.style.setProperty("--bw", `${theme.shape.border_width}px`);
  root.dataset.mode = theme.mode;
  root.dataset.density = theme.density;
  root.dataset.shadow = theme.effects.shadow;
  root.dataset.glow = theme.effects.glow && theme.colors.desktop_glow !== "none" ? "on" : "off";
  setThemeIcons(theme.icons, theme.icon_images);
  current = theme;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(theme));
  } catch { /* storage may be unavailable; the theme still applies */ }
}

const loaded = new Map();

export async function loadBuiltin(name) {
  if (!BUILTIN.includes(name)) name = "dark";
  if (!loaded.has(name)) {
    const res = await fetch(`/static/themes/${name}.ctheme`, { credentials: "same-origin" });
    loaded.set(name, await res.json());
  }
  return loaded.get(name);
}

/** Fetch a theme by preference key: a built-in name or "custom:<id>". Falls back to Dark
 * if an uploaded theme was deleted or unpublished. */
export async function loadTheme(key) {
  const custom = /^custom:(\d+)$/.exec(key || "");
  if (!custom) return loadBuiltin(key);
  const res = await fetch(`/api/themes/${custom[1]}`, { credentials: "same-origin" });
  if (!res.ok) return loadBuiltin("dark");
  const theme = await res.json();
  return validateTheme(theme).length ? loadBuiltin("dark") : theme;
}

export async function useTheme(key) {
  const theme = await loadTheme(key);
  applyTheme(theme);
  return theme;
}

/** Save a theme object to the user's computer as a .ctheme file. */
export function downloadTheme(theme) {
  const blob = new Blob([`${JSON.stringify(theme, null, 2)}\n`], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(theme.name || "theme").replace(/[^\w.-]+/g, "-").toLowerCase()}.ctheme`;
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

/** Paint the last theme this browser used before anything else loads (no flash). */
export function applyCachedTheme() {
  try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    if (cached && validateTheme(cached).length === 0) applyTheme(cached);
  } catch { /* fall back to the stylesheet defaults */ }
}
