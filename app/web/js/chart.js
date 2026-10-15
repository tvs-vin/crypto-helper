// A small line chart in SVG. Prices are converted to numbers only to place points on screen;
// every value shown as text is the exact string from the server.

import { money, when } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};
let gradientId = 0;

export function lineChart(rows, { fiat = "usd", width = 600, height = 200 } = {}) {
  const pad = { l: 8, r: 72, t: 12, b: 22 };
  const svg = svgEl("svg", { class: "chart", width, height, viewBox: `0 0 ${width} ${height}`,
    role: "img", "aria-label": "Price chart" });
  if (rows.length < 2) return svg;
  const xs = rows.map((r) => new Date(`${r.at}Z`).getTime());
  const ys = rows.map((r) => Number(r.price));
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
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
  svg.append(defs, area, path);

  const label = (text, x, y, anchor = "start") => {
    const t = svgEl("text", { x, y, "text-anchor": anchor, class: "label" });
    t.textContent = text;
    return t;
  };
  const maxI = ys.indexOf(Math.max(...ys));
  const minI = ys.indexOf(Math.min(...ys));
  svg.append(label(money(rows[maxI].price, fiat), width - 4, Y(ys[maxI]) + 4, "end"),
    label(money(rows[minI].price, fiat), width - 4, Y(ys[minI]) + 4, "end"),
    label(when(rows[0].at), pad.l, height - 6), label(when(rows.at(-1).at), pad.l + W, height - 6, "end"));

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
    tip.textContent = `${money(rows[best].price, fiat)} · ${when(rows[best].at)}`;
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
