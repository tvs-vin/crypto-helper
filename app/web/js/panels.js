// Every window the desktop can open. `perm` is checked here only to hide what you can't
// use; the server checks again on every request.

import { h } from "./dom.js";
import { renderAudit } from "./panels/audit.js";
import { renderOverview } from "./panels/overview.js";
import { renderTransfers } from "./panels/transfers.js";
import { renderWallets } from "./panels/wallets.js";
import { BUILTIN, loadBuiltin } from "./theme.js";

function coming(part, lines) {
  return (body) => body.append(h("div", { class: "placeholder" },
    h("h2", { text: `Arrives in part ${part}` }),
    h("p", { class: "muted", text: "This window is part of the next step of milestone 6. It will show:" }),
    h("ul", {}, lines.map((l) => h("li", { text: l })))));
}

export const PANELS = {
  wallets: { title: "Wallets", icon: "wallet", perm: "wallets.view", size: [760, 560], render: renderWallets },
  overview: { title: "Overview", icon: "chart", perm: "prices.view", size: [680, 560], render: renderOverview },
  transfers: { title: "Transfers", icon: "transfer", perm: "wallets.view", size: [700, 560], render: renderTransfers },
  users: {
    title: "Users", icon: "users", perm: "users.manage", size: [600, 420],
    render: coming("6c", ["Create users from presets", "Permissions, deactivate, reset password"]),
  },
  audit: { title: "Audit log", icon: "list", perm: "audit.view", size: [760, 500], render: renderAudit },
  settings: {
    title: "Settings", icon: "settings", perm: null, size: [620, 520],
    render: renderSettings,
  },
};

function segmented(options, current, onPick, label) {
  const group = h("div", { class: "segmented", role: "group", "aria-label": label });
  group.sync = (value) => {
    for (const b of group.children) b.setAttribute("aria-pressed", String(b.dataset.value === value));
  };
  for (const [value, text] of options) {
    group.append(h("button", { type: "button", "aria-pressed": String(value === current),
      dataset: { value }, text, onclick: (e) => {
        for (const b of group.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
        onPick(value);
      } }));
  }
  return group;
}

function row(title, text, control) {
  return h("div", { class: "setting-row" },
    h("div", { class: "label" }, h("h3", { text: title }), h("p", { text })), h("div", {}, control));
}

function renderSettings(body, ctx) {
  const grid = h("div", { class: "theme-grid" });
  const current = ctx.state.prefs?.theme || "dark";
  for (const name of BUILTIN) {
    const card = h("button", { class: "theme-card", type: "button", "aria-pressed": String(name === current),
      dataset: { theme: name } });
    grid.append(card);
    loadBuiltin(name).then((t) => {
      const swatch = h("div", { class: "swatch" }, h("span"), h("span"), h("span"));
      [t.colors.desktop, t.colors.surface, t.colors.accent].forEach((c, i) => {
        swatch.children[i].style.background = c;
      });
      card.append(swatch, h("span", { text: t.name }));
    });
    card.addEventListener("click", async () => {
      for (const c of grid.children) c.setAttribute("aria-pressed", String(c === card));
      await ctx.setTheme(name);
    });
  }

  const wm = ctx.wm;
  const modeControl = segmented([["floating", "Floating"], ["tiled", "Tiled"]], wm.mode,
    (v) => wm.setMode(v), "Window layout");
  const tilingControl = segmented([["master", "Main + stack"], ["grid", "Grid"]], wm.tiling,
    (v) => wm.setTiling(v), "Tiling style");
  // The taskbar and keyboard can change these too: keep the buttons in step.
  wm.addEventListener("change", () => {
    modeControl.sync(wm.mode);
    tilingControl.sync(wm.tiling);
  });
  body.append(h("div", { class: "panel-stack" },
    h("p", { class: "muted", text: "Appearance and layout. Account, users, prices and embeds join this window in part 6c." }),
    h("div", {},
      row("Theme", "Applies right away and follows you to any device you sign in on.", grid),
      row("Window layout", "Floating: drag anywhere, snap to edges and corners. Tiled: windows always share the screen.",
        modeControl),
      row("Tiling style", "How tiled mode arranges windows.", tilingControl),
      row("Keyboard", "Ctrl+Alt+← / → snap left or right, ↑ maximize, ↓ minimize, T switch layout, G tile.",
        h("span", { class: "muted", text: "" })),
      row("Signed in as", ctx.state.me?.totp_enabled ? "Two-factor login is on." : "Two-factor login is off. Turning it on comes with the full settings in 6c.",
        h("code", { text: ctx.state.me?.username || "" })))));
}
