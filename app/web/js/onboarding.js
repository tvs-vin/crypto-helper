// Onboarding (12a): the walkthrough. super first sets up the server (2FA, the encryption key,
// network, services, data settings, people), then every account gets to know the app (only the
// steps its permissions allow). It can shrink to a bar while you do something in a window, and
// the Getting started window reopens it at any step. The server keeps track of what's done.
//
// "Rules" mode: an account that must choose a new password or turn on 2FA sees only those steps,
// and can't close it until they're done (the server refuses everything else meanwhile).

import { api } from "./api.js";
import { emit } from "./bus.js";
import { brandMark, fill, h, icon } from "./dom.js";
import { networkEditor } from "./network.js";
import { enrol, notificationSettings, pricesSection } from "./panels/settings.js";
import { renderServices } from "./panels/services.js";
import { renderUsers } from "./panels/users.js";
import { applyScale } from "./scale.js";
import { BUILTIN } from "./theme.js";
import { button, copyable, errorBox, field, form, input, loading, segmented, select } from "./ui.js";

const SERVER_ORDER = ["welcome", "twofa", "key_backup", "network", "services", "data", "people"];
const ACCOUNT_ORDER = ["welcome", "password", "twofa", "personalise", "watchlist", "wallets", "sync",
  "alerts", "notifications", "tour"];
const FIATS = ["usd", "eur", "gbp", "jpy", "cad", "aud"];

let open = null; // the walkthrough on screen, if any

/** Open the walkthrough (or bring the one open back), at a step if given. Resolves when it
 * closes. env: { wm, state, toast, setTheme, refreshMe }. */
