// Building DOM safely: text always goes in through textContent, never innerHTML.

const SVG_NS = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Replace an element's contents. Unlike replaceChildren, null/false slots are skipped
 * (replaceChildren would show them as the text "null"). */
export function fill(el, ...children) {
  clear(el);
  return append(el, children);
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

// Small stroke icons, drawn from fixed path data (no markup strings).
const ICONS = {
  minimize: ["M4 12h8"],
  maximize: ["M4 4h8v8H4z"],
  restore: ["M5.5 6.5h6v6h-6z", "M7.5 4.5h4a2 2 0 0 1 2 2v4"],
  close: ["M4.5 4.5l7 7", "M11.5 4.5l-7 7"],
  apps: ["M3 3h4v4H3z", "M9 3h4v4H9z", "M3 9h4v4H3z", "M9 9h4v4H9z"],
  console: ["M2.5 3h11v10h-11z", "M5 6.5l2 1.5-2 1.5", "M8.5 10h2.5"],
  terminal: ["M2.5 3.5l4 4.5-4 4.5", "M8 12.5h5.5"],
  plus: ["M8 3.5v9", "M3.5 8h9"],
  server: ["M2.5 2.5h11v4.5h-11z", "M2.5 9h11v4.5h-11z", "M5 4.75h.5", "M5 11.25h.5"],
  appgrid: ["M2.5 2.5h4v4h-4z", "M9.5 2.5h4v4h-4z", "M2.5 9.5h4v4h-4z", "M9.5 11.5l1.5 1.5 2.8-3"],
  tile: ["M2.5 3h11v10h-11z", "M8 3v10", "M8 8h5.5"],
  floating: ["M2.5 5h7v6h-7z", "M6.5 3h7v6"],
  logout: ["M6 3H3.5v10H6", "M10 5l3 3-3 3", "M13 8H6.5"],
  settings: ["M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
             "M8 1.8v1.7M8 12.5v1.7M1.8 8h1.7M12.5 8h1.7M3.6 3.6l1.2 1.2M11.2 11.2l1.2 1.2M3.6 12.4l1.2-1.2M11.2 4.8l1.2-1.2"],
  wallet: ["M2.5 4.5h10a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-10z", "M2.5 4.5v-1a1 1 0 0 1 1-1h7", "M10.5 8.5h1"],
  chart: ["M2.5 13.5h11", "M3.5 10.5l3-3 2 2 4-5"],
  transfer: ["M3 5.5h9.5", "M10 3l2.5 2.5L10 8", "M13 10.5H3.5", "M6 8l-2.5 2.5L6 13"],
  users: ["M6 7.5a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z", "M1.8 13.5c.5-2.4 2.1-3.6 4.2-3.6s3.7 1.2 4.2 3.6",
          "M10.6 3.2a2.2 2.2 0 0 1 0 4.2", "M12 9.9c1.3.4 2 1.6 2.3 3.6"],
  list: ["M5.5 4h8", "M5.5 8h8", "M5.5 12h8", "M2.5 4h.5", "M2.5 8h.5", "M2.5 12h.5"],
  shield: ["M8 1.8l5 2v4c0 3.2-2.2 5.3-5 6.4-2.8-1.1-5-3.2-5-6.4v-4z"],
};

// Icons a theme replaces: vector paths, or a small PNG (checked by theme.js before use).
let themePaths = {};
let themeImages = {};
export function setThemeIcons(paths = {}, images = {}) {
  themePaths = paths || {};
  themeImages = images || {};
}
export const ICON_NAMES = Object.keys(ICONS);

export function icon(name, cls = "icon") {
  if (themeImages[name]) {
    return h("img", { class: `${cls} icon-image`, src: themeImages[name], alt: "", "aria-hidden": "true" });
  }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  for (const d of themePaths[name] || ICONS[name] || []) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

export function brandMark() {
  // Two stacked windows: the app's mark.
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("class", "brand-mark");
  svg.setAttribute("aria-hidden", "true");
  const back = document.createElementNS(SVG_NS, "rect");
  for (const [k, v] of Object.entries({ x: 1.5, y: 1.5, width: 12, height: 12, rx: 2.5,
    fill: "none", stroke: "var(--c-border-strong)", "stroke-width": 1.5 })) back.setAttribute(k, v);
  const front = document.createElementNS(SVG_NS, "rect");
  for (const [k, v] of Object.entries({ x: 6.5, y: 6.5, width: 12, height: 12, rx: 2.5,
    fill: "var(--c-accent)" })) front.setAttribute(k, v);
  svg.append(back, front);
  return svg;
}
