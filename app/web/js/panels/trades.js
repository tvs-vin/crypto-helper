// Trade log: trades imported (read-only) from connected exchanges, newest first, with filters,
// and a CSV download for tax software (TurboTax, CoinLedger, CoinTracker, Koinly, or generic).

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { amount } from "../format.js";
import { button, emptyState, errorBox, input, loading, select, table } from "../ui.js";

export function renderTrades(body, ctx) {
  const mine = ctx.windowState || {};
  const walletSel = select([["", "All accounts"]], "", { "aria-label": "Account", class: "input select sm", name: "trade_wallet" });
  const asset = input({ name: "trade_asset", placeholder: "Coin, e.g. BTC", class: "input sm", spellcheck: "false", maxlength: "16" });
  const since = input({ type: "date", name: "trade_since", class: "input sm", "aria-label": "From" });
  const until = input({ type: "date", name: "trade_until", class: "input sm", "aria-label": "To" });
  const format = select([], mine.format || "generic", { "aria-label": "CSV format", class: "input select sm", name: "trade_format" });
  const summary = h("p", { class: "muted small" });
  const list = h("div", {}, loading());
  const more = h("div", { class: "actions" });
  const download = h("a", { class: "btn btn-primary btn-sm", href: "#", dataset: { action: "export-trades" }, text: "Download CSV" });

  body.append(h("div", { class: "panel-stack" },
    h("div", { class: "toolbar" }, walletSel, asset, h("label", { class: "muted small", text: "From" }), since,
      h("label", { class: "muted small", text: "to" }), until, h("span", { class: "spacer" }), format, download),
    summary, list, more));

  let rows = [];
  const query = () => {
    const q = new URLSearchParams();
    if (walletSel.value) q.set("wallet_id", walletSel.value);
    if (asset.value.trim()) q.set("asset", asset.value.trim().toUpperCase());
    if (since.value) q.set("since", since.value);
    if (until.value) q.set("until", until.value);
    return q;
  };
  const updateDownload = () => {
    const q = query();
    q.set("format", format.value || "generic");
    download.href = `/api/trades/export?${q}`; // same origin: the session cookie goes along
    download.setAttribute("download", "");
  };

  async function load(append = false) {
    try {
      const q = query();
      if (append && rows.length) q.set("before_id", rows[rows.length - 1].id);
      const data = await api("GET", `/api/trades?${q}`);
      rows = append ? [...rows, ...data.trades] : data.trades;
      fill(summary, `${data.total} trade${data.total === 1 ? "" : "s"}`);
      fill(list, rows.length ? table([
        // UTC as stored (the tax files use UTC too), not converted to this browser's time.
        { label: "When (UTC)", cls: "num", render: (t) => t.time.replace("T", " ").slice(0, 16) },
        { label: "Account", render: (t) => h("span", {}, t.account, h("span", { class: "muted small", text: ` · ${t.exchange_name}` })) },
        { label: "", render: (t) => h("span", { class: `badge ${t.side === "buy" ? "ok" : "warn"}`, text: t.side }) },
        { label: "Amount", align: "right", cls: "num", render: (t) => `${amount(t.amount)} ${t.base}` },
        { label: "Price", align: "right", cls: "num", render: (t) => `${amount(t.price)} ${t.quote}` },
        { label: "Total", align: "right", cls: "num", render: (t) => `${amount(t.total)} ${t.quote}` },
        { label: "Fee", align: "right", cls: "num", render: (t) => (Number(t.fee) ? `${amount(t.fee)} ${t.fee_asset}` : "—") },
      ], rows) : emptyState("No trades", "Trades come from connected exchanges (Wallets → an exchange wallet → Sync from…). They're imported on Sync now and every hour."));
      fill(more, rows.length < data.total
        ? button("Load more", { kind: "btn-sm", onclick: () => load(true) }) : null);
    } catch (err) {
      fill(list, errorBox(err));
    }
    updateDownload();
  }

  (async () => {
    try {
      const [formats, wallets] = await Promise.all([api("GET", "/api/trades/formats"),
        api("GET", "/api/wallets?kind=exchange&archived=all")]);
      fill(format, formats.map((f) => h("option", { value: f.id, text: f.name, title: f.note, selected: f.id === (mine.format || "generic") })));
      wallets.filter((w) => w.sync).forEach((w) => walletSel.append(h("option", { value: String(w.id), text: w.display_name })));
    } catch { /* the list still works without these */ }
    updateDownload();
  })();

  let timer;
  for (const el of [walletSel, since, until]) el.addEventListener("change", () => load());
  asset.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(), 300); });
  format.addEventListener("change", () => { ctx.saveWindowState?.({ format: format.value }); updateDownload(); });
  download.addEventListener("click", () => ctx.toast("Downloading", "The file is in your browser's downloads."));
  ctx.signal?.addEventListener("abort", () => clearTimeout(timer));
  on("wallets-changed", () => load(), ctx.signal);
  on("trades-changed", () => load(), ctx.signal);
  load();
}
