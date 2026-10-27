// Users (users.manage): create from presets, change permissions, reset passwords, account rules
// (a new password at next sign-in, two-factor login required), deactivate, delete. The server enforces the rules (you can only grant what you hold, never touch super
// or yourself); this window shows them so nothing is a surprise.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h, icon } from "../dom.js";
import { when } from "../format.js";
import { button, chips, errorBox, field, form, input, loading, placeBelow, select, sheet, table } from "../ui.js";

let metaCache = null;
const meta = () => (metaCache ??= api("GET", "/api/meta/permissions"));

export function renderUsers(body, ctx) {
  const area = h("div", {}, loading());
  body.append(h("div", { class: "panel-stack" },
    h("div", { class: "toolbar" }, h("p", { class: "muted small", text: "You can only grant permissions you hold, and only manage users whose permissions you also hold." }),
      h("span", { class: "spacer" }),
      button("New user", { kind: "btn-primary btn-sm", iconName: "users", data: { action: "new-user" }, onclick: () => editUser(body, ctx, null, load) })),
    area));

  async function load() {
    try {
      const users = await api("GET", "/api/users");
      const mine = new Set(ctx.state.me.permissions);
      fill(area, table([
        { label: "User", render: (u) => h("span", {}, h("strong", { text: u.username }),
          u.is_super ? h("span", { class: "badge", text: "super" }) : null,
          u.id === ctx.state.me.id ? h("span", { class: "badge ok", text: "you" }) : null,
          u.online ? h("span", { class: "badge ok", title: "Signed in with a desktop open right now", text: "online" }) : null) },
        { label: "Status", render: (u) => h("span", { class: u.is_active ? "" : "muted",
          text: [u.is_active ? "active" : "deactivated", u.locked ? "locked" : null].filter(Boolean).join(" · ") }) },
        { label: "2FA", render: (u) => h("span", {}, u.totp_enabled ? "on" : "off",
          u.require_2fa ? h("span", { class: `badge${u.totp_enabled ? "" : " warn"}`, title: "Two-factor login is required for this account", text: "required" }) : null,
          u.must_change_password ? h("span", { class: "badge warn", title: "Must choose a new password at the next request", text: "new password due" }) : null) },
        { label: "Permissions", render: (u) => (u.is_super ? h("span", { class: "muted", text: "everything" }) : chips(u.permissions)) },
        { label: "Since", render: (u) => h("span", { class: "muted small", text: when(u.created_at) }) },
        { label: "", render: (u) => {
          const manageable = !u.is_super && u.id !== ctx.state.me.id && u.permissions.every((p) => mine.has(p));
          return manageable ? h("button", { class: "win-btn", type: "button", "aria-label": `Actions for ${u.username}`,
            dataset: { action: "user-menu", user: u.username }, onclick: (e) => userMenu(e.currentTarget, u) }, icon("apps")) : null;
        } },
      ], users, { rowKey: (u) => u.username }));
    } catch (err) {
      fill(area, errorBox(err));
    }
  }

  function userMenu(anchor, u) {
    document.querySelector(".menu")?.remove();
    const item = (text, action, fn, danger = false) => h("button", { class: `menu-item${danger ? " danger" : ""}`, type: "button",
      role: "menuitem", dataset: { action }, onclick: () => { menu.remove(); fn(); } }, h("span", { text }));
    const run = async (fn, msg) => {
      try { await fn(); ctx.toast(msg); load(); } catch (err) { ctx.toast("Couldn't do that", err.message, "error"); }
    };
    const menu = h("div", { class: "menu", role: "menu" },
      item("Permissions…", "edit", () => editUser(body, ctx, u, load)),
      u.online ? item("Open a window…", "open-window", () => openFor(body, ctx, u)) : null,
      item("Reset password…", "reset", () => resetPassword(body, u, load)),
      item("Live trading cap…", "trading-cap", () => tradingCap(body, ctx, u, load)),
      item(u.must_change_password ? "Don't require a new password" : "Require a new password at next sign-in", "rule-password", () => run(() =>
        api("PATCH", `/api/users/${u.id}`, { must_change_password: !u.must_change_password }),
        u.must_change_password ? `${u.username} keeps their password` : `${u.username} must choose a new password`)),
      item(u.require_2fa ? "Don't require two-factor login" : "Require two-factor login", "rule-2fa", () => run(() =>
        api("PATCH", `/api/users/${u.id}`, { require_2fa: !u.require_2fa }),
        u.require_2fa ? `Two-factor login is optional for ${u.username}` : `${u.username} must use two-factor login`)),
      item(u.is_active ? "Deactivate" : "Reactivate", "toggle", () => run(() =>
        api("PATCH", `/api/users/${u.id}`, { is_active: !u.is_active }), u.is_active ? `${u.username} deactivated and signed out` : `${u.username} reactivated`)),
      item("Delete…", "delete", () => deleteUser(body, u, load), true));
    document.body.append(menu);
    placeBelow(menu, anchor);
    const close = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("pointerdown", close, true); } };
    setTimeout(() => document.addEventListener("pointerdown", close, true));
  }

  on("users-changed", load, ctx.signal);
  load();
}