export function walkthrough(env, { at = null, rules = false } = {}) {
  if (open && rules && !open.rules) open.dismiss(); // a rule now applies: that comes first
  if (open) {
    open.restore(at);
    return open.done;
  }
  let resolveDone;
  const done = new Promise((r) => { resolveDone = r; });
  const life = new AbortController();
  const ctx = { ...env, signal: life.signal, saveWindowState: () => {}, windowState: {} };

  const stepsNav = h("ol", { class: "wizard-nav" });
  const title = h("h2", { id: "wizard-title" });
  const counter = h("span", { class: "muted small" });
  const content = h("div", { class: "wizard-content" });
  const back = button("Back", { data: { action: "wizard-back" } });
  const skip = button("Skip for now", { kind: "btn-ghost", data: { action: "wizard-skip" } });
  const next = button("Next", { kind: "btn-primary", data: { action: "wizard-next" } });
  const hide = h("button", { class: "win-btn", type: "button", title: "Hide for now: do something in a window, then come back",
    "aria-label": "Hide the walkthrough", dataset: { action: "wizard-hide" } }, icon("minimize"));
  const panel = h("div", { class: "wizard", role: "dialog", "aria-modal": "true", "aria-labelledby": "wizard-title" },
    h("aside", { class: "wizard-side" }, h("div", { class: "brand" }, brandMark(), h("span", { text: "Crypto Helper" })), stepsNav),
    h("section", { class: "wizard-main" },
      h("header", { class: "wizard-head" }, h("div", {}, counter, title), rules ? null : hide),
      content,
      h("footer", { class: "wizard-foot" }, back, h("span", { class: "spacer" }), skip, next)));
  const overlay = h("div", { class: "overlay wizard-overlay" }, panel);
  const pill = h("div", { class: "wizard-pill hidden", role: "status" });
  document.body.append(overlay, pill);
  document.body.dataset.walkthrough = rules ? "rules" : "open";

  let summary = null;
  let order = [];
  let index = 0;
  let stepLife = null; // each step's own lifetime: what it started stops when you move on
  const byId = () => Object.fromEntries([...(summary.server || []), ...summary.account].map((s) => [s.id, s]));

  async function refresh() {
    summary = await api("GET", "/api/onboarding");
    const have = byId();
    if (rules) {
      // Only what the account must do; a new password comes before 2FA.
      order = [summary.restricted === "password" ? "password" : null, summary.restricted ? "twofa" : null].filter(Boolean);
    } else if (summary.server) {
      order = [...SERVER_ORDER, ...ACCOUNT_ORDER.filter((s) => s !== "welcome" && s !== "twofa")].filter((s) => have[s]);
    } else {
      order = ACCOUNT_ORDER.filter((s) => have[s]);
    }
  }

  function drawNav() {
    const have = byId();
    const item = (id) => {
      const s = have[id];
      const i = order.indexOf(id);
      return h("li", { class: `${i === index ? "current" : ""}${s.done ? " done" : ""}` },
        h("button", { type: "button", disabled: rules, dataset: { step: id }, onclick: () => go(i) },
          h("span", { class: "tick", "aria-hidden": "true", text: s.done ? "✓" : String(i + 1) }),
          h("span", { text: s.title }), s.required && !s.done ? h("span", { class: "badge warn", text: "required" }) : null));
    };
    const groups = summary.server && !rules
      ? [["Your server", order.filter((s) => SERVER_ORDER.includes(s))], ["Getting to know it", order.filter((s) => !SERVER_ORDER.includes(s))]]
      : [[rules ? "Before you start" : "Getting started", order]];
    fill(stepsNav, groups.map(([label, ids]) => h("li", { class: "wizard-group" }, h("p", { class: "menu-label", text: label }),
      h("ol", {}, ids.map(item)))));
    const doneCount = summary.done;
    fill(pill, h("span", {}, h("strong", { text: "Getting started" }), ` · ${doneCount} of ${summary.total} done`),
      button("Continue", { kind: "btn-primary btn-sm", data: { action: "wizard-continue" }, onclick: () => restore() }),
      h("button", { class: "win-btn", type: "button", title: "Close: reopen it from Windows → Getting started",
        "aria-label": "Close the walkthrough", dataset: { action: "wizard-close" }, onclick: () => finish(false) }, icon("close")));
  }

  async function go(i) {
    if (i < 0) return;
    if (i >= order.length) return finish(true);
    index = i;
    const id = order[i];
    const s = byId()[id];
    stepLife?.abort();
    stepLife = new AbortController();
    life.signal.addEventListener("abort", () => stepLife.abort(), { once: true });
    title.textContent = s.title;
    counter.textContent = rules ? "" : `Step ${i + 1} of ${order.length}`;
    back.disabled = i === 0 || rules;
    const required = (id === "twofa" && s.required) || id === "password";
    skip.classList.toggle("hidden", required && !s.done);
    skip.textContent = "Skip for now";
    next.textContent = i === order.length - 1 ? (rules ? "Continue" : "Finish") : "Next";
    next.disabled = required && !s.done;
    drawNav();
    fill(content, loading());
    try {
      await STEPS[id]({ area: content, ctx: { ...ctx, signal: stepLife.signal }, env, summary, step: s, setNext, refreshStep, rules });
    } catch (err) {
      fill(content, errorBox(err));
    }
    content.querySelector("input, select, textarea, button")?.focus();
  }

  // Steps call these: setNext(label, enabled) changes the Next button; refreshStep() re-reads
  // the progress (after something got done) and updates the ticks.
  function setNext(label = null, enabled = true) {
    if (label) next.textContent = label;
    next.disabled = !enabled;
  }
  async function refreshStep() {
    const id = order[index];
    await refresh();
    index = Math.max(0, order.indexOf(id));
    const s = byId()[id];
    // Done, or (rules mode) nothing is required any more.
    if (s?.done || (rules && !summary.restricted)) { next.disabled = false; skip.classList.add("hidden"); }
    drawNav();
    emit("onboarding-changed");
  }

  async function advance() {
    const id = order[index];
    if (MARKS.has(id) && !rules) {
      try { summary = await api("POST", `/api/onboarding/steps/${id}`); } catch { /* still moves on */ }
      emit("onboarding-changed");
    }
    if (rules) {
      await refresh();
      if (!summary.restricted) return finish(true);
      return go(0);
    }
    return go(index + 1);
  }

  next.addEventListener("click", advance);
  skip.addEventListener("click", () => go(index + 1));
  back.addEventListener("click", () => go(index - 1));
  hide.addEventListener("click", () => minimize());

  function minimize() {
    overlay.classList.add("hidden");
    pill.classList.remove("hidden");
  }
  function restore(at = null) {
    overlay.classList.remove("hidden");
    pill.classList.add("hidden");
    refresh().then(() => go(at && order.includes(at) ? order.indexOf(at) : index));
  }
  ctx.minimizeWalkthrough = minimize;

  async function finish(completed) {
    if (!rules) {
      try { await api("POST", "/api/onboarding/finish"); } catch { /* ignore */ }
      if (completed) env.toast("You're all set", "Windows → Getting started shows what's left, any time.");
      emit("onboarding-changed");
    }
    life.abort();
    overlay.remove();
    pill.remove();
    open = null;
    delete document.body.dataset.walkthrough;
    resolveDone(completed);
  }

  const dismiss = () => {
    life.abort();
    overlay.remove();
    pill.remove();
    open = null;
    delete document.body.dataset.walkthrough;
    resolveDone(false);
  };
  open = { restore, done, rules, dismiss };
  (async () => {
    try {
      await refresh();
    } catch (err) {
      fill(content, errorBox(err));
      return;
    }
    // At the step asked for, else the first one not done yet.
    const undone = order.findIndex((id) => !byId()[id].done);
    go(at && order.includes(at) ? order.indexOf(at) : Math.max(0, undone));
  })();
  return done;
}

