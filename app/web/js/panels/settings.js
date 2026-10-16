// Settings: your account (password, 2FA with a QR code, recovery codes, sessions), appearance
// (themes, uploads, layout), display, prices (prices.manage) and system (super).

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago, when } from "../format.js";
import { embedsSection } from "./embeds.js";
import { applyTheme, BUILTIN, downloadTheme, loadBuiltin, loadTheme, useTheme, validateTheme } from "../theme.js";
import { button, can, copyButton, copyable, download, emptyState, errorBox, field, form, input, loading,
  segmented, select } from "../ui.js";

export function renderSettings(body, ctx) {
  const sections = [
    ["account", "Account", account],
    ["appearance", "Appearance", appearance],
    ["display", "Display", display],
    ...(can(ctx, "prices.manage") ? [["prices", "Prices", pricesSection]] : []),
    ...(can(ctx, "embeds.create") ? [["embeds", "Embeds", embedsSection]] : []),
    ...(ctx.state.me?.is_super ? [["system", "System", system]] : []),
  ];
  const main = h("div", { class: "settings-main" });
  const nav = h("nav", { class: "settings-nav", "aria-label": "Settings sections" });
  const show = (id) => {
    for (const b of nav.children) b.setAttribute("aria-current", String(b.dataset.section === id));
    const [, title, render] = sections.find((s) => s[0] === id);
    fill(main, h("h2", { class: "section-title", text: title }));
    render(main, ctx);
  };
  for (const [id, title] of sections) {
    nav.append(h("button", { type: "button", dataset: { section: id }, text: title, onclick: () => show(id) }));
  }
  body.append(h("div", { class: "settings" }, nav, main));
  show("account");
}

function block(title, text, ...content) {
  return h("section", { class: "settings-block" }, h("h3", { text: title }),
    text ? h("p", { class: "muted", text }) : null, ...content);
}

// ---- account -----------------------------------------------------------------------------

function account(main, ctx) {
  const me = ctx.state.me;
  main.append(h("p", { class: "muted" }, "Signed in as ", h("strong", { text: me.username }),
    me.is_super ? " (super: every permission)" : ` · ${me.permissions.length} permission(s)`));

  const cur = input({ type: "password", autocomplete: "current-password", required: true, name: "current" });
  const nw = input({ type: "password", autocomplete: "new-password", required: true, minlength: "12", name: "new" });
  const nw2 = input({ type: "password", autocomplete: "new-password", required: true, name: "repeat" });
  main.append(block("Password", "Changing it signs out your other sessions.",
    form([h("div", { class: "grid-3" }, field("Current", cur), field("New (12+ characters)", nw), field("Repeat", nw2)),
      h("div", { class: "actions" }, button("Change password", { kind: "btn-primary", type: "submit" }))],
    async () => {
      if (nw.value !== nw2.value) throw new Error("The new passwords don't match.");
      await api("POST", "/api/auth/password", { current_password: cur.value, new_password: nw.value });
      for (const i of [cur, nw, nw2]) i.value = "";
      ctx.toast("Password changed", "Your other sessions were signed out.");
    })));

  const twofa = h("div", {});
  main.append(block("Two-factor login", "A 6-digit code from an app on your phone, on top of your password.", twofa));
  drawTwoFactor(twofa, ctx);

  const sessions = h("div", {}, loading());
  main.append(block("Where you're signed in", "Sign out anything you don't recognise.", sessions));
  drawSessions(sessions, ctx);
}