async function permissionPicker(ctx, chosen) {
  const m = await meta();
  const mine = new Set(ctx.state.me.permissions);
  const boxes = Object.entries(m.permissions).map(([perm, text]) => {
    const box = h("input", { type: "checkbox", value: perm, checked: chosen.includes(perm), disabled: !mine.has(perm) });
    return h("label", { class: "check perm", title: mine.has(perm) ? text : "You don't hold this permission, so you can't grant it" },
      box, h("span", {}, h("code", { text: perm }), h("span", { class: "muted small", text: ` ${text}` })));
  });
  const preset = select([["", "Choose a preset…"], ...Object.keys(m.presets).map((p) => [p, p[0].toUpperCase() + p.slice(1)])], "",
    { "aria-label": "Preset" });
  const list = h("div", { class: "perm-list" }, boxes);
  preset.addEventListener("change", () => {
    const set = new Set(m.presets[preset.value] || []);
    for (const b of list.querySelectorAll("input")) if (!b.disabled) b.checked = set.has(b.value);
  });
  return { el: h("div", { class: "panel-stack" }, preset, list),
    value: () => [...list.querySelectorAll("input:checked")].map((b) => b.value) };
}

function editUser(body, ctx, u, reload) {
  sheet(body, u ? `Permissions for ${u.username}` : "New user", (close) => {
    const holder = h("div", {}, loading());
    const name = input({ name: "username", required: true, pattern: "[a-z0-9_.\\-]{3,32}", spellcheck: "false", autocapitalize: "none" });
    const pw = input({ type: "password", name: "password", required: true, minlength: "12", autocomplete: "new-password" });
    const mustChange = h("input", { type: "checkbox", name: "must_change_password", checked: true });
    const need2fa = h("input", { type: "checkbox", name: "require_2fa" });
    let picker = null;
    permissionPicker(ctx, u?.permissions || []).then((p) => { picker = p; fill(holder, p.el); });
    return form([
      u ? null : h("div", { class: "grid-2" }, field("Username", name, "Lowercase letters, digits, _ . -"),
        field("Password", pw, "12+ characters, for their first sign-in")),
      u ? null : h("div", { class: "panel-stack" },
        h("label", { class: "check" }, mustChange, h("span", { text: "They choose their own password at first sign-in (recommended: then only they know it)" })),
        h("label", { class: "check" }, need2fa, h("span", { text: "Two-factor login required (they set it up at first sign-in)" }))),
      field("Permissions", holder),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button(u ? "Save" : "Create user", { kind: "btn-primary", type: "submit", data: { action: "save-user" } })),
    ], async () => {
      const permissions = picker ? picker.value() : [];
      if (u) await api("PATCH", `/api/users/${u.id}`, { permissions });
      else await api("POST", "/api/users", { username: name.value.trim(), password: pw.value, permissions,
        must_change_password: mustChange.checked, require_2fa: need2fa.checked });
      close();
      ctx.toast(u ? "Permissions saved" : "User created", u ? u.username : name.value.trim());
      reload();
    });
  });
}