// Steps ticked by finishing them (the others tick themselves from what's set up).
const MARKS = new Set(["welcome", "personalise", "notifications", "tour", "key_backup", "network", "services", "data", "people"]);

const p = (text) => h("p", { text });
const muted = (text) => h("p", { class: "muted", text });
const doneBadge = (text) => h("p", {}, h("span", { class: "badge ok", text: "done" }), ` ${text}`);

// Open a window behind the walkthrough, and shrink the walkthrough to its bar.
function openWindow(ctx, panel, state = null) {
  const w = ctx.wm.windowsOf(panel)[0];
  if (w && state?.section) {
    ctx.wm.open(panel);
    emit("settings-show", state);
  } else {
    ctx.wm.open(panel, state && !w ? { state } : null);
  }
  ctx.minimizeWalkthrough();
}

const STEPS = {
  welcome({ area, env, summary }) {
    const me = env.state.me;
    fill(area,
      p(me.is_super
        ? "Welcome. You're super: you can see and change everything. First a few minutes on the server itself, then the app."
        : `Welcome, ${me.username}. A few short steps to get you going; skip anything and come back to it later.`),
      h("div", { class: "grid-2 wizard-promise" },
        h("div", {}, h("h4", { text: "What it does" }), h("ul", {},
          h("li", { text: "Tracks your wallets and exchange accounts, and what they're worth." }),
          h("li", { text: "Syncs balances by itself, read-only: view-only exchange keys and public addresses." }),
          h("li", { text: "Alerts you about prices, your portfolio and the server." }),
          h("li", { text: "Practises on paper: made-up balances, real prices." }))),
        h("div", {}, h("h4", { text: "What it never does" }), h("ul", {},
          h("li", { text: "Hold or move real money." }),
          h("li", { text: "Ask for a recovery (seed) phrase or a private key. Anyone who asks is trying to steal from you." }),
          h("li", { text: "Accept an exchange key that can trade or withdraw." })))),
      summary.server ? muted("Server settings here can be changed later in Settings and the Services window.") : null);
  },

  password({ area, env, refreshStep, setNext, step }) {
    if (step.done) {
      fill(area, doneBadge("You chose your own password."));
      return;
    }
    const cur = input({ type: "password", autocomplete: "current-password", required: true, name: "current" });
    const nw = input({ type: "password", autocomplete: "new-password", required: true, minlength: "12", name: "new" });
    const nw2 = input({ type: "password", autocomplete: "new-password", required: true, name: "repeat" });
    setNext(null, false);
    fill(area, p("An admin set your password. Choose your own now, so only you know it."),
      form([field("The password you were given", cur), h("div", { class: "grid-2" },
        field("New password (12+ characters)", nw, "A few random words make a strong one."), field("Repeat it", nw2)),
      h("div", { class: "actions" }, button("Save password", { kind: "btn-primary", type: "submit", data: { action: "wizard-password" } }))],
      async () => {
        if (nw.value !== nw2.value) throw new Error("The new passwords don't match.");
        await api("POST", "/api/auth/password", { current_password: cur.value, new_password: nw.value });
        env.toast("Password changed", "");
        await refreshStep();
        fill(area, doneBadge("Your password is yours alone now."));
      }));
  },

  async twofa({ area, ctx, env, refreshStep, step }) {
    const intro = () => fill(area,
      p("Two-factor login: on top of your password, a 6-digit code from an app on your phone. Someone who learns your password still can't get in."),
      step.required ? h("div", { class: "notice info", text: env.state.me.is_super ? "Required for super." : "Required for your account." }) : null,
      button("Set it up", { kind: "btn-primary", data: { action: "wizard-2fa" }, onclick: () => enrol(area, ctx, async (ok) => {
        if (ok) {
          env.state.me = await api("GET", "/api/auth/me");
          await refreshStep();
          fill(area, doneBadge("Two-factor login is on. Keep the recovery codes safe."));
        } else intro();
      }) }));
    if (step.done) fill(area, doneBadge("Two-factor login is on."));
    else intro();
  },

  key_backup({ area, setNext, step }) {
    const box = h("input", { type: "checkbox", checked: step.done, name: "key_saved" });
    setNext(null, step.done);
    box.addEventListener("change", () => setNext(null, box.checked));
    fill(area,
      p("The server encrypts its secrets (2FA, exchange keys, xpubs, Discord webhooks) with one key file. Database backups don't include it, on purpose."),
      p("Restoring a backup without the key means setting all of those up again. Copy it somewhere off this machine once, like a password manager:"),
      copyable("sudo cat /etc/crypto-helper/secret.key"),
      muted("Run that on the VM and store what it prints. Never paste it into this app, a chat or a website."),
      h("label", { class: "check" }, box, h("span", { text: "I've stored the key somewhere off this machine" })));
  },

  async network({ area, ctx }) {
    fill(area, muted("Where the web UI listens, and which networks may reach it. 127.0.0.1 is this machine only (an SSH tunnel). Add your NetBird or Tailscale address to use it from your other devices."),
      h("div", { class: "net-editor" }));
    await networkEditor(area.lastChild, ctx);
  },

  services({ area, ctx }) {
    const body = h("div", { class: "wizard-embed" });
    fill(area, muted("Backups (daily, on by default), the embed server, and the Console and Terminal windows (off unless you need them). Feature switches apply to everyone."), body);
    renderServices(body, ctx);
  },

  async data({ area, ctx }) {
    const sync = h("div", {});
    const body = h("div", { class: "wizard-embed" });
    fill(area, muted("The defaults are fine to start with. Price history: a price every 10 minutes, then hourly. Balance history: every wallet hourly, then daily. Synced wallets: every 15 minutes."),
      sync, body);
    try {
      const s = await api("GET", "/api/sync/settings");
      const every = input({ type: "number", min: "5", max: "1440", value: String(s.interval_minutes), name: "sync_every" });
      fill(sync, form([h("div", { class: "row" }, field("Sync wallets every (minutes)", every),
        button("Save", { kind: "btn-sm", type: "submit" }))], async () => {
        await api("PUT", "/api/sync/settings", { enabled: s.enabled, interval_minutes: Number(every.value) });
        ctx.toast("Sync settings saved");
      }));
    } catch { /* needs wallets.connect: super has it */ }
    await pricesSection(body, ctx);
  },

  people({ area, ctx }) {
    const body = h("div", { class: "wizard-embed" });
    fill(area, muted("Add an account for each person, with only what they need (the Viewer preset can only look). New accounts choose their own password and get this walkthrough at their first sign-in; tick “two-factor login required” for anyone who can change things."), body);
    renderUsers(body, ctx);
  },

  personalise({ area, env }) {
    const prefs = env.state.prefs || {};
    const save = async (patch) => { env.state.prefs = await api("PATCH", "/api/me/preferences", patch); emit("prices-changed"); };
    const fiat = select(FIATS.map((f) => [f, f.toUpperCase()]), prefs.fiat || "usd", { name: "fiat", "aria-label": "Currency" });
    fiat.addEventListener("change", () => save({ fiat: fiat.value }));
    const themes = BUILTIN.filter((t) => t !== "template");
    fill(area,
      field("Your currency", fiat, "Values everywhere are shown in it. Each Overview window can show another."),
      field("Theme", segmented(themes.map((t) => [t, t[0].toUpperCase() + t.slice(1)]), themes.includes(prefs.theme) ? prefs.theme : "",
        (v) => env.setTheme(v), "Theme"), "More themes, wallpapers and uploads: Settings → Appearance."),
      field("Size", segmented([["90", "Smaller"], ["100", "Normal"], ["115", "Larger"], ["130", "Largest"]], String(prefs.scale || 100),
        async (v) => { applyScale(Number(v)); await save({ scale: Number(v) }); window.dispatchEvent(new Event("scale-changed")); }, "Size"),
      "Fine-tune it in Settings → Display, or per device with Ctrl+Alt+ and Ctrl+Alt−."));
  },

  async watchlist({ area, env, refreshStep }) {
    const prefs = env.state.prefs || {};
    const chosen = new Set(prefs.watchlist || []);
    const s = await api("GET", "/api/prices/supported");
    const draw = () => fill(area,
      p("Pick the coins you want to follow. They're starred in Overview, and price alerts can watch them."),
      h("div", { class: "chips coin-picker" }, s.coins.map((c) => h("button", {
        class: `chip button${chosen.has(c.symbol) ? " on" : ""}`, type: "button", "aria-pressed": String(chosen.has(c.symbol)),
        dataset: { coin: c.symbol }, title: c.name, text: c.symbol,
        onclick: async () => {
          chosen.has(c.symbol) ? chosen.delete(c.symbol) : chosen.add(c.symbol);
          env.state.prefs = await api("PATCH", "/api/me/preferences", { watchlist: [...chosen] });
          draw();
          refreshStep();
        } }))),
      muted("Missing a coin? An admin can add any coin CoinGecko lists: Settings → Prices → Extra coins."));
    draw();
  },

  wallets({ area, ctx, refreshStep, step }) {
    const name = input({ name: "paper_name", placeholder: "Practice", maxlength: "64", required: true, value: "Practice" });
    fill(area,
      step.done ? doneBadge("You have a wallet. Add more any time in Wallets.") : null,
      p("A wallet here is a place you keep coins. Crypto Helper only ever looks: it never holds keys or moves coins."),
      h("div", { class: "choice-grid" },
        h("section", { class: "choice" }, h("h4", { text: "I don't have one yet" }),
          muted("Step by step: pick a hardware or phone wallet, set it up safely, test it, then add its public address."),
          button("Guided setup", { kind: "btn-primary btn-sm", data: { action: "wizard-wallet-guide" },
            onclick: () => { openWindow(ctx, "wallets"); setTimeout(() => emit("open-wallet-guide"), 50); } })),
        h("section", { class: "choice" }, h("h4", { text: "An exchange account" }),
          muted("Coinbase, Kraken, Gemini or Binance.US with a view-only key: balances and trades come in by themselves."),
          button("Connect an exchange", { kind: "btn-sm", onclick: () => openWindow(ctx, "settings", { section: "connections" }) })),
        h("section", { class: "choice" }, h("h4", { text: "A wallet I already have" }),
          muted("Bitcoin by xpub or address, Ethereum and its L2s by address. New wallet, then Sync from…"),
          button("Open Wallets", { kind: "btn-sm", onclick: () => openWindow(ctx, "wallets") })),
        h("section", { class: "choice" }, h("h4", { text: "Just practise" }),
          muted("A paper wallet: made-up balances you type in, real prices."),
          form([h("div", { class: "row" }, name, button("Create", { kind: "btn-sm", type: "submit", data: { action: "wizard-paper" } }))], async () => {
            await api("POST", "/api/wallets", { name: name.value.trim(), kind: "paper" });
            emit("wallets-changed");
            ctx.toast("Paper wallet created", `${name.value.trim()}: set its balances in Wallets.`);
            await refreshStep();
          }))));
  },

  sync({ area, ctx, step }) {
    fill(area,
      step.done ? doneBadge("A wallet syncs by itself.") : null,
      p("Synced wallets update by themselves: from an exchange with a view-only key, or from public addresses (Bitcoin xpub, Ethereum and its L2s)."),
      h("ol", { class: "steps" },
        h("li", { text: "Exchange: Settings → Connections → add a view-only key (each exchange has a guide)." }),
        h("li", { text: "Then in Wallets: a wallet's menu → Sync from… → pick the connection or enter addresses." })),
      h("div", { class: "row" },
        button("Open Connections", { kind: "btn-sm", onclick: () => openWindow(ctx, "settings", { section: "connections" }) }),
        button("Open Wallets", { kind: "btn-sm", onclick: () => openWindow(ctx, "wallets") }),
        button("Read the guide", { kind: "btn-sm btn-ghost", onclick: () => { ctx.wm.openHelp("guides/exchange-connections"); ctx.minimizeWalkthrough(); } })));
  },

  alerts({ area, ctx, step }) {
    fill(area,
      step.done ? doneBadge("You have an alert.") : null,
      p("Get told when a price goes above or below a level, when your portfolio moves, when a synced wallet's balance changes (catch an unexpected withdrawal), when your coins drift from the split you want, or when a coin's trend turns."),
      h("ol", { class: "steps" }, h("li", { text: "Open Alerts and press New alert." }), h("li", { text: "Pick the kind and fill in the line. Price alerts are there too (and in Overview)." })),
      button("Open Alerts", { kind: "btn-sm", data: { action: "wizard-open-alerts" }, onclick: () => openWindow(ctx, "alerts") }));
  },

  notifications({ area, ctx }) {
    const body = h("div", { class: "wizard-embed" });
    fill(area, muted("Choose what you hear about, and where: in the app, and on a Discord channel of your own."), body);
    notificationSettings(body, ctx);
  },

  tour({ area, ctx }) {
    fill(area,
      p("A quick look at the desktop: where windows open, how to arrange them, where help is."),
      button("Start the tour", { kind: "btn-primary", data: { action: "wizard-tour" }, onclick: () => tour(ctx) }));
  },
};

