// Backtester: try a plan on past prices and compare it with simply buying and holding. The server
// simulates it (app/backtest.py): decisions on each day's close, filled at the next day's open,
// fees and slippage on every trade. Runs can be saved, compared side by side, and their trades
// downloaded.

import { api } from "../api.js";
import { on } from "../bus.js";
import { lineChart } from "../chart.js";
import { fill, h } from "../dom.js";
import { ago, money } from "../format.js";
import { button, download, emptyState, errorBox, field, input, loading, segmented, select, table } from "../ui.js";

const PLANS = [["dca", "Regular buys"], ["rebalance", "Rebalancing"], ["dip", "Buy the dip"], ["trend", "Trend"]];
const HELP = {
  dca: "Put in a fixed amount on a schedule, split between coins, whatever the price. Over time you buy more when it's cheap and less when it's dear.",
  rebalance: "Keep a set split (e.g. 60 % BTC, 40 % ETH, the rest in cash): now and then, sell some of what grew and buy what shrank.",
  dip: "Keep the money in cash and buy a set amount only when the coin is well below its recent high. Shows whether waiting for dips beats buying straight away.",
  trend: "Hold the coin while its price is above its average of the last N days; sell into cash when it drops below.",
};
const ISO = (s) => `${s}T00:00:00`; // the chart reads full times