function resetPassword(body, u, reload) {
  sheet(body, `New password for ${u.username}`, (close) => {
    const pw = input({ type: "password", required: true, minlength: "12", autocomplete: "new-password", name: "password" });
    const mustChange = h("input", { type: "checkbox", name: "must_change_password", checked: true });
    return form([h("p", { class: "muted", text: "They'll be signed out everywhere, and a lockout is cleared." }),
      field("New password (12+ characters)", pw),
      h("label", { class: "check" }, mustChange, h("span", { text: "They choose their own password when they sign in with it" })),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }), button("Set password", { kind: "btn-primary", type: "submit" }))],
    async () => {
      await api("PATCH", `/api/users/${u.id}`, { password: pw.value, must_change_password: mustChange.checked });
      close();
      reload();
    });
  });
}

function deleteUser(body, u, reload) {
  sheet(body, `Delete ${u.username}`, (close) => form([
    h("p", { text: `${u.username} is removed and signed out. Their audit history stays. This can't be undone.` }),
    h("div", { class: "actions" }, button("Cancel", { onclick: close }),
      button("Delete user", { kind: "btn-danger", type: "submit", data: { action: "confirm-delete-user" } }))],
  async () => {
    await api("DELETE", `/api/users/${u.id}`);
    close();
    reload();
  }));
}

// Someone's live-trading cap and ceiling (phase 4). Raising either needs your own 2FA code.
function tradingCap(body, ctx, u, reload) {
  sheet(body, `Live trading cap for ${u.username}`, (close) => {
    const cap = input({ name: "cap", inputmode: "decimal", value: u.live_cap || "", placeholder: "150 (the default)" });
    const ceiling = input({ name: "ceiling", inputmode: "decimal", value: u.live_cap_ceiling || "", placeholder: "no ceiling" });
    const code = input({ name: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "8", placeholder: "only to raise either" });
    return form([
      h("p", { class: "muted", text: `The most ${u.username}'s live bots may control, in USD (real money). With live.cap they may change their own cap, up to the ceiling. Empty: the default cap; no ceiling.` }),
      h("div", { class: "grid-2" }, field("Cap (USD)", cap), field("Ceiling (USD)", ceiling)),
      field("Your 2FA code", code, "Needed to raise a cap or ceiling"),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button("Save", { kind: "btn-primary", type: "submit", data: { action: "save-trading-cap" } }))],
    async () => {
      await api("PUT", `/api/users/${u.id}/trading`, { cap: cap.value.trim() || null, ceiling: ceiling.value.trim() || null, code: code.value.trim() || null });
      close();
      ctx.toast("Cap saved", u.username);
      reload();
    });
  });
}

// Open a window on someone's desktop (they see who opened it). The server checks they may use it.
function openFor(body, ctx, u) {
  sheet(body, `Open a window for ${u.username}`, (close) => {
    const choices = Object.entries(ctx.wm.panels).map(([id, def]) => [id, def.title]).sort((a, b) => a[1].localeCompare(b[1]));
    const panel = select(choices, "start", { name: "panel", "aria-label": "Window" });
    return form([
      h("p", { class: "muted", text: `It opens on ${u.username}'s desktop now, with a note saying you opened it. Only windows they're allowed to use; it's in the audit log.` }),
      field("Window", panel),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button("Open it", { kind: "btn-primary", type: "submit", data: { action: "send-window" } }))],
    async () => {
      const r = await api("POST", `/api/users/${u.id}/open-window`, { panel: panel.value });
      close();
      ctx.toast("Opened", `${ctx.wm.panels[r.opened]?.title || r.opened} for ${r.for}`);
    });
  });
}
