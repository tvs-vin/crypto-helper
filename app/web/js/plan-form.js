// The plan form shared by the Backtester and Paper trading: a strategy, its coins and shares,
// money in, fees and slippage (and, for a backtest, dates). `meta` is /api/backtests/meta (or
// /api/bots/meta): fee presets and which coins have daily prices in which currency since when.
// The form changes `state` in place and redraws itself; `onChange(state)` after every change.

import { fill, h } from "./dom.js";
import { button, emptyState, field, input, segmented, select } from "./ui.js";

export const PLANS = [["dca", "Regular buys"], ["rebalance", "Rebalancing"], ["dip", "Buy the dip"], ["trend", "Trend"]];
const HELP = {
  dca: "Put in a fixed amount on a schedule, split between coins, whatever the price. Over time you buy more when it's cheap and less when it's dear.",
  rebalance: "Keep a set split (e.g. 60 % BTC, 40 % ETH, the rest in cash): now and then, sell some of what grew and buy what shrank.",
  dip: "Keep the money in cash and buy a set amount only when the coin is well below its recent high. Shows whether waiting for dips beats buying straight away.",
  trend: "Hold the coin while its price is above its average of the last N days; sell into cash when it drops below.",
};

export function planDefaults() {
  return {
    strategy: "dca", coins: [["BTC", "100"]], currency: "usd", start: "", end: "", initial: "1000",
    contribution: "100", every: "month", fee: "coinbase", fee_pct: "0.9", slippage_pct: "0.1",
    rebalance: "quarter", band: "5", dip_pct: "20", dip_days: "30", dip_amount: "250", ma_days: "50",
  };
}

const single = (state) => state.strategy === "dip" || state.strategy === "trend";

/** The plan as the server takes it (`dates`: with start and end, for a backtest). */
export function planParams(state, { dates = true } = {}) {
  const coins = Object.fromEntries((single(state) ? [[state.coins[0][0], "100"]] : state.coins)
    .map(([s, v]) => [s, String(v).trim()]));
  return {
    strategy: state.strategy, coins, currency: state.currency, ...(dates ? { start: state.start, end: state.end } : {}),
    initial: state.initial.trim(), contribution: state.every === "none" ? "0" : state.contribution.trim(), every: state.every,
    fee_pct: state.fee_pct.trim(), slippage_pct: state.slippage_pct.trim(),
    rebalance: state.rebalance, band: state.band.trim(), dip_pct: state.dip_pct.trim(),
    dip_days: Number(state.dip_days), dip_amount: state.dip_amount.trim(), ma_days: Number(state.ma_days),
  };
}

