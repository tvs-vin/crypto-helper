// The window manager: floating windows with edge/corner snapping, or automatic tiling.
// Emits "change" (layout should be saved) and "focus"/"windows" (taskbar should redraw).

import { fill, h, icon } from "./dom.js";
import { screenToCss } from "./scale.js";
import * as T from "./tiling.js";

const GAP = 8;

export class WindowManager extends EventTarget {
  constructor(desktop, panels, ctx) {
    super();
    this.desktop = desktop;
    this.panels = panels;
    this.ctx = ctx;
    // Window id -> record. The first window of an app has the app's name as its id
    // ("overview"); more are "overview:2" ... up to the app's `max` (panels.js).
    this.windows = new Map();
    this.order = [];          // tiling order (window ids)
    this.mode = "floating";
    this.tiling = "master";
    this.active = null;
    this.zTop = 10;
    this.preview = h("div", { class: "snap-preview hidden" });
    desktop.append(this.preview);
    new ResizeObserver(() => this.#onResize()).observe(desktop);
    document.addEventListener("keydown", (e) => this.#onKey(e));
  }

  // ---- geometry ---------------------------------------------------------------------------

  area() {
    return { x: 0, y: 0, w: this.desktop.clientWidth, h: this.desktop.clientHeight };
  }

  stacked() {
    return window.matchMedia("(max-width: 760px)").matches;
  }

  #place(w, rect, animate = false) {
    w.rect = rect;
    const el = w.el;
    el.classList.toggle("animating", animate);
    Object.assign(el.style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.w}px`, height: `${rect.h}px` });
    if (animate) setTimeout(() => el.classList.remove("animating"), 200);
  }

  // ---- opening and closing ----------------------------------------------------------------

  /** The open windows of one app, most recently used first. */
  windowsOf(panel) {
    return [...this.windows.values()].filter((w) => w.panel === panel).sort((a, b) => b.z - a.z);
  }

  canOpenAnother(panel) {
    return this.windowsOf(panel).length < (this.panels[panel]?.max || 1);
  }

  /** Open an app's window, or bring back the one already open. `newWindow` opens another
   * one (if the app allows more); `saved` restores a window from the saved layout. */
  open(panel, saved = null, { focus = true, quiet = false, newWindow = false } = {}) {
    const def = this.panels[panel];
    if (!def) return null;
    const open = this.windowsOf(panel);
    if (!saved && open.length && (!newWindow || !this.canOpenAnother(panel))) {
      if (newWindow) this.ctx.toast?.(`At most ${def.max || 1} ${def.title} window${(def.max || 1) > 1 ? "s" : ""}`, "", "warn");
      const w = open[0];
      if (w.minimized) this.#setMinimized(w, false);
      if (focus) this.focus(w.id);
      return w;
    }
    const id = saved?.id || this.#freeId(panel);
    if (!id || this.windows.has(id)) return this.windows.get(id) || null;
    const n = Number(id.split(":")[1] || 1);
    const label = n > 1 ? `${def.title} ${n}` : def.title;
    const body = h("div", { class: "window-body" });
    const title = h("span", { class: "title", text: label });
    const btnMax = h("button", { class: "win-btn", type: "button", title: "Maximize", "aria-label": "Maximize" }, icon("maximize"));
    const titlebar = h("div", { class: "titlebar" },
      title,
      h("button", { class: "win-btn", type: "button", title: "Minimize", "aria-label": "Minimize",
        onclick: () => this.minimize(id) }, icon("minimize")),
      btnMax,
      h("button", { class: "win-btn close", type: "button", title: "Close", "aria-label": "Close",
        onclick: () => this.close(id) }, icon("close")));
    btnMax.addEventListener("click", () => this.toggleMaximize(id));
    const el = h("section", { class: "window", role: "region", "aria-label": label, dataset: { panel, window: id } },
      titlebar, body,
      ...["n", "s", "e", "w", "ne", "nw", "se", "sw"].map((d) => h("div", { class: `resize ${d}`, dataset: { dir: d } })));
    // Aborted when the window closes: windows use it to stop timers and listeners.
    const life = new AbortController();
    const w = { id, panel, title: label, el, body, btnMax, life, rect: null, floatRect: null, minimized: false,
      maximized: false, prev: null, z: 0, state: { ...(saved?.state || {}) } };
    this.windows.set(id, w);
    this.order.push(id);
    this.desktop.append(el);

    const area = this.area();
    const rect = saved && Number.isFinite(saved.w)
      ? T.clampRect(saved, area)
      : T.cascade(this.windows.size - 1, { w: def.size[0], h: def.size[1] }, area);
    this.#place(w, rect);
    w.floatRect = rect;

    el.addEventListener("pointerdown", () => this.focus(id), true);
    titlebar.addEventListener("pointerdown", (e) => this.#startDrag(e, w));
    titlebar.addEventListener("dblclick", (e) => { if (!e.target.closest(".win-btn")) this.toggleMaximize(id); });
    for (const handle of el.querySelectorAll(".resize")) {
      handle.addEventListener("pointerdown", (e) => this.#startResize(e, w, handle.dataset.dir));
    }
    try {
      // windowState: this window's own saved settings; saveWindowState merges and saves.
      def.render(body, { ...this.ctx, wm: this, panel, windowId: id, signal: life.signal,
        windowState: w.state,
        saveWindowState: (patch) => { Object.assign(w.state, patch); this.#changed(); } });
    } catch (err) {
      body.textContent = `This window couldn't load: ${err.message}`;
    }
    if (focus) this.focus(id);
    if (this.mode === "tiled") this.relayout(true);
    if (!quiet) this.#changed();
    return w;
  }