export function renderBacktest(body, ctx) {
  const mine = ctx.windowState || {};
  let meta = null;
  let last = null; // the last result shown
  const form = h("div", { class: "panel-stack bt-form" }, loading());
  const result = h("div", { class: "panel-stack bt-result" });
  const saved = h("div", { class: "panel-stack" });
  body.append(h("div", { class: "panel-stack" }, form, result,
    h("section", {}, h("h3", { text: "Saved runs" }), saved)));

  const state = {
    strategy: "dca", coins: [["BTC", "100"]], currency: "usd", start: "", end: "", initial: "1000",
    contribution: "100", every: "month", fee: "coinbase", fee_pct: "0.9", slippage_pct: "0.1",
    rebalance: "quarter", band: "5", dip_pct: "20", dip_days: "30", dip_amount: "250", ma_days: "50",
  };
  // The window remembers a few small things (window state takes short plain values only).
  if (mine.plan) state.strategy = mine.plan;
  if (mine.currency) state.currency = mine.currency;
  if (mine.fee) state.fee = mine.fee;
  if (mine.coins) state.coins = mine.coins.split(",").map((c) => c.split(":"));
  const coinsFor = (cur) => Object.keys(meta.coverage).filter((s) => meta.coverage[s][cur]).sort();
  const firstDay = (syms, cur) => syms.map((s) => meta.coverage[s]?.[cur]?.first_day).filter(Boolean).sort().at(-1);

  function params() {
    const coins = Object.fromEntries((state.strategy === "dip" || state.strategy === "trend"
      ? [[state.coins[0][0], "100"]] : state.coins).map(([s, v]) => [s, String(v).trim()]));
    return {
      strategy: state.strategy, coins, currency: state.currency, start: state.start, end: state.end,
      initial: state.initial.trim(), contribution: state.every === "none" ? "0" : state.contribution.trim(), every: state.every,
      fee_pct: state.fee_pct.trim(), slippage_pct: state.slippage_pct.trim(),
      rebalance: state.rebalance, band: state.band.trim(), dip_pct: state.dip_pct.trim(),
      dip_days: Number(state.dip_days), dip_amount: state.dip_amount.trim(), ma_days: Number(state.ma_days),
    };
  }

  function drawForm() {
    const cur = state.currency;
    const coins = coinsFor(cur);
    if (!coins.length) {
      fill(form, emptyState("No daily prices yet", "The server downloads USD daily prices from Coinbase shortly after it starts; other currencies can be imported in Settings → Prices → Past prices."));
      return;
    }
    if (!state.coins.every(([s]) => coins.includes(s))) state.coins = [[coins.includes("BTC") ? "BTC" : coins[0], "100"]];
    const single = state.strategy === "dip" || state.strategy === "trend";
    const set = (k) => (e) => { state[k] = e.target.value; keep(); };
    const inp = (k, attrs = {}) => { const el = input({ value: state[k], name: k, class: "input sm", inputmode: "decimal", ...attrs }); el.addEventListener("input", set(k)); return el; };
    const sel = (k, opts, attrs = {}) => { const el = select(opts, state[k], { name: k, class: "input select sm", ...attrs }); el.addEventListener("change", (e) => { set(k)(e); drawForm(); }); return el; };

    const coinRows = h("div", { class: "panel-stack" }, (single ? state.coins.slice(0, 1) : state.coins).map(([sym, pct], i) => {
      const cs = select(coins.map((c) => [c, c]), sym, { class: "input select sm", "aria-label": "Coin", dataset: { role: "coin" } });
      cs.addEventListener("change", () => { state.coins[i][0] = cs.value; keep(); drawForm(); });
      if (single) return h("div", { class: "row" }, cs, h("span", { class: "muted small", text: `daily prices since ${meta.coverage[sym]?.[cur]?.first_day || "?"}` }));
      const p = input({ value: pct, class: "input sm bt-pct", inputmode: "decimal", "aria-label": `${sym} share`, dataset: { role: "pct" } });
      p.addEventListener("input", () => { state.coins[i][1] = p.value; keep(); showSum(); });
      return h("div", { class: "row" }, cs, p, h("span", { class: "muted small", text: "%" }),
        state.coins.length > 1 ? button("×", { kind: "btn-sm btn-ghost", title: "Remove", onclick: () => { state.coins.splice(i, 1); keep(); drawForm(); } }) : null);
    }));
    const sum = h("p", { class: "muted small" });
    function showSum() {
      const total = state.coins.reduce((t, [, v]) => t + (Number(v) || 0), 0);
      sum.textContent = state.strategy === "dca" ? (total === 100 ? "" : `The shares add up to ${total} %: they must make 100 %.`)
        : total > 100 ? "More than 100 %." : total < 100 ? `The other ${(100 - total).toFixed(1)} % stays in cash.` : "";
    }
    if (!single) showSum();

    // Dates: presets back from the newest common day.
    const syms = (single ? state.coins.slice(0, 1) : state.coins).map(([s]) => s);
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
      keep(); drawForm();
    }, "Range");

    const feeSel = select([...Object.entries(meta.fees).map(([k, f]) => [k, `${f.name} (${f.pct} %)`]), ["custom", "Custom"]],
      state.fee, { name: "fee", class: "input select sm", "aria-label": "Fees like" });
    feeSel.addEventListener("change", () => {
      state.fee = feeSel.value;
      if (meta.fees[state.fee]) state.fee_pct = meta.fees[state.fee].pct;
      keep(); drawForm();
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
    fill(form,
      h("div", { class: "row bt-top" }, segmented(PLANS, state.strategy, (v) => {
        state.strategy = v;
        if ((v === "dip" || v === "trend") && state.coins.length > 1) state.coins = state.coins.slice(0, 1);
        if (v === "dca" && state.coins.length === 1) state.coins[0][1] = "100";
        keep(); drawForm();
      }, "Plan"), h("span", { class: "spacer" }), sel("currency", currencies.map((c) => [c, c.toUpperCase()]), { "aria-label": "Currency" })),
      h("p", { class: "muted small", text: HELP[state.strategy] }),
      h("div", { class: "grid-2" },
        field(single ? "Coin" : "Coins and shares", h("div", { class: "panel-stack" }, coinRows,
          single ? null : button("+ Coin", { kind: "btn-sm", onclick: () => { state.coins.push([coins.find((c) => !state.coins.some(([s]) => s === c)) || coins[0], "0"]); keep(); drawForm(); } }),
          single ? null : sum)),
        h("div", { class: "panel-stack" },
          field("Dates", h("div", { class: "row" }, start, h("span", { text: "to" }), end), `Prices from ${earliest}.`), presets)),
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
      h("div", { class: "actions" }, button("Run backtest", { kind: "btn-primary", data: { action: "run-backtest" }, onclick: run })));
  }

  const keep = () => {
    const coins = state.coins.map(([s, v]) => `${s}:${String(v).trim()}`).join(",");
    ctx.saveWindowState?.({ plan: state.strategy, currency: state.currency, fee: state.fee,
      ...(coins.length <= 40 ? { coins } : {}) });
  };

  async function run() {
    fill(result, loading("Simulating…"));
    try {
      last = await api("POST", "/api/backtests/run", { params: params() });
      showResult(last, null);
      result.scrollIntoView({ block: "start", behavior: "smooth" }); // the results are below the form
    } catch (err) {
      fill(result, errorBox(err));
    }
  }

  function showResult(r, savedId) {
    const s = r.summary;
    const cur = s.currency;
    const card = (title, x, better) => h("div", { class: `bt-card${better ? " better" : ""}` },
      h("h4", { text: title }),
      h("p", { class: "big num", text: money(x.final, cur) }),
      h("p", { class: `num ${Number(x.profit) >= 0 ? "up" : "down"}`, text: `${Number(x.profit) >= 0 ? "+" : ""}${money(x.profit, cur)} (${x.return_pct ?? "—"} %)` }),
      h("dl", { class: "bt-facts" },
        h("dt", { text: "Yearly rate" }), h("dd", { class: "num", text: x.annual_pct === null ? "—" : `${x.annual_pct} %` }),
        h("dt", { text: "Worst drop" }), h("dd", { class: "num", text: `${x.worst_drop_pct} %` }),
        h("dt", { text: "Fees + slippage" }), h("dd", { class: "num", text: `${money(x.fees, cur)} + ${money(x.slippage, cur)}` }),
        x.trades !== undefined ? [h("dt", { text: "Trades" }), h("dd", { class: "num", text: String(x.trades) })] : null,
        x.in_market_pct !== undefined && r.params?.strategy !== "dca" ? [h("dt", { text: "In the market" }), h("dd", { class: "num", text: `${x.in_market_pct} % of days` })] : null,
        Number(x.cash) ? [h("dt", { text: "Cash left" }), h("dd", { class: "num", text: money(x.cash, cur) })] : null));
    const better = Number(s.plan.final) >= Number(s.buy_and_hold.final);
    const rows = r.series.map((p) => ({ ...p, at: ISO(p.at) }));
    const name = input({ name: "run_name", placeholder: "Name this run", maxlength: "80", class: "input sm", value: r.name || "" });
    const width = Math.max(320, result.clientWidth || 700);
    fill(result,
      h("h3", { text: r.text || r.name }),
      h("p", { class: "muted small", text: `${s.first_day} to ${s.last_day} · ${s.days} days · ${money(s.put_in, cur)} put in. Past prices don't predict future ones; taxes aren't included.` }),
      h("div", { class: "bt-cards" }, card("This plan", s.plan, better), card("Buy and hold", s.buy_and_hold, !better)),
      lineChart(rows, { fiat: cur, width, height: 220, key: "value", also: [{ key: "benchmark", label: "Hold" }], main: "Plan", daily: true,
        label: "Value over time: this plan (solid) and buy and hold (dashed)" }),
      h("p", { class: "muted small", text: "Solid: this plan. Dashed: buying the same coins with the same money as it arrived, and holding." }),
      tradesTable(r.trades || [], cur, r.trades_total),
      h("div", { class: "actions" },
        button("Download trades (CSV)", { kind: "btn-sm", data: { action: "bt-csv" }, onclick: () => {
          if (savedId) { window.location.href = `/api/backtests/${savedId}/trades.csv`; return; }
          const lines = [["day", "side", "symbol", "units", "price", "value", "fee", "currency"].join(",")]
            .concat((r.trades || []).map((t) => [t.day, t.side, t.symbol, t.units, t.price, t.value, t.fee, cur.toUpperCase()].join(",")));
          download("backtest-trades.csv", `${lines.join("\n")}\n`, "text/csv");
        } }),
        savedId ? null : h("span", { class: "row" }, name, button("Save", { kind: "btn-sm btn-primary", data: { action: "save-backtest" }, onclick: async () => {
          try {
            await api("POST", "/api/backtests", { name: name.value.trim() || r.text.slice(0, 80), params: r.params });
            ctx.toast("Saved", name.value.trim() || r.text);
            loadSaved();
          } catch (err) { ctx.toast("Couldn't save it", err.message, "error"); }
        } }))));
  }

  function tradesTable(trades, cur, total) {
    if (!trades.length) return h("p", { class: "muted small", text: "No trades." });
    const shown = trades.slice(0, 100);
    return h("details", { class: "bt-trades" }, h("summary", { text: `Trades (${total ?? trades.length})${shown.length < (total ?? trades.length) ? `: the first ${shown.length}` : ""}` }),
      table([
        { label: "Day", render: (t) => t.day },
        { label: "", render: (t) => h("span", { class: `badge ${t.side === "buy" ? "ok" : "warn"}`, text: t.side }) },
        { label: "Coin", render: (t) => t.symbol },
        { label: "Units", align: "right", cls: "num", render: (t) => t.units },
        { label: "Price", align: "right", cls: "num", render: (t) => money(t.price, cur) },
        { label: "Value", align: "right", cls: "num", render: (t) => money(t.value, cur) },
        { label: "Fee", align: "right", cls: "num", render: (t) => money(t.fee, cur) },
      ], shown));
  }

  async function loadSaved() {
    try {
      const { runs } = await api("GET", "/api/backtests");
      if (!runs.length) { fill(saved, h("p", { class: "muted small", text: "None yet: run one, then Save it to compare it with others later." })); return; }
      const picked = new Set();
      const compare = h("div", {});
      const cmpBtn = button("Compare selected", { kind: "btn-sm", disabled: true, data: { action: "compare-runs" }, onclick: () => showCompare(runs.filter((r) => picked.has(r.id)), compare) });
      fill(saved, table([
        { label: "", render: (r) => { const b = h("input", { type: "checkbox", "aria-label": `Compare ${r.name}`, dataset: { run: r.id } }); b.addEventListener("change", () => { b.checked ? picked.add(r.id) : picked.delete(r.id); cmpBtn.disabled = picked.size < 2; }); return b; } },
        { label: "Run", render: (r) => h("span", {}, h("strong", { text: r.name }), h("p", { class: "muted small", text: r.text })) },
        { label: "Plan", align: "right", cls: "num", render: (r) => `${money(r.summary.plan.final, r.summary.currency)} (${r.summary.plan.return_pct} %)` },
        { label: "Buy and hold", align: "right", cls: "num", render: (r) => `${money(r.summary.buy_and_hold.final, r.summary.currency)} (${r.summary.buy_and_hold.return_pct} %)` },
        { label: "Saved", render: (r) => h("span", { class: "muted small", text: ago(r.created_at) }) },
        { label: "", render: (r) => h("span", { class: "row" },
          button("Open", { kind: "btn-sm btn-ghost", onclick: async () => { const full = await api("GET", `/api/backtests/${r.id}`); showResult(full, r.id); result.scrollIntoView({ block: "start" }); } }),
          button("Delete", { kind: "btn-sm btn-ghost", data: { action: "delete-run" }, onclick: async () => { await api("DELETE", `/api/backtests/${r.id}`); loadSaved(); } })) },
      ], runs, { rowKey: (r) => String(r.id) }), h("div", { class: "actions" }, cmpBtn), compare);
      saved.querySelector("table")?.classList.add("bt-saved");
    } catch (err) {
      fill(saved, errorBox(err));
    }
  }

  function showCompare(runs, area) {
    const metric = (label, f) => ({ label, f });
    const metrics = [
      metric("Dates", (r) => `${r.summary.first_day} to ${r.summary.last_day}`),
      metric("Put in", (r) => money(r.summary.put_in, r.summary.currency)),
      metric("Final value", (r) => money(r.summary.plan.final, r.summary.currency)),
      metric("Return", (r) => `${r.summary.plan.return_pct} %`),
      metric("Yearly rate", (r) => (r.summary.plan.annual_pct === null ? "—" : `${r.summary.plan.annual_pct} %`)),
      metric("Worst drop", (r) => `${r.summary.plan.worst_drop_pct} %`),
      metric("Trades", (r) => String(r.summary.plan.trades)),
      metric("Fees + slippage", (r) => `${money(r.summary.plan.fees, r.summary.currency)} + ${money(r.summary.plan.slippage, r.summary.currency)}`),
      metric("Buy and hold", (r) => `${money(r.summary.buy_and_hold.final, r.summary.currency)} (${r.summary.buy_and_hold.return_pct} %)`),
    ];
    fill(area, h("div", { class: "table-wrap" }, h("table", { class: "table bt-compare" },
      h("thead", {}, h("tr", {}, h("th", { text: "" }), runs.map((r) => h("th", { scope: "col", text: r.name })))),
      h("tbody", {}, metrics.map((m) => h("tr", {}, h("th", { scope: "row", text: m.label }), runs.map((r) => h("td", { class: "num", text: m.f(r) }))))))));
  }

  (async () => {
    try {
      meta = await api("GET", "/api/backtests/meta");
      drawForm();
    } catch (err) {
      fill(form, errorBox(err));
    }
  })();
  on("backtests-changed", loadSaved, ctx.signal);
  on("prices-changed", () => { if (meta) api("GET", "/api/backtests/meta").then((m) => { meta = m; }).catch(() => {}); }, ctx.signal);
  loadSaved();
}

function shift(day, years) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() + years);
  return d.toISOString().slice(0, 10);
}