async function drawTwoFactor(area, ctx) {
  const me = (ctx.state.me = await api("GET", "/api/auth/me"));
  ctx.refreshTaskbar?.();
  if (me.totp_enabled) {
    const pw = input({ type: "password", autocomplete: "current-password", placeholder: "Your password", "aria-label": "Password" });
    fill(area,
      h("p", {}, h("span", { class: "badge ok", text: "on" }), ` ${me.recovery_codes_left} recovery code(s) left.`),
      me.recovery_codes_left < 3 ? h("div", { class: "notice warn", text: "Running low on recovery codes: make a new set." }) : null,
      form([h("div", { class: "row" }, pw,
        button("New recovery codes", { data: { action: "new-codes" }, onclick: async (e) => {
          const r = await api("POST", "/api/auth/totp/recovery-codes", { password: pw.value }).catch((err) => { area.prepend(errorBox(err)); });
          if (r) showCodes(area, ctx, r.recovery_codes);
        } }),
        button("Turn off", { kind: "btn-danger", type: "submit", data: { action: "disable-2fa" } }))],
      async () => {
        await api("POST", "/api/auth/totp/disable", { password: pw.value });
        ctx.toast("Two-factor login is off", "", "warn");
        drawTwoFactor(area, ctx);
      }));
    return;
  }
  fill(area, h("p", {}, h("span", { class: "badge warn", text: "off" }), " Recommended, especially for super."),
    button("Turn on two-factor login", { kind: "btn-primary", data: { action: "enable-2fa" }, onclick: () => enrol(area, ctx) }));
}

async function enrol(area, ctx) {
  const setup = await api("POST", "/api/auth/totp/setup");
  const code = input({ class: "input code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "7",
    placeholder: "000000", "aria-label": "Code from the app", required: true });
  fill(area,
    h("ol", { class: "steps" },
      h("li", {}, "Open an authenticator app (Aegis, Ente Auth, 2FAS, Google or Microsoft Authenticator…)."),
      h("li", {}, "Scan this code. Or choose “enter a setup key” and paste the key below."),
      h("li", {}, "Type the 6-digit code it shows to confirm.")),
    h("div", { class: "qr-row" },
      h("img", { class: "qr", src: setup.qr, alt: "QR code for your authenticator app", width: "180", height: "180" }),
      h("div", { class: "panel-stack" }, h("label", { class: "muted small", text: "Setup key" }), copyable(setup.secret),
        form([field("Code from the app", code), h("div", { class: "actions" },
          button("Cancel", { onclick: () => drawTwoFactor(area, ctx) }),
          button("Confirm", { kind: "btn-primary", type: "submit", data: { action: "confirm-2fa" } }))],
        async () => {
          const r = await api("POST", "/api/auth/totp/enable", { code: code.value.trim() });
          ctx.state.me = { ...ctx.state.me, totp_enabled: true };
          ctx.refreshTaskbar?.(); // the "2FA is off" dot goes away now, not later
          ctx.toast("Two-factor login is on", "Your other sessions were signed out.");
          showCodes(area, ctx, r.recovery_codes);
        }))));
  code.focus();
}

function showCodes(area, ctx, codes) {
  const text = codes.join("\n");
  const list = h("ol", { class: "codes mono" }, codes.map((c) => h("li", { text: c })));
  fill(area,
    h("div", { class: "notice warn" }, h("strong", { text: "Save these recovery codes now. " }),
      "They're shown only this once. Each one gets you in once if you lose your phone. Keep them away from your phone: printed, or in a password manager."),
    list,
    h("div", { class: "row" }, copyButton(text, list, "Copy all"),
      button("Download .txt", { kind: "btn-sm", onclick: () => download("crypto-helper-recovery-codes.txt", `${text}\n`) })),
    h("div", { class: "actions" }, button("I've saved them", { kind: "btn-primary", data: { action: "codes-saved" },
      onclick: () => drawTwoFactor(area, ctx) })));
}

