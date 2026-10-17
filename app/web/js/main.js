// Boot: paint the last theme, then either the setup box, the sign-in box, or straight back
// into the saved desktop. A session that ends mid-use brings the sign-in box back over the
// current windows; nothing on screen is lost.

import { api, onAuthRequired } from "./api.js";
import { emit, on } from "./bus.js";
import { h } from "./dom.js";
import { Taskbar } from "./desktop.js";
import { showAuth } from "./login.js";
import { PANELS } from "./panels.js";
import { applyCachedScale, applyScale, clamp, deviceScale, effectiveScale, setDeviceScale } from "./scale.js";
import { applyCachedTheme, useTheme } from "./theme.js";
import { applyWallpaper } from "./wallpaper.js";
import { toast } from "./toast.js";
import { WindowManager } from "./wm.js";

applyCachedTheme();
applyCachedScale();

const state = { me: null, prefs: null };
const desktop = h("main", { class: "desktop", id: "desktop" },
  h("div", { class: "desktop-empty" }, h("h2", { text: "Nothing open" }),
    h("p", { text: "Open a window from Windows in the taskbar." })));
const empty = desktop.firstChild;

let saveTimer = null;
async function saveNow() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (!state.me) return;
  try {
    state.prefs = await api("PATCH", "/api/me/preferences", { layout: wm.serialize() });
  } catch (err) {
    toast("Couldn't save your layout", err.message, "warn");
  }
}

// Closing or reloading the tab inside the debounce window would lose the last change:
// send it on the way out (keepalive lets the request outlive the page).
window.addEventListener("pagehide", () => {
  if (!saveTimer || !state.me) return;
  clearTimeout(saveTimer);
  saveTimer = null;
  api("PATCH", "/api/me/preferences", { layout: wm.serialize() }, { keepalive: true }).catch(() => {});
});

function saveLayout() {
  if (!state.me) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 600); // dragging makes many changes; save once it settles
}

async function setTheme(name) {
  await useTheme(name);
  state.prefs = await api("PATCH", "/api/me/preferences", { theme: name });
}

// After app access changes, ask the server again which windows this account may use.
async function refreshMe() {
  if (!state.me) return;
  state.me = await api("GET", "/api/auth/me");
  taskbar.render();
}

const wm = new WindowManager(desktop, PANELS, {
  state, api, toast, setTheme, refreshMe, refreshTaskbar: () => taskbar.render(),
});
const taskbar = new Taskbar({ wm, panels: PANELS, state, onLogout: logout });
wm.addEventListener("change", saveLayout);
wm.addEventListener("windows", () => empty.classList.toggle("hidden", wm.windows.size > 0));
document.body.append(desktop, taskbar.el);

async function startSession(me) {
  state.me = me;
  state.prefs = await api("GET", "/api/me/preferences");
  await useTheme(state.prefs.theme);
  applyScale(effectiveScale(state.prefs));
  applyWallpaper(desktop, state.prefs.wallpaper);
  wm.restore(state.prefs.layout, (panel) => taskbar.allowed(panel));
  taskbar.render();
  document.body.dataset.session = "ready";
  startPriceTicker();
  if (me.is_super && !me.totp_enabled) {
    toast("Turn on two-factor login", "Recommended for super: Settings → Account.", "warn", 9000);
  }
}

// Prices refresh on the server once a minute; windows showing them follow along.
let ticker = null;
function startPriceTicker() {
  clearInterval(ticker);
  ticker = setInterval(() => { if (state.me && !document.hidden) emit("prices-changed"); }, 60_000);
}

// Only ever one sign-in box: everything that needs a session waits for the same one.
let signingIn = null;
function signIn(options) {
  if (!signingIn) signingIn = showAuth(options).finally(() => { signingIn = null; });
  return signingIn;
}

onAuthRequired(async () => {
  // The session ended mid-use: the box comes up over the current windows.
  const previous = state.me?.id;
  const me = await signIn({ reason: state.me ? "expired" : null, username: state.me?.username || "" });
  if (me.id !== previous) await startSession(me); // someone else signed in: their desktop
  else state.me = me;
  taskbar.render();
});

async function logout() {
  if (saveTimer) await saveNow(); // keep the last changes before the session ends
  state.me = null; // nothing may save or refresh for the old session from here on
  try {
    await api("POST", "/api/auth/logout");
  } catch { /* already signed out */ }
  wm.closeAll();
  taskbar.render();
  document.body.dataset.session = "signed-out";
  await startSession(await signIn());
}

// Ctrl+Alt+= / - / 0: make this device bigger, smaller, or back to the account's scale.
document.addEventListener("keydown", (e) => {
  if (!e.ctrlKey || !e.altKey || !state.me) return;
  const step = { "=": 5, "+": 5, "-": -5, _: -5 }[e.key];
  if (step === undefined && e.key !== "0") return;
  e.preventDefault();
  if (e.key === "0") setDeviceScale(null);
  else setDeviceScale(clamp(effectiveScale(state.prefs) + step));
  const now = effectiveScale(state.prefs);
  applyScale(now);
  toast(`Scale ${now}%`, deviceScale() === null ? "Your account's scale" : "On this device only", "info", 1500);
  window.dispatchEvent(new Event("scale-changed"));
});

on("wallpaper-changed", () => applyWallpaper(desktop, state.prefs?.wallpaper));

async function boot() {
  let status;
  try {
    status = await api("GET", "/api/setup/status");
  } catch (err) {
    toast("Can't reach the server", err.message, "error", 0);
    return;
  }
  if (status.setup_required) return startSession(await signIn({ mode: "setup" }));
  let me;
  try {
    me = await api("GET", "/api/auth/me", undefined, { retryAuth: false });
  } catch (err) {
    if (err.status !== 401) toast("Something went wrong", err.message, "error");
    me = await signIn();
  }
  await startSession(me);
}

boot();
