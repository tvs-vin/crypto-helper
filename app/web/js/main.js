// Boot: paint the last theme, then either the setup box, the sign-in box, or straight back
// into the saved desktop. A session that ends mid-use brings the sign-in box back over the
// current windows; nothing on screen is lost.

import { api, onAuthRequired, onRestricted } from "./api.js";
import { emit, on } from "./bus.js";
import { h } from "./dom.js";
import { Taskbar } from "./desktop.js";
import { showAuth } from "./login.js";
import { walkthrough } from "./onboarding.js";
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
  emit("theme-changed");
  state.prefs = await api("PATCH", "/api/me/preferences", { theme: name });
}

// After app access changes, ask the server again which windows this account may use.
async function refreshMe() {
  if (!state.me) return;
  state.me = await api("GET", "/api/auth/me");
  taskbar.render();
}

// The walkthrough (onboarding) and the Getting started window share these.
const env = () => ({ wm, state, api, toast, setTheme, refreshMe, refreshTaskbar: () => taskbar.render() });
const openWalkthrough = (options = {}) => walkthrough(env(), options);

const wm = new WindowManager(desktop, PANELS, {
  state, api, toast, setTheme, refreshMe, refreshTaskbar: () => taskbar.render(), walkthrough: openWalkthrough,
});
const taskbar = new Taskbar({ wm, panels: PANELS, state, onLogout: logout });
wm.addEventListener("change", saveLayout);
wm.addEventListener("windows", () => empty.classList.toggle("hidden", wm.windows.size > 0));
document.body.append(desktop, taskbar.el);

// An account rule (a new password, 2FA) must be met before anything else loads.
async function meetRules(me) {
  state.me = me;
  while (me.restricted) {
    await walkthrough(env(), { rules: true });
    me = state.me = await api("GET", "/api/auth/me");
  }
  return me;
}
onRestricted(async () => {
  // A rule set while signed in (an admin asked for a new password): the next request finds it.
  if (state.me) await meetRules(await api("GET", "/api/auth/me"));
});

async function startSession(me) {
  me = await meetRules(me);
  state.me = me;
  state.prefs = await api("GET", "/api/me/preferences");
  await useTheme(state.prefs.theme);
  applyScale(effectiveScale(state.prefs));
  applyWallpaper(desktop, state.prefs.wallpaper);
  wm.restore(state.prefs.layout, (panel) => taskbar.allowed(panel));
  taskbar.render();
  startPriceTicker();
  startNotifications();
  try {
    const progress = await api("GET", "/api/onboarding");
    if (progress.show) openWalkthrough(); // first sign-in (or never finished): walk them through
  } catch { /* the desktop works without it */ }
  document.body.dataset.session = "ready";
  if (!me.totp_enabled && !me.requires_2fa) {
    toast("Turn on two-factor login", "Recommended: Settings → Account.", "warn", 9000);
  }
}

// Notifications: the unread count now, then new ones live (server-sent events). The browser
// reconnects by itself if the connection drops; a new session starts a new stream.
let stream = null;
async function startNotifications() {
  stream?.close();
  try {
    const { unread } = await api("GET", "/api/notifications?limit=1");
    taskbar.setUnread(unread);
  } catch { /* the bell just shows nothing */ }
  stream = new EventSource("/api/notifications/stream");
  stream.addEventListener("notification", (e) => {
    const n = JSON.parse(e.data);
    taskbar.setUnread(taskbar.unread + 1);
    toast(n.title, n.body || "", n.level === "info" ? "info" : "warn", n.level === "critical" ? 0 : 8000);
    emit("notification", n);
  });
  stream.addEventListener("signed-out", () => stream?.close());
  // Live windows (app/live.py): something changed somewhere; windows showing it reload.
  stream.addEventListener("changed", (e) => {
    for (const t of JSON.parse(e.data).topics || []) pendingTopics.add(t);
    clearTimeout(topicTimer);
    topicTimer = setTimeout(flushTopics, 300); // a burst of changes: one reload each
  });
  // Your own access changed (permissions, apps, account rules).
  stream.addEventListener("me", () => accessChanged());
  // An admin opened a window for you.
  stream.addEventListener("open-window", (e) => {
    const { panel, by } = JSON.parse(e.data);
    if (!taskbar.allowed(panel)) return;
    wm.open(panel);
    toast(`${by} opened ${PANELS[panel]?.title || panel} for you`, "", "info", 6000);
  });
}

const TOPIC_EVENTS = {
  wallets: "wallets-changed", transfers: "transfers-changed", trades: "trades-changed",
  balances: "balances-changed", connections: "connections-changed", prices: "prices-changed",
  alerts: "alerts-changed", users: "users-changed", apps: "apps-changed", services: "services-changed",
  audit: "audit-changed", embeds: "embeds-changed", onboarding: "onboarding-changed",
  themes: "themes-changed", settings: "settings-changed", backtests: "backtests-changed",
  bots: "bots-changed",
};
const pendingTopics = new Set();
let topicTimer = null;
function flushTopics() {
  const topics = [...pendingTopics];
  pendingTopics.clear();
  for (const t of topics) if (TOPIC_EVENTS[t]) emit(TOPIC_EVENTS[t]);
  document.body.dataset.lastTopics = topics.sort().join(" "); // for the browser tests
}

// The Windows menu follows your access live; windows you may no longer use close.
async function accessChanged() {
  if (!state.me) return;
  let me;
  try { me = await api("GET", "/api/auth/me"); } catch { return; }
  state.me = me;
  taskbar.render();
  const gone = [...wm.windows.values()].filter((w) => !taskbar.allowed(w.panel));
  for (const w of gone) wm.close(w.id);
  if (gone.length) {
    toast("Your access changed", `Closed: ${[...new Set(gone.map((w) => w.title))].join(", ")}.`, "warn", 9000);
  } else {
    toast("Your access changed", "The Windows menu shows what you can open now.", "info", 5000);
  }
  if (me.restricted) await api("GET", "/api/me/preferences").catch(() => {}); // brings up the rule
}
on("notifications-changed", async () => {
  try { taskbar.setUnread((await api("GET", "/api/notifications?limit=1")).unread); } catch { /* ignore */ }
});

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
  stream?.close();
  stream = null;
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
// A new theme can bring its own icons and wallpaper.
on("theme-changed", () => { taskbar.render(); applyWallpaper(desktop, state.prefs?.wallpaper); });

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