async function drawSessions(area, ctx) {
  try {
    const rows = await api("GET", "/api/auth/sessions");
    const others = rows.filter((r) => !r.current).length;
    fill(area, h("ul", { class: "sessions" }, rows.map((s) => h("li", {},
      h("div", {}, h("strong", { text: s.device }), s.current ? h("span", { class: "badge ok", text: "this device" }) : null,
        h("p", { class: "muted small", text: `${s.source_ip || "unknown address"} · signed in ${ago(s.created_at)}` })),
      s.current ? null : button("Sign out", { kind: "btn-sm", data: { session: s.id }, onclick: async () => {
        await api("DELETE", `/api/auth/sessions/${s.id}`);
        drawSessions(area, ctx);
      } })))),
    others ? button(`Sign out everywhere else (${others})`, { data: { action: "revoke-others" }, onclick: async () => {
      await api("POST", "/api/auth/sessions/revoke-others");
      ctx.toast("Signed out everywhere else");
      drawSessions(area, ctx);
    } }) : null);
  } catch (err) {
    fill(area, errorBox(err));
  }
}

// ---- appearance --------------------------------------------------------------------------

function appearance(main, ctx) {
  const grid = h("div", { class: "theme-grid" }, loading());
  const preview = h("div", {});
  const fileIn = h("input", { type: "file", accept: ".ctheme,application/json", class: "hidden", "aria-label": "Upload a theme file" });
  main.append(block("Theme", "Applies right away and follows you to every device you sign in on.", grid,
    h("div", { class: "row" },
      button("Upload .ctheme", { data: { action: "upload-theme" }, onclick: () => fileIn.click() }), fileIn,
      button("Download the template", { kind: "btn-ghost", onclick: async () => downloadTheme(await loadBuiltin("template")) }),
      button("Download current theme", { kind: "btn-ghost", onclick: async () => downloadTheme(await loadTheme(ctx.state.prefs.theme)) })),
    preview));

  const draw = async () => {
    const data = await api("GET", "/api/themes");
    const current = ctx.state.prefs.theme;
    const cards = [];
    for (const name of BUILTIN) {
      const t = await loadBuiltin(name);
      cards.push(themeCard(ctx, { key: name, name: t.name, colors: t.colors }, current, null));
    }
    for (const t of data.custom) cards.push(themeCard(ctx, t, current, { data, redraw: draw }));
    fill(grid, cards);
  };
  draw();

  fileIn.addEventListener("change", async () => {
    const file = fileIn.files[0];
    fileIn.value = "";
    if (!file) return;
    fill(preview);
    let text;
    let theme;
    try {
      text = await file.text();
      if (text.length > 32 * 1024) throw new Error("Theme files are at most 32 KB.");
      theme = JSON.parse(text);
      const bad = validateTheme(theme);
      if (bad.length) throw new Error(`This file isn't a valid theme (problems: ${bad.join(", ")}).`);
    } catch (err) {
      fill(preview, errorBox(err instanceof SyntaxError ? new Error("That file isn't a .ctheme (it must be JSON).") : err));
      return;
    }
    applyTheme(theme); // preview: nothing is saved yet
    fill(preview, h("div", { class: "notice" }, h("strong", { text: `Previewing “${theme.name}”. ` }),
      "Nothing is saved yet.",
      h("div", { class: "actions" },
        button("Discard", { data: { action: "discard-theme" }, onclick: async () => { await useTheme(ctx.state.prefs.theme); fill(preview); } }),
        button("Save to my themes", { kind: "btn-primary", data: { action: "save-theme" }, onclick: async () => {
          try {
            const t = await api("POST", "/api/themes", { content: text });
            await ctx.setTheme(t.key);
            fill(preview);
            ctx.toast("Theme saved", `“${t.name}” is in your themes and in use.`);
            draw();
          } catch (err) { preview.prepend(errorBox(err)); }
        } }))));
  });

  const wm = ctx.wm;
  const modeControl = segmented([["floating", "Floating"], ["tiled", "Tiled"]], wm.mode, (v) => wm.setMode(v), "Window layout");
  const tilingControl = segmented([["master", "Main + stack"], ["grid", "Grid"]], wm.tiling, (v) => wm.setTiling(v), "Tiling style");
  wm.addEventListener("change", () => { modeControl.sync(wm.mode); tilingControl.sync(wm.tiling); }, { signal: ctx.signal });
  main.append(block("Window layout", "Floating: drag anywhere, snap to edges and corners. Tiled: windows always share the screen.",
    h("div", { class: "row" }, modeControl, tilingControl)),
  block("Keyboard", null, h("p", { class: "muted small",
    text: "Ctrl+Alt+← / → snap left or right · ↑ maximize · ↓ minimize · T switch layout · G tile" })));
}

