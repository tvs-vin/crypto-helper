// The taskbar: launcher, open windows, layout controls and the account menu.

import { brandMark, fill, h, icon } from "./dom.js";

export class Taskbar {
  constructor({ wm, panels, state, onLogout }) {
    this.wm = wm;
    this.panels = panels;
    this.state = state;
    this.tasks = h("div", { class: "task-list", role: "toolbar", "aria-label": "Open windows" });
    this.modeBtn = h("button", { class: "btn btn-ghost btn-sm mode-toggle", type: "button",
      onclick: () => wm.setMode(wm.mode === "tiled" ? "floating" : "tiled") });
    this.userChip = h("button", { class: "user-chip", type: "button", "aria-haspopup": "menu",
      onclick: (e) => this.#accountMenu(e.currentTarget) });
    this.launcher = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-haspopup": "menu",
      dataset: { action: "launcher" },
      title: "Open a window", onclick: (e) => this.#launchMenu(e.currentTarget) }, icon("apps"),
      h("span", { text: "Windows" }));
    this.el = h("nav", { class: "taskbar", "aria-label": "Taskbar" },
      h("div", { class: "brand" }, brandMark(), h("span", { class: "brand-name", text: "Crypto Helper" })),
      h("span", { class: "divider" }),
      this.launcher,
      this.tasks,
      h("div", { class: "tray" },
        this.modeBtn,
        h("button", { class: "btn btn-ghost btn-sm tile-btn", type: "button", title: "Tile windows (Ctrl+Alt+G)",
          onclick: () => wm.tile() }, icon("tile"), h("span", { text: "Tile" })),
        this.userChip));
    wm.addEventListener("windows", () => this.render());
    wm.addEventListener("focus", () => this.render());
    this.onLogout = onLogout;
  }

  /** The server decides which apps this account can use (/api/auth/me `apps`); it also
   * checks every request, so this only hides what wouldn't work. */
  allowed(panel) {
    return (this.state.me?.apps || []).includes(panel);
  }

  render() {
    const wm = this.wm;
    fill(this.tasks, ...[...wm.windows.values()].map((w) => {
      const def = this.panels[w.panel];
      const current = wm.active === w.id && !w.minimized;
      const cls = ["task", current ? "active" : "", w.minimized ? "minimized" : ""];
      return h("button", { class: cls.join(" "), type: "button", dataset: { panel: w.panel, window: w.id },
        "aria-pressed": String(current),
        onclick: () => {
          if (current) wm.minimize(w.id);
          else wm.show(w.id);
        } },
        icon(def.icon), h("span", { text: w.title }));
    }));
    const tiled = wm.mode === "tiled";
    fill(this.modeBtn, icon(tiled ? "tile" : "floating"), h("span", { text: tiled ? "Tiled" : "Floating" }));
    this.modeBtn.title = `Layout: ${tiled ? "tiled" : "floating"}. Click to switch (Ctrl+Alt+T)`;
    const me = this.state.me;
    fill(this.userChip, h("span", { text: me?.username || "" }),
      me && !me.totp_enabled ? h("span", { class: "dot", title: "Two-factor login is off" }) : null);
  }

  #menu(anchor, items) {
    document.querySelector(".menu")?.remove();
    const menu = h("div", { class: "menu", role: "menu" }, items);
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    Object.assign(menu.style, { left: `${Math.max(8, left)}px`, bottom: `${window.innerHeight - r.top + 6}px` });
    const close = (e) => {
      if (e.type === "keydown" && e.key !== "Escape") return;
      if (e.type === "pointerdown" && menu.contains(e.target)) return;
      menu.remove();
      document.removeEventListener("pointerdown", close, true);
      document.removeEventListener("keydown", close, true);
    };
    setTimeout(() => {
      document.addEventListener("pointerdown", close, true);
      document.addEventListener("keydown", close, true);
    });
    menu.querySelector("button")?.focus();
    return menu;
  }

  #launchMenu(anchor) {
    const items = [h("div", { class: "menu-label", text: "Open a window" })];
    const done = () => document.querySelector(".menu")?.remove();
    for (const [id, def] of Object.entries(this.panels)) {
      if (!this.allowed(id)) continue;
      const count = this.wm.windowsOf(id).length;
      const another = (def.max || 1) > 1 && count > 0;
      // Click: open (or bring back) the window. Ctrl+click or middle-click: another one.
      const item = h("button", { class: "menu-item", role: "menuitem", type: "button", dataset: { panel: id },
        title: another ? "Ctrl+click for another window" : null,
        onclick: (e) => { done(); this.wm.open(id, null, { newWindow: e.ctrlKey || e.metaKey }); } },
        icon(def.icon), h("span", { text: def.title }),
        count ? h("span", { class: "hint", text: count > 1 ? `${count} open` : "open" }) : null);
      item.addEventListener("auxclick", (e) => { if (e.button === 1) { done(); this.wm.open(id, null, { newWindow: true }); } });
      const plus = another && this.wm.canOpenAnother(id)
        ? h("button", { class: "menu-plus", type: "button", title: `New ${def.title} window`,
          "aria-label": `New ${def.title} window`, dataset: { newWindow: id },
          onclick: () => { done(); this.wm.open(id, null, { newWindow: true }); } }, icon("plus"))
        : null;
      items.push(plus ? h("div", { class: "menu-row" }, item, plus) : item);
    }
    this.#menu(anchor, items);
  }

  #accountMenu(anchor) {
    const me = this.state.me;
    this.#menu(anchor, [
      h("div", { class: "menu-label", text: me?.username || "" }),
      h("button", { class: "menu-item", role: "menuitem", type: "button",
        onclick: () => { document.querySelector(".menu")?.remove(); this.wm.open("settings"); } },
        icon("settings"), h("span", { text: "Settings" })),
      h("button", { class: "menu-item", role: "menuitem", type: "button", dataset: { action: "logout" },
        onclick: () => { document.querySelector(".menu")?.remove(); this.onLogout(); } },
        icon("logout"), h("span", { text: "Sign out" })),
    ]);
  }
}