  /** Bring a window back (from minimized) and to the front. */
  show(id) {
    const w = this.windows.get(id);
    if (!w) return;
    if (w.minimized) {
      this.#setMinimized(w, false);
      this.#changed();
    }
    this.focus(id);
  }

  #freeId(panel) {
    const max = this.panels[panel]?.max || 1;
    for (let n = 1; n <= max; n++) {
      const id = n === 1 ? panel : `${panel}:${n}`;
      if (!this.windows.has(id)) return id;
    }
    return null;
  }

  close(id) {
    const w = this.windows.get(id);
    if (!w) return;
    w.life.abort();
    w.el.remove();
    this.windows.delete(id);
    this.order = this.order.filter((p) => p !== id);
    if (this.active === id) this.#focusTopmost();
    if (this.mode === "tiled") this.relayout(true);
    this.#changed();
  }

  closeAll() {
    for (const w of this.windows.values()) {
      w.life.abort();
      w.el.remove();
    }
    this.windows.clear();
    this.order = [];
    this.active = null;
    this.dispatchEvent(new Event("windows"));
  }

  minimize(id) {
    const w = this.windows.get(id);
    if (!w) return;
    this.#setMinimized(w, true);
    if (this.active === id) this.#focusTopmost();
    if (this.mode === "tiled") this.relayout(true);
    this.#changed();
  }

  #setMinimized(w, value) {
    w.minimized = value;
    w.el.classList.toggle("hidden", value);
    if (!value && this.mode === "tiled") this.relayout(true);
  }

  toggleMaximize(id) {
    const w = this.windows.get(id);
    if (!w || this.mode === "tiled" || this.stacked()) return;
    if (w.maximized) {
      w.maximized = false;
      this.#place(w, T.clampRect(w.prev || w.floatRect, this.area()), true);
      w.floatRect = w.rect;
    } else {
      w.prev = w.rect;
      w.maximized = true;
      this.#place(w, T.zoneRect("max", this.area(), GAP), true);
    }
    this.#syncMaxButton(w);
    this.#changed();
  }

  #syncMaxButton(w) {
    w.el.classList.toggle("maximized", w.maximized);
    fill(w.btnMax, icon(w.maximized ? "restore" : "maximize"));
    w.btnMax.title = w.maximized ? "Restore" : "Maximize";
    w.btnMax.setAttribute("aria-label", w.btnMax.title);
  }

  focus(id) {
    const w = this.windows.get(id);
    if (!w) return;
    if (this.active !== id || w.z !== this.zTop) {
      w.z = ++this.zTop;
      w.el.style.zIndex = String(w.z);
    }
    for (const other of this.windows.values()) other.el.classList.toggle("active", other === w);
    this.active = id;
    this.dispatchEvent(new Event("focus"));
  }

  #focusTopmost() {
    const visible = [...this.windows.values()].filter((w) => !w.minimized).sort((a, b) => b.z - a.z);
    if (visible.length) this.focus(visible[0].id);
    else {
      this.active = null;
      this.dispatchEvent(new Event("focus"));
    }
  }

  // ---- layout modes -----------------------------------------------------------------------

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.desktop.classList.toggle("layout-tiled", mode === "tiled");
    if (mode === "floating") {
      for (const w of this.windows.values()) {
        w.maximized = false;
        this.#syncMaxButton(w);
        this.#place(w, T.clampRect(w.floatRect || w.rect, this.area()), true);
      }
    } else {
      this.relayout(true);
    }
    this.#changed();
  }

  setTiling(tiling) {
    this.tiling = tiling;
    if (this.mode === "tiled") this.relayout(true);
    this.#changed();
  }

  relayout(animate = false) {
    if (this.mode !== "tiled") return;
    const visible = this.order.map((p) => this.windows.get(p)).filter((w) => w && !w.minimized);
    const fn = this.tiling === "grid" ? T.gridLayout : T.masterLayout;
    const rects = fn(visible.length, this.area(), GAP);
    visible.forEach((w, i) => this.#place(w, rects[i], animate));
  }

  /** Floating mode's "Tile" button: arrange open windows into a grid once. */
  tile() {
    if (this.mode === "tiled") return this.relayout(true);
    const visible = [...this.windows.values()].filter((w) => !w.minimized).sort((a, b) => a.z - b.z);
    const rects = T.gridLayout(visible.length, this.area(), GAP);
    visible.forEach((w, i) => {
      w.maximized = false;
      this.#syncMaxButton(w);
      this.#place(w, rects[i], true);
      w.floatRect = rects[i];
    });
    this.#changed();
  }

  // ---- dragging ---------------------------------------------------------------------------

  #startDrag(e, w) {
    if (e.button !== 0 || e.target.closest(".win-btn") || this.stacked()) return;
    e.preventDefault();
    const bar = e.currentTarget;
    bar.setPointerCapture(e.pointerId);
    const origin = this.desktop.getBoundingClientRect();
    const start = { px: e.clientX, py: e.clientY, rect: { ...w.rect } };
    let moved = false;
    let zone = null;
    let target = null;
    w.el.classList.add("dragging");

    const move = (ev) => {
      // Pointer positions are screen pixels; window positions are page pixels (display scale).
      const dx = screenToCss(ev.clientX - start.px);
      const dy = screenToCss(ev.clientY - start.py);
      if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      moved = true;
      if (this.mode === "tiled") {
        w.el.style.transform = `translate(${dx}px, ${dy}px)`;
        w.el.style.pointerEvents = "none";
        const under = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".window");
        if (target && target !== under) target.classList.remove("swap-target");
        target = under && under !== w.el ? under : null;
        target?.classList.add("swap-target");
        return;
      }
      if (w.maximized) {
        // Pull a maximized window off the top: it returns to its old size under the pointer.
        w.maximized = false;
        this.#syncMaxButton(w);
        const prev = w.prev || w.floatRect;
        const grab = screenToCss(start.px - origin.left);
        const ratio = (grab - w.rect.x) / w.rect.w;
        start.rect = { ...prev, x: grab - prev.w * ratio, y: w.rect.y };
      }
      const area = this.area();
      const rect = { ...start.rect, x: start.rect.x + dx, y: Math.max(0, start.rect.y + dy) };
      // Keep at least 80px of the titlebar reachable.
      rect.x = Math.min(Math.max(rect.x, -rect.w + 80), area.w - 80);
      rect.y = Math.min(rect.y, area.h - 40);
      this.#place(w, rect);
      zone = T.snapZone(screenToCss(ev.clientX - origin.left), screenToCss(ev.clientY - origin.top), area);
      const z = zone && T.zoneRect(zone, area, GAP);
      this.preview.classList.toggle("hidden", !z);
      if (z) Object.assign(this.preview.style, { left: `${z.x}px`, top: `${z.y}px`, width: `${z.w}px`, height: `${z.h}px` });
    };

    const up = () => {
      bar.removeEventListener("pointermove", move);
      bar.removeEventListener("pointerup", up);
      bar.removeEventListener("pointercancel", up);
      w.el.classList.remove("dragging");
      this.preview.classList.add("hidden");
      if (!moved) return;
      if (this.mode === "tiled") {
        w.el.style.transform = "";
        w.el.style.pointerEvents = "";
        if (target) {
          target.classList.remove("swap-target");
          const a = this.order.indexOf(w.id);
          const b = this.order.indexOf(target.dataset.window);
          [this.order[a], this.order[b]] = [this.order[b], this.order[a]];
        }
        this.relayout(true);
      } else if (zone) {
        w.prev = start.rect;
        w.maximized = zone === "max";
        this.#syncMaxButton(w);
        this.#place(w, T.zoneRect(zone, this.area(), GAP), true);
        if (!w.maximized) w.floatRect = w.rect;
      } else {
        w.floatRect = w.rect;
      }
      this.#changed();
    };
    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", up);
    bar.addEventListener("pointercancel", up);
  }

  #startResize(e, w, dir) {
    if (e.button !== 0 || this.mode === "tiled" || w.maximized || this.stacked()) return;
    e.preventDefault();
    e.stopPropagation();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const start = { px: e.clientX, py: e.clientY, rect: { ...w.rect } };
    w.el.classList.add("resizing");
    const move = (ev) => {
      const dx = screenToCss(ev.clientX - start.px);
      const dy = screenToCss(ev.clientY - start.py);
      const r = { ...start.rect };
      if (dir.includes("e")) r.w = start.rect.w + dx;
      if (dir.includes("s")) r.h = start.rect.h + dy;
      if (dir.includes("w")) { r.w = start.rect.w - dx; r.x = start.rect.x + dx; }
      if (dir.includes("n")) { r.h = start.rect.h - dy; r.y = start.rect.y + dy; }
      if (r.w < T.MIN_W) { if (dir.includes("w")) r.x -= T.MIN_W - r.w; r.w = T.MIN_W; }
      if (r.h < T.MIN_H) { if (dir.includes("n")) r.y -= T.MIN_H - r.h; r.h = T.MIN_H; }
      this.#place(w, T.clampRect(r, this.area()));
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      w.el.classList.remove("resizing");
      w.floatRect = w.rect;
      this.#changed();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  }

  // ---- keyboard ---------------------------------------------------------------------------

  #onKey(e) {
    if (!e.ctrlKey || !e.altKey || document.querySelector(".overlay")) return;
    const w = this.active && this.windows.get(this.active);
    const key = e.key.toLowerCase();
    if (key === "t") this.setMode(this.mode === "tiled" ? "floating" : "tiled");
    else if (key === "g") this.tile();
    else if (w && this.mode === "floating" && ["arrowleft", "arrowright", "arrowup"].includes(key)) {
      const zone = { arrowleft: "left", arrowright: "right", arrowup: "max" }[key];
      w.prev = w.rect;
      w.maximized = zone === "max";
      this.#syncMaxButton(w);
      this.#place(w, T.zoneRect(zone, this.area(), GAP), true);
      if (!w.maximized) w.floatRect = w.rect;
      this.#changed();
    } else if (w && key === "arrowdown") this.minimize(w.id);
    else if (w && key === "n") this.open(w.panel, null, { newWindow: true });
    else return;
    e.preventDefault();
  }

  #onResize() {
    const area = this.area();
    if (this.mode === "tiled") return this.relayout(false);
    for (const w of this.windows.values()) {
      this.#place(w, w.maximized ? T.zoneRect("max", area, GAP) : T.clampRect(w.rect, area));
    }
  }

  // ---- saving and restoring ---------------------------------------------------------------

  #changed() {
    this.dispatchEvent(new Event("windows"));
    this.dispatchEvent(new Event("change"));
  }

  serialize() {
    const byZ = [...this.windows.values()].sort((a, b) => a.z - b.z);
    const rank = new Map(byZ.map((w, i) => [w.id, Math.min(i, 100)]));
    const windows = this.order.map((p) => this.windows.get(p)).map((w) => {
      const r = (this.mode === "tiled" || w.maximized ? w.floatRect || w.prev : w.rect) || w.rect;
      return {
        panel: w.panel,
        id: w.id,
        ...(Object.keys(w.state).length ? { state: { ...w.state } } : {}),
        x: Math.max(0, Math.min(10000, Math.round(r.x))),
        y: Math.max(0, Math.min(10000, Math.round(r.y))),
        w: Math.max(120, Math.min(10000, Math.round(r.w))),
        h: Math.max(80, Math.min(10000, Math.round(r.h))),
        open: true,
        minimized: w.minimized,
        maximized: w.maximized,
        z: rank.get(w.id),
      };
    });
    return { mode: this.mode, tiling: this.tiling, windows };
  }

  restore(layout, allowed) {
    this.closeAll();
    this.mode = layout?.mode === "tiled" ? "tiled" : "floating";
    this.tiling = layout?.tiling === "grid" ? "grid" : "master";
    this.desktop.classList.toggle("layout-tiled", this.mode === "tiled");
    const saved = (layout?.windows || []).filter((s) => s.open !== false && allowed(s.panel));
    for (const s of [...saved].sort((a, b) => (a.z ?? 0) - (b.z ?? 0))) {
      const w = this.open(s.panel, s, { focus: true, quiet: true });
      if (!w) continue;
      if (s.maximized && this.mode === "floating") {
        w.prev = w.rect;
        w.maximized = true;
        this.#syncMaxButton(w);
        this.#place(w, T.zoneRect("max", this.area(), GAP));
      }
      if (s.minimized) this.#setMinimized(w, true);
    }
    // Keep the saved tiling order rather than the z order used to open them.
    this.order = saved.map((s) => s.id || s.panel).filter((p) => this.windows.has(p));
    this.relayout(false);
    this.#focusTopmost();
    this.dispatchEvent(new Event("windows"));
  }
}