function themeCard(ctx, t, current, custom) {
  const swatch = h("div", { class: "swatch" }, h("span"), h("span"), h("span"));
  [t.colors.desktop, t.colors.surface, t.colors.accent].forEach((c, i) => { swatch.children[i].style.background = c; });
  const card = h("div", { class: "theme-card-wrap" },
    h("button", { class: "theme-card", type: "button", "aria-pressed": String(t.key === current), dataset: { theme: t.key },
      onclick: async () => {
        await ctx.setTheme(t.key);
        for (const b of card.parentNode.querySelectorAll(".theme-card")) b.setAttribute("aria-pressed", String(b === card.firstChild));
      } }, swatch, h("span", { text: t.name }),
      custom ? h("span", { class: "muted small", text: t.mine ? (t.published ? "yours · published" : "yours · private") : `by ${t.owner}` }) : null));
  if (custom) {
    const acts = h("div", { class: "theme-actions" },
      button("Download", { kind: "btn-ghost btn-sm", onclick: async () => downloadTheme(await api("GET", `/api/themes/${t.id}`)) }));
    if (custom.data.can_publish && (t.mine || t.published)) {
      acts.append(button(t.published ? "Unpublish" : "Publish", { kind: "btn-ghost btn-sm", data: { action: "publish" },
        onclick: async () => { await api("POST", `/api/themes/${t.id}/publish`, { published: !t.published }); custom.redraw(); } }));
    }
    if (t.mine) {
      acts.append(button("Delete", { kind: "btn-ghost btn-sm", data: { action: "delete-theme" }, onclick: async () => {
        await api("DELETE", `/api/themes/${t.id}`);
        if (current === t.key) await ctx.setTheme("dark");
        custom.redraw();
      } }));
    }
    card.append(acts);
  }
  return card;
}

// ---- display -----------------------------------------------------------------------------

function display(main, ctx) {
  const prefs = ctx.state.prefs;
  const save = async (patch, msg) => {
    ctx.state.prefs = await api("PATCH", "/api/me/preferences", patch);
    emit("prices-changed");
    if (msg) ctx.toast(msg);
  };
  const fiat = select(["usd", "eur", "gbp", "jpy", "cad", "aud"].map((f) => [f, f.toUpperCase()]), prefs.fiat, { "aria-label": "Currency" });
  fiat.addEventListener("change", () => save({ fiat: fiat.value }));
  main.append(block("Currency", "Used for values everywhere.", fiat));

  const cols = h("div", { class: "row" }, [["price", "Price"], ["change_24h", "24h change"], ["holdings", "Holdings"], ["value", "Value"]]
    .map(([k, label]) => {
      const box = h("input", { type: "checkbox", checked: prefs.overview.columns.includes(k), dataset: { column: k } });
      box.addEventListener("change", () => {
        const next = [...cols.querySelectorAll("input")].filter((b) => b.checked).map((b) => b.dataset.column);
        save({ overview: { ...ctx.state.prefs.overview, columns: next } });
      });
      return h("label", { class: "check" }, box, h("span", { text: label }));
    }));
  main.append(block("Overview columns", null, cols));

  const chips = h("div", { class: "chips" });
  const add = input({ placeholder: "Add a coin, e.g. BTC", "aria-label": "Add to watchlist", maxlength: "10", class: "input sm" });
  const drawWatch = () => fill(chips, ctx.state.prefs.watchlist.length ? ctx.state.prefs.watchlist.map((s) => h("span", { class: "chip" }, s,
    h("button", { class: "chip-x", type: "button", "aria-label": `Remove ${s}`, text: "×",
      onclick: async () => { await save({ watchlist: ctx.state.prefs.watchlist.filter((x) => x !== s) }); drawWatch(); } })))
    : h("span", { class: "muted small", text: "Empty: the Overview shows every coin." }));
  add.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !add.value.trim()) return;
    e.preventDefault();
    try {
      await save({ watchlist: [...ctx.state.prefs.watchlist, add.value.trim().toUpperCase()] });
      add.value = "";
      drawWatch();
    } catch (err) { ctx.toast("Can't add that", err.message, "warn"); }
  });
  drawWatch();
  main.append(block("Watchlist", "Coins always shown in the Overview (also: the ☆ in its table).", chips, add));

  main.append(block("Reset the desktop", "Closes every window and goes back to floating mode.",
    button("Reset layout", { data: { action: "reset-layout" }, onclick: async () => {
      ctx.wm.closeAll();
      ctx.wm.setMode("floating");
      ctx.state.prefs = await api("PATCH", "/api/me/preferences", { layout: { mode: "floating", tiling: "master", windows: [] } });
      ctx.toast("Desktop reset");
    } })));
}

