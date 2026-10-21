// A small line chart in SVG. Prices are converted to numbers only to place points on screen;
// every value shown as text is the exact string from the server.

import { money, utc, when } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};
let gradientId = 0;

// rows: [{at, <key>}] oldest first; `key` names the field to plot ("price", or "value" for
// balance history). `also`: more lines from other fields of the same rows, drawn thinner
// (e.g. the backtester's buy-and-hold): [{key, label}]; `main`: the first line's label.
export function lineChart(rows, { fiat = "usd", width = 600, height = 200, key = "price", label: name = "Price chart",
  also = [], main = "", daily = false } = {}) {
  // Daily series: dates only, in UTC (a day's price is for that whole day, wherever you are).
  const stamp = daily ? (s) => utc(s).toLocaleDateString(undefined, { timeZone: "UTC", dateStyle: "medium" }) : when;
  const pad = { l: 8, r: 72, t: 12, b: 22 };
  const svg = svgEl("svg", { class: "chart", width, height, viewBox: `0 0 ${width} ${height}`,
    role: "img", "aria-label": name });
  if (rows.length < 2) return svg;
  const xs = rows.map((r) => new Date(`${r.at}Z`).getTime());
  const ys = rows.map((r) => Number(r[key]));
  const extra = also.map((s) => rows.map((r) => Number(r[s.key])));
  const all = [ys, ...extra].flat();
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(...all), Math.max(...all)];
  const span = y1 - y0 || Math.abs(y1) * 0.02 || 1;
  y0 -= span * 0.08;
  y1 += span * 0.08;
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const X = (x) => pad.l + ((x - x0) / (x1 - x0 || 1)) * W;
  const Y = (y) => pad.t + (1 - (y - y0) / (y1 - y0)) * H;
  const pts = xs.map((x, i) => [X(x), Y(ys[i])]);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const up = ys[ys.length - 1] >= ys[0];

  const id = `cg${++gradientId}`;
  const grad = svgEl("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 });
  const s1 = svgEl("stop", { offset: "0%" });
  const s2 = svgEl("stop", { offset: "100%" });
  s1.style.stopColor = up ? "var(--c-positive)" : "var(--c-negative)";
  s1.style.stopOpacity = "0.22";
  s2.style.stopColor = s1.style.stopColor;
  s2.style.stopOpacity = "0";
  grad.append(s1, s2);
  const defs = svgEl("defs");
  defs.append(grad);

  for (const frac of [0, 0.5, 1]) {
    const y = pad.t + frac * H;
    svg.append(svgEl("line", { x1: pad.l, x2: pad.l + W, y1: y, y2: y, class: "grid" }));
  }
  const area = svgEl("path", { d: `${line}L${pts.at(-1)[0]},${pad.t + H}L${pts[0][0]},${pad.t + H}Z`, fill: `url(#${id})` });
  const path = svgEl("path", { d: line, class: `line ${up ? "up" : "down"}` });
  const others = extra.map((vals, n) => svgEl("path", { class: `line other other-${n}`,
    d: xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(vals[i]).toFixed(1)}`).join("") }));
  svg.append(defs, area, path, ...others); // the comparison lines on top, so they stay visible

  const label = (text, x, y, anchor = "start") => {
    const t = svgEl("text", { x, y, "text-anchor": anchor, class: "label" });
    t.textContent = text;
    return t;
  };
  // The highest and lowest values on any line, at their heights.
  const series = [{ key, vals: ys }, ...also.map((s, n) => ({ key: s.key, vals: extra[n] }))];
  const at = (pick) => {
    let best = null;
    for (const s of series) s.vals.forEach((v, i) => { if (best === null || pick(v, best.v)) best = { v, row: rows[i], key: s.key }; });
    return best;
  };
  const hi = at((a, b) => a > b);
  const lo = at((a, b) => a < b);
  svg.append(label(money(hi.row[hi.key], fiat), width - 4, Y(hi.v) + 4, "end"),
    label(money(lo.row[lo.key], fiat), width - 4, Y(lo.v) + 4, "end"),
    label(stamp(rows[0].at), pad.l, height - 6), label(stamp(rows.at(-1).at), pad.l + W, height - 6, "end"));

  // Hover: nearest point, with its exact price and time.
  const cross = svgEl("line", { y1: pad.t, y2: pad.t + H, class: "cross hidden" });
  const dot = svgEl("circle", { r: 3.5, class: "dot hidden" });
  const tip = label("", 0, pad.t + 12);
  tip.classList.add("tip");
  const hit = svgEl("rect", { x: pad.l, y: pad.t, width: W, height: H, fill: "transparent" });
  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const mx = ((e.clientX - box.left) / box.width) * width;
    let best = 0;
    pts.forEach(([x], i) => { if (Math.abs(x - mx) < Math.abs(pts[best][0] - mx)) best = i; });
    const [px, py] = pts[best];
    for (const el of [cross, dot]) el.classList.remove("hidden");
    cross.setAttribute("x1", px);
    cross.setAttribute("x2", px);
    dot.setAttribute("cx", px);
    dot.setAttribute("cy", py);
    tip.textContent = also.length
      ? `${main || "This"} ${money(rows[best][key], fiat)} · ${also.map((s) => `${s.label} ${money(rows[best][s.key], fiat)}`).join(" · ")} · ${stamp(rows[best].at)}`
      : `${money(rows[best][key], fiat)} · ${stamp(rows[best].at)}`;
    tip.setAttribute("x", Math.min(Math.max(px, pad.l + 4), pad.l + W - 4));
    tip.setAttribute("text-anchor", px > pad.l + W / 2 ? "end" : "start");
  });
  hit.addEventListener("pointerleave", () => {
    for (const el of [cross, dot]) el.classList.add("hidden");
    tip.textContent = "";
  });
  svg.append(cross, dot, tip, hit);
  return svg;
}

// A tiny trend line with no labels (wallet cards). rows: [{at, value}], oldest first.
export function sparkline(rows, { width = 120, height = 28, label: name = "Value over time" } = {}) {
  const svg = svgEl("svg", { class: "spark", width, height, viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": name });
  if (rows.length < 2) return svg;
  const xs = rows.map((r) => new Date(`${r.at}Z`).getTime());
  const ys = rows.map((r) => Number(r.value));
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const X = (x) => 1 + ((x - x0) / (x1 - x0 || 1)) * (width - 2);
  const Y = (y) => (y1 === y0 ? height / 2 : 2 + (1 - (y - y0) / (y1 - y0)) * (height - 4));
  const d = xs.map((x, i) => `${i ? "L" : "M"}${X(x).toFixed(1)},${Y(ys[i]).toFixed(1)}`).join("");
  svg.append(svgEl("path", { d, class: `line ${ys.at(-1) >= ys[0] ? "up" : "down"}` }));
  return svg;
}
