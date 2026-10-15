// Small building blocks shared by the windows. Everything renders through dom.js (no markup).

import { h, icon } from "./dom.js";

export function button(text, { kind = "", onclick, type = "button", disabled, title, data, iconName } = {}) {
  return h("button", { class: `btn ${kind}`.trim(), type, onclick, disabled, title, dataset: data },
    iconName ? icon(iconName) : null, text ? h("span", { text }) : null);
}

export function field(label, control, hint = null) {
  const id = control.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  return h("div", { class: "field" }, h("label", { for: id, text: label }), control,
    hint ? h("p", { class: "hint", text: hint }) : null);
}

export function input(attrs = {}) {
  return h("input", { class: "input", ...attrs });
}

export function select(options, value, attrs = {}) {
  const el = h("select", { class: "input select", ...attrs });
  for (const opt of options) {
    const [v, text] = Array.isArray(opt) ? opt : [opt, opt];
    el.append(h("option", { value: v, text, selected: String(v) === String(value) }));
  }
  return el;
}

export function segmented(options, current, onPick, label) {
  const group = h("div", { class: "segmented", role: "group", "aria-label": label });
  group.sync = (value) => {
    for (const b of group.children) b.setAttribute("aria-pressed", String(b.dataset.value === value));
  };
  for (const [value, text] of options) {
    group.append(h("button", { type: "button", "aria-pressed": String(value === current), dataset: { value },
      text, onclick: () => { group.sync(value); onPick(value); } }));
  }
  return group;
}

export function chips(tags = [], systemTags = []) {
  return h("div", { class: "chips" },
    tags.map((t) => h("span", { class: "chip", text: t })),
    systemTags.map((t) => h("span", { class: "chip system", text: t, title: "Built-in tag" })));
}

export function emptyState(title, text, action = null) {
  return h("div", { class: "empty" }, h("h3", { text: title }), text ? h("p", { text }) : null, action);
}

export function errorBox(err) {
  const problems = err?.data?.problems;
  return h("div", { class: "notice error", role: "alert" },
    err?.message || String(err),
    problems?.length ? h("ul", {}, problems.map((p) => h("li", { text: p }))) : null);
}

export function loading(text = "Loading…") {
  return h("div", { class: "loading", role: "status", text });
}

/** A table. columns: [{key, label, align, render(row) -> Node|string, cls}] */
export function table(columns, rows, { empty = "Nothing here yet.", onRow, rowKey } = {}) {
  if (!rows.length) return emptyState(empty, "");
  const thead = h("thead", {}, h("tr", {}, columns.map((c) =>
    h("th", { scope: "col", class: c.align === "right" ? "r" : "", text: c.label ?? "" }))));
  const tbody = h("tbody", {}, rows.map((row) => {
    const tr = h("tr", { dataset: rowKey ? { key: rowKey(row) } : undefined },
      columns.map((c) => {
        const value = c.render ? c.render(row) : row[c.key];
        return h("td", { class: [c.align === "right" ? "r" : "", c.cls || ""].join(" ").trim() || null },
          value instanceof Node ? value : String(value ?? ""));
      }));
    if (onRow) {
      tr.classList.add("clickable");
      tr.tabIndex = 0;
      tr.addEventListener("click", () => onRow(row, tr));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onRow(row, tr); });
    }
    return tr;
  }));
  return h("div", { class: "table-wrap" }, h("table", { class: "table" }, thead, tbody));
}

/** A dialog inside a window: covers the window's body, closes with Esc or Cancel. */
export function sheet(windowBody, title, build) {
  const close = () => { wrap.remove(); };
  const panel = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "sheet-head" }, h("h2", { text: title }),
      h("button", { class: "win-btn", type: "button", "aria-label": "Close", onclick: close }, icon("close"))));
  const wrap = h("div", { class: "sheet-backdrop" }, panel);
  wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  wrap.addEventListener("pointerdown", (e) => { if (e.target === wrap) close(); });
  panel.append(build(close));
  windowBody.closest(".window").append(wrap);
  panel.querySelector("input, select, textarea, button:not(.win-btn)")?.focus();
  return close;
}

/** A form whose submit shows a server error inline and disables itself while busy. */
export function form(children, onSubmit) {
  const el = h("form", { class: "form" }, children);
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    el.querySelector(":scope > .notice.error")?.remove();
    const controls = el.querySelectorAll("button, input, select, textarea");
    const was = [...controls].map((c) => c.disabled);
    controls.forEach((c) => { c.disabled = true; });
    try {
      await onSubmit(el);
    } catch (err) {
      el.prepend(errorBox(err));
    } finally {
      controls.forEach((c, i) => { c.disabled = was[i]; });
    }
  });
  return el;
}

export function can(ctx, permission) {
  return (ctx.state.me?.permissions || []).includes(permission);
}