// ---- prices ------------------------------------------------------------------------------

async function pricesSection(main, ctx) {
  const area = h("div", {}, loading());
  main.append(area);
  const { settings, stats, coarse_choices: choices } = await api("GET", "/api/prices/history/settings");
  const num = (name, value, min, max) => input({ type: "number", name, value: String(value), min: String(min), max: String(max), required: true });
  const enabled = h("input", { type: "checkbox", checked: settings.enabled, name: "enabled" });
  const fine = num("fine", settings.fine_interval_minutes, 1, 60);
  const keep = num("keep", settings.fine_keep_hours, 1, 720);
  const coarse = select(choices.map((c) => [c, c % 60 ? `${c} min` : `${c / 60} h`]), settings.coarse_interval_minutes, { name: "coarse" });
  const days = num("days", settings.coarse_keep_days, 0, 36500);
  const fiats = h("div", { class: "row" }, ["usd", "eur", "gbp", "jpy", "cad", "aud"].map((f) =>
    h("label", { class: "check" }, h("input", { type: "checkbox", value: f, checked: settings.fiats.includes(f) }), h("span", { text: f.toUpperCase() }))));
  fill(area, block("Price history",
    `Recorded in the background. Now: ${stats.points} detailed points, ${stats.candles} candles${stats.newest_point ? `, newest ${ago(stats.newest_point)}` : ""}.`,
    form([h("label", { class: "check" }, enabled, h("span", { text: "Record price history" })),
      h("div", { class: "grid-2" }, field("Detailed point every (minutes)", fine), field("Keep detailed points for (hours)", keep),
        field("Then one candle per", coarse), field("Keep candles for (days, 0 = forever)", days)),
      field("Currencies to record", fiats),
      h("div", { class: "actions" }, button("Save", { kind: "btn-primary", type: "submit", data: { action: "save-history" } }))],
    async () => {
      await api("PUT", "/api/prices/history/settings", { enabled: enabled.checked,
        fine_interval_minutes: Number(fine.value), fine_keep_hours: Number(keep.value),
        coarse_interval_minutes: Number(coarse.value), coarse_keep_days: Number(days.value),
        fiats: [...fiats.querySelectorAll("input:checked")].map((b) => b.value) });
      ctx.toast("Price history settings saved");
    })));

  const coins = h("div", {});
  area.append(block("Extra coins", "Add any coin CoinGecko lists, by the id at the end of its page address (coingecko.com/en/coins/pepe).", coins));
  const drawCoins = async () => {
    const supported = await api("GET", "/api/prices/supported");
    const extra = supported.coins.filter((c) => !c.builtin);
    const id = input({ placeholder: "coingecko id, e.g. pepe", "aria-label": "CoinGecko id", spellcheck: "false", required: true });
    const sym = input({ placeholder: "symbol (optional)", "aria-label": "Symbol", maxlength: "10", spellcheck: "false" });
    const result = h("div", {});
    const addCoin = async (confirm) => {
      fill(result);
      try {
        const c = await api("POST", "/api/coins", { coingecko_id: id.value.trim(), symbol: sym.value.trim() || null, confirm });
        ctx.toast("Coin added", `${c.symbol}: ${c.name}`);
        emit("prices-changed");
        drawCoins();
      } catch (err) {
        if (err.status === 409 && err.data?.lookalikes) {
          fill(result, h("div", { class: "notice warn" }, err.message,
            h("ul", {}, err.data.lookalikes.map((l) => h("li", { text: `${l.name} (${l.coingecko_id})` }))),
            h("div", { class: "actions" }, button("It's the right one: add it", { kind: "btn-primary", data: { action: "confirm-coin" },
              onclick: () => addCoin(true) }))));
        } else fill(result, errorBox(err));
      }
    };
    fill(coins,
      extra.length ? h("ul", { class: "sessions" }, extra.map((c) => h("li", {},
        h("div", {}, h("strong", { text: c.symbol }), ` ${c.name}`, h("p", { class: "muted small", text: c.coingecko_id })),
        button("Remove", { kind: "btn-sm", onclick: async () => { await api("DELETE", `/api/coins/${c.symbol}`); emit("prices-changed"); drawCoins(); } }))))
        : h("p", { class: "muted small", text: "None yet: only the 18 built-in coins have prices." }),
      form([h("div", { class: "row" }, id, sym, button("Add coin", { kind: "btn-primary", type: "submit", data: { action: "add-coin" } }))],
        () => addCoin(false)),
      result);
  };
  drawCoins();
}

