// Alerts: every alert you have, in one place. Price alerts (the same as in Overview), and the
// smarter ones: your portfolio's value, a synced wallet's balance changing, drift from your
// target percentages, and trend signals (moving averages, drops from a high). The server checks
// them (app/smart_alerts.py) and sends a notification when one fires.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago } from "../format.js";
import { button, emptyState, errorBox, field, form, input, loading, segmented, select, sheet, table } from "../ui.js";
import { priceAlerts } from "./price-alerts.js";

const FIATS = ["usd", "eur", "gbp", "jpy", "cad", "aud"];
const KIND_NAMES = { portfolio: "Portfolio value", wallet: "Wallet balance changes", drift: "Drift from targets", trend: "Trend signal" };
const KIND_HELP = {
  portfolio: "Your wallets' total goes above or below an amount, or moves a lot in a day or a week.",
  wallet: "A synced wallet's balance changes: a deposit, a withdrawal, a reward. Notice an unexpected withdrawal fast.",
  drift: "Set the share you want of each coin (e.g. BTC 60 %, ETH 40 %); you're told when one is off by more than a few points.",
  trend: "A coin crosses its average price of the last N days, or falls a set percent from its recent high.",
};

export function renderAlerts(body, ctx) {
  const mine = h("div", {}, loading());
  const prices = h("div", {});
  const head = h("div", { class: "toolbar" }, h("p", { class: "muted small", text: "Alerts arrive as notifications; choose where in Settings → Notifications (and what Discord may show)." }),
    h("span", { class: "spacer" }),
    button("New alert", { kind: "btn-primary btn-sm", iconName: "bell", data: { action: "new-alert" }, onclick: () => newAlert() }));
  body.append(h("div", { class: "panel-stack" }, head, h("h3", { text: "Portfolio, wallet and trend alerts" }), mine, prices));
  let data = null;
  const fiat = () => ctx.state.prefs?.fiat || "usd";

  async function load() {
    try {
      data = await api("GET", "/api/alerts");
    } catch (err) {
      fill(mine, errorBox(err));
      return;
    }
    priceList.refresh();
    fill(mine, data.alerts.length ? table([
      { label: "Alert", render: (a) => h("span", {}, h("strong", { text: a.text }),
        a.note ? h("p", { class: "muted small", text: `Waiting: ${a.note}` }) : null,
        a.side ? h("p", { class: "muted small", text: `Now ${a.side} the average` }) : null) },
      { label: "Kind", render: (a) => h("span", { class: "muted small", text: KIND_NAMES[a.kind] }) },
      { label: "", render: (a) => h("span", { class: `badge ${a.state === "armed" ? "ok" : "warn"}`, text: a.state === "armed" ? "watching" : "fired",
        title: a.state === "armed" ? "Waiting for its moment" : "Fired; it re-arms once things are back on the other side" }) },
      { label: "Last fired", render: (a) => h("span", { class: "muted small", text: a.last_fired_at ? ago(a.last_fired_at) : "never" }) },
      { label: "", render: (a) => button("Delete", { kind: "btn-sm btn-ghost", data: { action: "delete-alert" }, onclick: async () => {
        await api("DELETE", `/api/alerts/${a.id}`);
        ctx.toast("Alert deleted", a.text);
        load();
      } }) },
    ], data.alerts, { rowKey: (a) => String(a.id) })
      : emptyState("None yet", "New alert: your portfolio's value, a wallet's balance, drift from your targets, or a trend."));
  }

  // Price alerts: the same list and form as in Overview (its coin list fills once data is in).
  const priceList = priceAlerts(prices, ctx, {
    symbols: () => data?.coins || [], chosen: () => null, fiat, onChange: () => {},
  });

  function newAlert() {
    if (!data) return;
    sheet(body, "New alert", (close) => {
      const area = h("div", { class: "panel-stack" });
      let kind = data.kinds[0];
      const kindCtl = segmented(data.kinds.map((k) => [k, KIND_NAMES[k]]), kind, (v) => { kind = v; draw(); }, "Kind");
      const help = h("p", { class: "muted" });
      const fields = h("div", { class: "panel-stack" });
      let collect = () => ({});
      function draw() {
        help.textContent = KIND_HELP[kind];
        const built = FORMS[kind](data, fiat());
        collect = built.collect;
        fill(fields, built.el);
      }
      draw();
      area.append(form([field("Kind", kindCtl), help, fields,
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Add alert", { kind: "btn-primary", type: "submit", data: { action: "save-alert" } }))],
      async () => {
        const a = await api("POST", "/api/alerts", { kind, params: collect() });
        close();
        ctx.toast("Alert added", a.text);
        load();
      }));
      return area;
    });
  }

  on("notification", load, ctx.signal);
  on("alerts-changed", load, ctx.signal);
  on("wallets-changed", load, ctx.signal);
  load();
}

const fiatSelect = (current, name = "fiat") => select(FIATS.map((f) => [f, f.toUpperCase()]), current, { name, "aria-label": "Currency", class: "input select sm" });

const FORMS = {
  portfolio(_data, fiat) {
    const cond = select([["above", "goes above"], ["below", "goes below"], ["move", "moves by"]], "below", { name: "condition", "aria-label": "When" });
    const value = input({ name: "value", inputmode: "decimal", required: true, placeholder: "10000" });
    const cur = fiatSelect(fiat);
    const windowSel = select([["24h", "in 24 hours"], ["7d", "in 7 days"]], "24h", { name: "window", "aria-label": "Over" });
    const unit = h("span", { class: "muted small" });
    const sync = () => {
      const move = cond.value === "move";
      unit.textContent = move ? "%" : "";
      cur.classList.toggle("hidden", move);
      windowSel.classList.toggle("hidden", !move);
      value.placeholder = move ? "10" : "10000";
    };
    cond.addEventListener("change", sync);
    sync();
    return { el: h("div", { class: "row" }, h("span", { text: "When my portfolio" }), cond, value, unit, cur, windowSel),
      collect: () => ({ condition: cond.value, value: value.value.trim(), fiat: cur.value, window: windowSel.value }) };
  },

  wallet(data, fiat) {
    const which = select([["", "Any synced wallet"], ...data.synced_wallets.map((w) => [String(w.id), w.name])], "", { name: "wallet_id", "aria-label": "Wallet" });
    const dir = select([["any", "changes"], ["down", "goes down"], ["up", "goes up"]], "any", { name: "direction", "aria-label": "Direction" });
    const min = input({ name: "min_value", inputmode: "decimal", placeholder: "optional, e.g. 50" });
    const cur = fiatSelect(fiat);
    return { el: h("div", { class: "panel-stack" },
      data.synced_wallets.length ? null : h("div", { class: "notice info", text: "No wallet syncs yet: this alert waits for one (Wallets → Sync from…)." }),
      h("div", { class: "row" }, which, h("span", { text: "balance" }), dir),
      h("div", { class: "row" }, field("Only if worth at least", min, "Leave empty to hear about every change."), cur)),
    collect: () => ({ wallet_id: which.value ? Number(which.value) : null, direction: dir.value,
      min_value: min.value.trim() || null, fiat: cur.value }) };
  },

  drift(data) {
    const rows = h("div", { class: "panel-stack drift-rows" });
    const rest = h("p", { class: "muted small" });
    const threshold = input({ name: "threshold", inputmode: "decimal", required: true, value: "5", class: "input sm" });
    const addRow = (sym = "", pct = "") => {
      const coin = select(data.coins.map((c) => [c, c]), sym || data.coins[0], { "aria-label": "Coin", class: "input select sm", dataset: { role: "coin" } });
      const share = input({ inputmode: "decimal", required: true, value: pct, placeholder: "60", class: "input sm", "aria-label": "Target percent", dataset: { role: "pct" } });
      const row = h("div", { class: "row" }, coin, share, h("span", { class: "muted small", text: "%" }),
        button("×", { kind: "btn-sm btn-ghost", title: "Remove", onclick: () => { row.remove(); sum(); } }));
      share.addEventListener("input", sum);
      rows.append(row);
    };
    function sum() {
      const total = [...rows.querySelectorAll("[data-role=pct]")].reduce((t, i) => t + (Number(i.value) || 0), 0);
      rest.textContent = total > 100 ? "That's more than 100 %." : total < 100 ? `The other ${(100 - total).toFixed(1)} % is for every other coin together.` : "";
    }
    addRow("BTC", "60");
    addRow("ETH", "40");
    sum();
    return { el: h("div", { class: "panel-stack" }, h("p", { class: "small", text: "Targets" }), rows,
      button("+ Coin", { kind: "btn-sm", onclick: () => { addRow(); sum(); } }), rest,
      h("div", { class: "row" }, h("span", { text: "Tell me when a coin is off by more than" }), threshold, h("span", { text: "points" }))),
    collect: () => ({
      targets: Object.fromEntries([...rows.children].map((r) => [r.querySelector("[data-role=coin]").value, r.querySelector("[data-role=pct]").value.trim()])),
      threshold: threshold.value.trim(),
    }) };
  },

  trend(data) {
    const has = (c) => Boolean(data.daily[c]);
    const coins = [...data.coins].sort((a, b) => has(b) - has(a));
    const coin = select(coins.map((c) => [c, has(c) ? c : `${c} (no daily prices)`]), coins[0], { name: "symbol", "aria-label": "Coin" });
    for (const o of coin.options) o.disabled = !has(o.value);
    let signal = "ma_cross";
    const days = select([["20", "20 days"], ["50", "50 days"], ["100", "100 days"], ["200", "200 days"]], "50", { name: "days", "aria-label": "Days" });
    const dir = select([["either", "either way"], ["up", "upwards"], ["down", "downwards"]], "either", { name: "direction", "aria-label": "Direction" });
    const pct = input({ name: "percent", inputmode: "decimal", value: "20", class: "input sm", "aria-label": "Drop percent" });
    const line = h("div", { class: "row" });
    const draw = () => fill(line, ...(signal === "ma_cross"
      ? [coin, h("span", { text: "crosses its" }), days, h("span", { text: "average" }), dir]
      : [coin, h("span", { text: "falls" }), pct, h("span", { text: "% from its" }), days, h("span", { text: "high" })]));
    const sig = segmented([["ma_cross", "Crosses its average"], ["drawdown", "Drops from its high"]], signal, (v) => { signal = v; draw(); }, "Signal");
    draw();
    const since = h("p", { class: "muted small" });
    const showSince = () => { const c = data.daily[coin.value]; since.textContent = c ? `Daily prices for ${coin.value} since ${c.first}, from Coinbase.` : ""; };
    coin.addEventListener("change", showSince);
    showSince();
    return { el: h("div", { class: "panel-stack" }, sig, line, since,
      Object.keys(data.daily).length ? null : h("div", { class: "notice info", text: "Daily prices are still downloading (the server fetches years of them once); come back in a few minutes." })),
    collect: () => ({ symbol: coin.value, signal, days: Number(days.value), direction: dir.value,
      percent: signal === "drawdown" ? pct.value.trim() : null }) };
  },
};
