// Settings: your account (password, 2FA with a QR code, recovery codes, sessions), appearance
// (themes, uploads, layout), display, prices (prices.manage) and system (super).

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago, when } from "../format.js";
import { connectionsSection } from "./connections.js";
import { embedsSection } from "./embeds.js";
import { wallpaperBlock } from "./wallpapers.js";
import { MAX, MIN, STEP, applyScale, clamp, deviceScale, effectiveScale, setDeviceScale } from "../scale.js";
import { applyTheme, BUILTIN, downloadTheme, loadBuiltin, loadTheme, useTheme, validateTheme } from "../theme.js";
import { button, can, copyButton, copyable, download, emptyState, errorBox, field, form, input, loading,
  segmented, select } from "../ui.js";

export function renderSettings(body, ctx) {
  const sections = [
    ["account", "Account", account],
    ["appearance", "Appearance", appearance],
    ["display", "Display", display],
    ["notifications", "Notifications", notificationSettings],
    ...(can(ctx, "prices.manage") ? [["prices", "Prices", pricesSection]] : []),
    ...(can(ctx, "embeds.create") ? [["embeds", "Embeds", embedsSection]] : []),
    ...(can(ctx, "wallets.connect") ? [["connections", "Connections", connectionsSection]] : []),
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
  const password = input({ type: "password", name: "current_password", autocomplete: "current-password", required: true });
  fill(area,
    h("ol", { class: "steps" },
      h("li", {}, "Open an authenticator app (Aegis, Ente Auth, 2FAS, Google or Microsoft Authenticator…)."),
      h("li", {}, "Scan this code. Or choose “enter a setup key” and paste the key below."),
      h("li", {}, "Type the 6-digit code it shows to confirm.")),
    h("div", { class: "qr-row" },
      h("img", { class: "qr", src: setup.qr, alt: "QR code for your authenticator app", width: "180", height: "180" }),
      h("div", { class: "panel-stack" }, h("label", { class: "muted small", text: "Setup key" }), copyable(setup.secret),
        form([field("Code from the app", code), field("Your password", password, "Asked again to make sure it's you."),
          h("div", { class: "actions" },
          button("Cancel", { onclick: () => drawTwoFactor(area, ctx) }),
          button("Confirm", { kind: "btn-primary", type: "submit", data: { action: "confirm-2fa" } }))],
        async () => {
          const r = await api("POST", "/api/auth/totp/enable", { code: code.value.trim(), password: password.value });
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
  const fileIn = h("input", { type: "file", accept: ".ctheme,application/json,application/zip", class: "hidden", "aria-label": "Upload a theme file" });
  main.append(block("Theme", "Applies right away and follows you to every device you sign in on.", grid,
    h("div", { class: "row" },
      button("Upload .ctheme", { data: { action: "upload-theme" }, onclick: () => fileIn.click() }), fileIn,
      button("Download the template", { kind: "btn-ghost", onclick: async () => downloadTheme(await loadBuiltin("template")) }),
      button("Download current theme", { kind: "btn-ghost", onclick: async () => downloadTheme(await loadTheme(ctx.state.prefs.theme)) })),
    preview));
  main.append(wallpaperBlock(ctx));

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
    // A bundle (zip: theme + wallpapers + icons) is checked and converted by the server.
    const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    if (head[0] === 0x50 && head[1] === 0x4b && head[2] === 3 && head[3] === 4) {
      fill(preview, h("p", { class: "small", role: "status", text: `Installing “${file.name}”… (its wallpapers are converted first)` }));
      try {
        const t = await api("POST", "/api/themes/upload", file);
        await ctx.setTheme(t.key);
        fill(preview);
        ctx.toast("Theme installed", `“${t.name}” is in your themes and in use.`);
        draw();
      } catch (err) { fill(preview, errorBox(err)); }
      return;
    }
    let text;
    let theme;
    try {
      text = await file.text();
      if (text.length > 1024 * 1024) throw new Error("Theme files are at most 1 MB.");
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
      custom ? h("span", { class: "muted small", text: t.mine ? (t.published ? "yours · published" : "yours · private") : `by ${t.owner}` }) : null,
      custom && (t.wallpaper || t.icons) ? h("span", { class: "theme-extras" },
        t.wallpaper ? h("span", { class: "badge", text: "wallpaper" }) : null,
        t.icons ? h("span", { class: "badge", text: `${t.icons} icon${t.icons > 1 ? "s" : ""}` }) : null) : null));
  if (custom) {
    const acts = h("div", { class: "theme-actions" },
      // Bundles download as a bundle (with their wallpapers and icon pictures).
      button("Download", { kind: "btn-ghost btn-sm", data: { action: "download-theme" }, onclick: async () => {
        if (!t.bundle) return downloadTheme(await api("GET", `/api/themes/${t.id}`));
        const a = h("a", { href: `/api/themes/${t.id}/bundle`, download: "" });
        document.body.append(a);
        a.click();
        a.remove();
      } }));
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
  main.append(scaleBlock(ctx));

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

/** Scale: the account's default (saved, follows you) and an optional override for this
 * browser only. Dragging previews at once; the account value saves when you let go. */
function scaleBlock(ctx) {
  const slider = (value, label, action) => {
    const range = h("input", { type: "range", min: String(MIN), max: String(MAX), step: String(STEP), value: String(value),
      "aria-label": label, dataset: { action }, class: "range" });
    const out = h("output", { class: "range-value", text: `${value}%` });
    range.addEventListener("input", () => { out.textContent = `${range.value}%`; });
    return { range, out, row: h("div", { class: "row scale-row" }, range, out) };
  };
  const account = slider(clamp(ctx.state.prefs.scale ?? 100), "Scale for your account", "scale-account");
  const device = slider(effectiveScale(ctx.state.prefs), "Scale on this device", "scale-device");
  const own = h("input", { type: "checkbox", checked: deviceScale() !== null, dataset: { action: "scale-own" } });
  const sync = () => {
    device.row.classList.toggle("hidden", !own.checked);
    applyScale(effectiveScale(ctx.state.prefs));
  };
  account.range.addEventListener("input", () => { if (!own.checked) applyScale(account.range.value); });
  account.range.addEventListener("change", async () => {
    ctx.state.prefs = await api("PATCH", "/api/me/preferences", { scale: Number(account.range.value) });
    sync();
    ctx.toast(`Scale ${account.range.value}% for your account`);
  });
  device.range.addEventListener("input", () => applyScale(device.range.value));
  device.range.addEventListener("change", () => { setDeviceScale(device.range.value); sync(); });
  own.addEventListener("change", () => {
    setDeviceScale(own.checked ? device.range.value : null);
    if (!own.checked) {
      device.range.value = account.range.value;
      device.out.textContent = `${account.range.value}%`;
    }
    sync();
  });
  window.addEventListener("scale-changed", () => {  // keyboard shortcuts elsewhere
    own.checked = deviceScale() !== null;
    device.range.value = String(effectiveScale(ctx.state.prefs));
    device.out.textContent = `${device.range.value}%`;
    sync();
  }, { signal: ctx.signal });
  sync();
  return block("Scale", "Makes everything bigger or smaller. Ctrl+Alt+= and Ctrl+Alt+- change this device; Ctrl+Alt+0 goes back to your account's scale.",
    h("label", { class: "muted small", text: "Your account (every device)" }), account.row,
    h("label", { class: "check" }, own, h("span", { text: "Use a different scale on this device" })), device.row);
}

// ---- notifications -------------------------------------------------------------------------

const NOTIFY_CATEGORIES = [
  ["security", "Security", "Sign-ins from a new device, password and 2FA changes, lockouts"],
  ["system", "System", "Backups, updates, services, disk space, prices, the self-test (for super and whoever runs services)"],
  ["prices", "Price alerts", "Your own price alerts"],
  ["messages", "Messages", "Notifications sent by admins"],
];

function notificationSettings(main, ctx) {
  const admin = ctx.state.me.is_super || can(ctx, "users.manage");
  const current = () => ctx.state.prefs.notifications || { channels: {} };
  const save = async (patch, msg) => {
    ctx.state.prefs = await api("PATCH", "/api/me/preferences", { notifications: { ...current(), ...patch } });
    if (msg) ctx.toast(msg);
  };
  const box = (key, label, channel) => {
    const forced = admin && key === "security" && channel === "inapp";
    const choice = current().channels?.[key] || {};
    const on = channel === "inapp" ? forced || choice.inapp !== false : Boolean(choice.discord);
    const el = h("input", { type: "checkbox", checked: on, disabled: forced,
      dataset: { category: key, channel }, "aria-label": `${label}: ${channel === "inapp" ? "in the app" : "Discord"}` });
    el.addEventListener("change", () => {
      const channels = { ...current().channels, [key]: { ...(current().channels?.[key] || {}), [channel]: el.checked } };
      save({ channels }, `${label}${channel === "discord" ? " on Discord" : ""}: ${el.checked ? "on" : "off"}`);
    });
    return h("td", { class: "c" }, el, forced ? h("p", { class: "muted small", text: "Always on for admins" }) : null);
  };
  const rows = NOTIFY_CATEGORIES.map(([key, label, text]) => h("tr", {},
    h("td", {}, h("strong", { text: label }), h("p", { class: "muted small", text: text })),
    box(key, label, "inapp"), box(key, label, "discord")));
  main.append(block("Notifications", "What you're told about, and where. In the app they show in the bell and as a pop-up while you're signed in.",
    h("div", { class: "table-wrap" }, h("table", { class: "table notify-table" },
      h("thead", {}, h("tr", {}, h("th", { text: "Kind" }), h("th", { class: "c", text: "In the app" }), h("th", { class: "c", text: "Discord" }))),
      h("tbody", {}, rows)))));

  // Discord webhook
  const area = h("div", { class: "panel-stack" });
  const drawDiscord = async () => {
    const { discord } = await api("GET", "/api/notifications/channels");
    if (discord) {
      fill(area, h("div", { class: "row" }, h("strong", { text: discord.label }),
        discord.last_ok_at ? h("span", { class: "badge ok", text: "working" }) : null,
        discord.last_error ? h("span", { class: "badge warn", title: discord.last_error, text: "problem" }) : null),
      discord.last_error ? h("p", { class: "warn-text small", text: discord.last_error }) : null,
      h("div", { class: "row" },
        button("Send a test", { kind: "btn-sm", data: { action: "discord-test" }, onclick: async () => {
          try { await api("POST", "/api/notifications/channels/discord/test"); ctx.toast("Test sent", "Check the Discord channel."); }
          catch (err) { ctx.toast("Discord didn't take it", err.message, "error"); }
          drawDiscord();
        } }),
        button("Remove", { kind: "btn-sm btn-ghost", data: { action: "discord-remove" }, onclick: async () => {
          await api("DELETE", "/api/notifications/channels/discord"); ctx.toast("Discord webhook removed"); drawDiscord();
        } })));
      return;
    }
    const url = input({ name: "webhook", type: "password", autocomplete: "off", spellcheck: "false",
      placeholder: "discord.com/api/webhooks/…" });
    fill(area, form([
      field("Webhook address", url, "In Discord: channel settings → Integrations → Webhooks → New webhook → Copy webhook URL. Treat it like a password: anyone with it can post in that channel."),
      h("div", { class: "actions" }, button("Save webhook", { kind: "btn-primary", type: "submit", data: { action: "discord-save" } })),
    ], async () => {
      await api("PUT", "/api/notifications/channels/discord", { url: url.value.trim() });
      ctx.toast("Discord webhook saved", "Send a test to check it.");
      drawDiscord();
    }));
  };
  drawDiscord();
  main.append(block("Discord", "Notifications you tick under Discord are posted to a channel of your choice. Notifications never include your balances or values.", area));

  // Quiet hours (outside channels; critical ones still go out)
  const from = input({ type: "time", name: "quiet_from", value: current().quiet_from || "" });
  const to = input({ type: "time", name: "quiet_to", value: current().quiet_to || "" });
  const offset = -new Date().getTimezoneOffset(); // this browser's time zone
  const saveQuiet = () => save({ quiet_from: from.value || null, quiet_to: to.value || null, utc_offset_minutes: offset },
    from.value && to.value ? `Quiet ${from.value}–${to.value}` : "No quiet hours");
  from.addEventListener("change", saveQuiet);
  to.addEventListener("change", saveQuiet);
  main.append(block("Quiet hours", "Discord notifications wait until quiet hours end (critical ones still go out). Times are in this browser's time zone.",
    h("div", { class: "row" }, field("From", from), field("To", to),
      button("No quiet hours", { kind: "btn-sm btn-ghost", onclick: () => { from.value = ""; to.value = ""; saveQuiet(); } }))));
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
