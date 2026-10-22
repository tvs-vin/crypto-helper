// Backtester: try a plan on past prices and compare it with simply buying and holding. The server
// simulates it (app/backtest.py): decisions on each day's close, filled at the next day's open,
// fees and slippage on every trade. Runs can be saved, compared side by side, and their trades
// downloaded.

import { api } from "../api.js";
import { on } from "../bus.js";
import { lineChart } from "../chart.js";
import { fill, h } from "../dom.js";
import { ago, money } from "../format.js";
import { planDefaults, planForm, planParams } from "../plan-form.js";
import { button, can, download, errorBox, input, loading, table } from "../ui.js";
import { paperSheet } from "./bots.js";

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

  const state = planDefaults();
  // The window remembers a few small things (window state takes short plain values only).
  if (mine.plan) state.strategy = mine.plan;
  if (mine.currency) state.currency = mine.currency;
  if (mine.fee) state.fee = mine.fee;
  if (mine.coins) state.coins = mine.coins.split(",").map((c) => c.split(":"));

  function drawForm() {
    fill(form, planForm(meta, state, { onChange: keep,
      actions: h("div", { class: "actions" }, button("Run backtest", { kind: "btn-primary", data: { action: "run-backtest" }, onclick: run })) }));
  }

  const keep = () => {
    const coins = state.coins.map(([s, v]) => `${s}:${String(v).trim()}`).join(",");
    ctx.saveWindowState?.({ plan: state.strategy, currency: state.currency, fee: state.fee,
      ...(coins.length <= 40 ? { coins } : {}) });
  };

  async function run() {
    fill(result, loading("Simulating…"));
    try {
      last = await api("POST", "/api/backtests/run", { params: planParams(state) });
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
        can(ctx, "bots.run") && (ctx.state.me?.apps || []).includes("bots")
          ? button("Run it on paper…", { kind: "btn-sm", data: { action: "paper-trade" }, onclick: () => paperSheet(body, ctx, r.params, r.text || r.name) })
          : null,
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