// ---- the desktop tour: a spotlight on each part of the taskbar ----------------------------

const TOUR = [
  ["[data-action=launcher]", "Windows", "Open any app here. Some can have several windows: the + next to them."],
  [".task-list", "Open windows", "Each open window shows here. Click one to bring it forward."],
  [".mode-toggle", "Floating or tiled", "Tiled arranges windows side by side by itself. Floating: drag them anywhere, or to an edge to snap."],
  [".bell", "Notifications", "Alerts, security events and the server's health. Choose what you get in Settings → Notifications."],
  [".user-chip", "Your account", "Settings (password, 2FA, theme, size), Help, and signing out."],
  [null, "Help everywhere", "Every window has a ? in its title bar for its own guide, and Help has the whole manual with search. Getting started (in Windows) shows what's left to set up."],
];

function tour(ctx) {
  ctx.minimizeWalkthrough();
  document.querySelector(".wizard-pill")?.classList.add("hidden");
  const ring = h("div", { class: "tour-ring" });
  const tip = h("div", { class: "tour-tip", role: "dialog", "aria-live": "polite" });
  document.body.append(ring, tip);
  let i = 0;
  const end = () => { ring.remove(); tip.remove(); document.querySelector(".wizard-pill")?.classList.remove("hidden"); };
  const show = () => {
    const [sel, title, text] = TOUR[i];
    const target = sel && document.querySelector(sel);
    const r = target?.getBoundingClientRect();
    if (r && r.width) {
      Object.assign(ring.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
      ring.classList.remove("hidden");
      Object.assign(tip.style, { left: `${Math.min(Math.max(8, r.left), window.innerWidth - 340)}px`, top: "", bottom: `${window.innerHeight - r.top + 16}px` });
    } else {
      ring.classList.add("hidden");
      Object.assign(tip.style, { left: `${window.innerWidth / 2 - 160}px`, top: "35%", bottom: "" });
    }
    fill(tip, h("p", { class: "muted small", text: `${i + 1} of ${TOUR.length}` }), h("h3", { text: title }), h("p", { text }),
      h("div", { class: "actions" },
        button("Stop", { kind: "btn-ghost btn-sm", onclick: end }),
        button(i === TOUR.length - 1 ? "Done" : "Next", { kind: "btn-primary btn-sm", data: { action: "tour-next" }, onclick: () => {
          if (++i >= TOUR.length) {
            end();
            api("POST", "/api/onboarding/steps/tour").then(() => emit("onboarding-changed")).catch(() => {});
          } else show();
        } })));
    tip.querySelector("[data-action=tour-next]").focus();
  };
  show();
}