// ---- system ------------------------------------------------------------------------------

async function system(main) {
  const area = h("div", {}, loading());
  main.append(area);
  try {
    const s = await api("GET", "/api/system/status");
    const db = s.database.revision === s.database.expected;
    const card = (title, value, note, state = "") => h("div", { class: `stat ${state}` },
      h("p", { class: "muted small", text: title }), h("strong", { text: value }), note ? h("p", { class: "muted small", text: note }) : null);
    const up = s.uptime_seconds > 86400 ? `${Math.floor(s.uptime_seconds / 86400)} d` : `${Math.floor(s.uptime_seconds / 3600)} h ${Math.floor((s.uptime_seconds % 3600) / 60)} min`;
    fill(area,
      h("div", { class: "stats" },
        card("Version", s.build, `Python ${s.python}`),
        card("Running for", up),
        card("Database", db ? `current (${s.database.revision})` : `${s.database.revision} ≠ ${s.database.expected}`, null, db ? "" : "bad"),
        card("Prices", s.prices.stale ? "stale" : s.prices.as_of ? `fresh, ${ago(s.prices.as_of)}` : "not fetched yet",
          s.prices.last_error || s.prices.source, s.prices.stale ? "warn" : ""),
        card("Price history", `${s.history.points} points · ${s.history.candles} candles`,
          s.history.newest_point ? `newest ${ago(s.history.newest_point)}` : "nothing recorded yet"),
        card("Backups", s.backups ? `${s.backups.count} kept` : "none yet",
          s.backups ? `newest ${when(new Date(s.backups.modified * 1000).toISOString().replace("Z", ""))}` : "a daily timer makes them", s.backups ? "" : "warn"),
        card("Listening on", s.listening, `clients from ${s.allowed_networks}`)),
      block("On the server", "These need root, so they run in a terminal on the VM (they ask for sudo themselves).",
        h("div", { class: "commands" }, Object.entries(s.commands).map(([k, cmd]) => h("div", { class: "row" },
          h("span", { class: "muted small cmd-label", text: k }), copyable(cmd))))));
  } catch (err) {
    fill(area, err.status === 403 ? emptyState("Only super can see this", "") : errorBox(err));
  }
}