export function planForm(meta, state, { dates = true, onChange = () => {}, actions = null } = {}) {
  const wrap = h("div", { class: "panel-stack" });
  const keep = () => onChange(state);
  const coinsFor = (cur) => Object.keys(meta.coverage).filter((s) => meta.coverage[s][cur]).sort();
  const firstDay = (syms, cur) => syms.map((s) => meta.coverage[s]?.[cur]?.first_day).filter(Boolean).sort().at(-1);

  function draw() {
    const cur = state.currency;
    const coins = coinsFor(cur);
    if (!coins.length) {
      fill(wrap, emptyState("No daily prices yet", "The server downloads USD daily prices from Coinbase shortly after it starts; other currencies can be imported in Settings → Prices → Past prices."));
      return;
    }
    if (!state.coins.every(([s]) => coins.includes(s))) state.coins = [[coins.includes("BTC") ? "BTC" : coins[0], "100"]];
    const one = single(state);
    const set = (k) => (e) => { state[k] = e.target.value; keep(); };
    const inp = (k, attrs = {}) => { const el = input({ value: state[k], name: k, class: "input sm", inputmode: "decimal", ...attrs }); el.addEventListener("input", set(k)); return el; };
    const sel = (k, opts, attrs = {}) => { const el = select(opts, state[k], { name: k, class: "input select sm", ...attrs }); el.addEventListener("change", (e) => { set(k)(e); draw(); }); return el; };

    const coinRows = h("div", { class: "panel-stack" }, (one ? state.coins.slice(0, 1) : state.coins).map(([sym, pct], i) => {
      const cs = select(coins.map((c) => [c, c]), sym, { class: "input select sm", "aria-label": "Coin", dataset: { role: "coin" } });
      cs.addEventListener("change", () => { state.coins[i][0] = cs.value; keep(); draw(); });
      if (one) return h("div", { class: "row" }, cs, h("span", { class: "muted small", text: `daily prices since ${meta.coverage[sym]?.[cur]?.first_day || "?"}` }));
      const p = input({ value: pct, class: "input sm bt-pct", inputmode: "decimal", "aria-label": `${sym} share`, dataset: { role: "pct" } });
      p.addEventListener("input", () => { state.coins[i][1] = p.value; keep(); showSum(); });
      return h("div", { class: "row" }, cs, p, h("span", { class: "muted small", text: "%" }),
        state.coins.length > 1 ? button("×", { kind: "btn-sm btn-ghost", title: "Remove", onclick: () => { state.coins.splice(i, 1); keep(); draw(); } }) : null);
    }));
    const sum = h("p", { class: "muted small" });
    function showSum() {
      const total = state.coins.reduce((t, [, v]) => t + (Number(v) || 0), 0);
      sum.textContent = state.strategy === "dca" ? (total === 100 ? "" : `The shares add up to ${total} %: they must make 100 %.`)
        : total > 100 ? "More than 100 %." : total < 100 ? `The other ${(100 - total).toFixed(1)} % stays in cash.` : "";
    }
    if (!one) showSum();

    let when = null;
    if (dates) { // presets back from today
      const syms = (one ? state.coins.slice(0, 1) : state.coins).map(([s]) => s);
      const earliest = firstDay(syms, cur);
      const today = new Date().toISOString().slice(0, 10);
      if (!state.end) state.end = today;
      if (!state.start) state.start = shift(state.end, -3);
      const start = input({ type: "date", value: state.start, name: "start", class: "input sm", min: earliest, max: today });
      const end = input({ type: "date", value: state.end, name: "end", class: "input sm", min: earliest, max: today });
      start.addEventListener("change", () => { state.start = start.value; keep(); });
      end.addEventListener("change", () => { state.end = end.value; keep(); });
      const presets = segmented([["1", "1y"], ["3", "3y"], ["5", "5y"], ["max", "Max"]], "", (v) => {
        state.end = today;
        state.start = v === "max" ? earliest : shift(today, -Number(v));
        if (state.start < earliest) state.start = earliest;
        keep(); draw();
      }, "Range");
      when = h("div", { class: "panel-stack" },
        field("Dates", h("div", { class: "row" }, start, h("span", { text: "to" }), end), `Prices from ${earliest}.`), presets);
    }

    const feeSel = select([...Object.entries(meta.fees).map(([k, f]) => [k, `${f.name} (${f.pct} %)`]), ["custom", "Custom"]],
      state.fee, { name: "fee", class: "input select sm", "aria-label": "Fees like" });
    feeSel.addEventListener("change", () => {
      state.fee = feeSel.value;
      if (meta.fees[state.fee]) state.fee_pct = meta.fees[state.fee].pct;
      keep(); draw();
    });
    const fee = inp("fee_pct", { "aria-label": "Fee %", readonly: state.fee !== "custom" });

    const extra = {
      dca: null,
      rebalance: h("div", { class: "row" }, h("span", { text: "Rebalance" }),
        sel("rebalance", [["month", "every month"], ["quarter", "every quarter"], ["year", "every year"], ["threshold", "when a coin is off by"]]),
        state.rebalance === "threshold" ? h("span", { class: "row" }, inp("band", { "aria-label": "Band" }), h("span", { text: "points" })) : null),
      dip: h("div", { class: "row" }, h("span", { text: "Buy" }), inp("dip_amount", { "aria-label": "Dip buy" }),
        h("span", { text: `${cur.toUpperCase()} when it's` }), inp("dip_pct", { "aria-label": "Drop %" }),
        h("span", { text: "% below its" }), inp("dip_days", { "aria-label": "Days" }), h("span", { text: "-day high" })),
      trend: h("div", { class: "row" }, h("span", { text: "Hold while above its" }),
        sel("ma_days", [["20", "20-day"], ["50", "50-day"], ["100", "100-day"], ["200", "200-day"]]), h("span", { text: "average" })),
    }[state.strategy];

    const currencies = [...new Set(Object.values(meta.coverage).flatMap((c) => Object.keys(c)))].sort();
    const coinField = field(one ? "Coin" : "Coins and shares", h("div", { class: "panel-stack" }, coinRows,
      one ? null : button("+ Coin", { kind: "btn-sm", onclick: () => { state.coins.push([coins.find((c) => !state.coins.some(([s]) => s === c)) || coins[0], "0"]); keep(); draw(); } }),
      one ? null : sum));
    fill(wrap,
      h("div", { class: "row bt-top" }, segmented(PLANS, state.strategy, (v) => {
        state.strategy = v;
        if ((v === "dip" || v === "trend") && state.coins.length > 1) state.coins = state.coins.slice(0, 1);
        if (v === "dca" && state.coins.length === 1) state.coins[0][1] = "100";
        keep(); draw();
      }, "Plan"), h("span", { class: "spacer" }), sel("currency", currencies.map((c) => [c, c.toUpperCase()]), { "aria-label": "Currency" })),
      h("p", { class: "muted small", text: HELP[state.strategy] }),
      when ? h("div", { class: "grid-2" }, coinField, when) : coinField,
      h("div", { class: "grid-2" },
        field(`Starting money (${cur.toUpperCase()})`, inp("initial")),
        field("Then add", h("div", { class: "row" }, state.every === "none" ? null : inp("contribution", { "aria-label": "Each addition" }),
          sel("every", [["none", "nothing"], ["week", "every week"], ["month", "every month"]], { "aria-label": "How often" })))),
      extra,
      h("div", { class: "grid-2" },
        field("Fees like", h("div", { class: "row" }, feeSel, fee, h("span", { class: "muted small", text: "%" })),
          "Entry-tier fees for market orders, checked 2026-10-21. Check your own tier in the exchange's order preview."),
        field("Slippage", h("div", { class: "row" }, inp("slippage_pct", { "aria-label": "Slippage %" }), h("span", { class: "muted small", text: "%" })),
          "How much worse than the quoted price a fill is. 0.1 % is typical for big coins.")),
      actions);
  }
  draw();
  wrap.redraw = draw;
  return wrap;
}

function shift(day, years) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() + years);
  return d.toISOString().slice(0, 10);
}
