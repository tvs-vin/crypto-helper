// Overview: prices, 24h change, what you hold and what it's worth, your watchlist, and a
// price chart for any coin. Columns, sort and the watchlist are your preferences (shared by
// every Overview window); the currency, charted coin and range belong to each window, so two
// Overviews can show different ones.

import { api } from "../api.js";
import { on } from "../bus.js";
import { lineChart } from "../chart.js";
import { fill, h, icon } from "../dom.js";
import { ago, amount, changeClass, cmpDecimal, money, percent } from "../format.js";
import { can, emptyState, errorBox, loading, placeBelow, segmented, select } from "../ui.js";

const COLUMNS = { price: "Price", change_24h: "24h", holdings: "Holdings", value: "Value" };
const FIATS = ["usd", "eur", "gbp", "jpy", "cad", "aud"];
const RANGES = [["24", "24h"], ["168", "7d"], ["720", "30d"], ["8760", "1y"]];

export function renderOverview(body, ctx) {
  const holdingsAllowed = can(ctx, "wallets.view");
  const prefs = () => ctx.state.prefs;
  const mine = ctx.windowState || {};
  let chosen = mine.coin || null;
  let hours = mine.hours || "24";
  const fiatOf = () => mine.fiat || prefs().fiat; // this window's, else your default

  const total = h("div", { class: "total" });
  const meta = h("p", { class: "muted small" });
  const fiatSel = select(FIATS.map((f) => [f, f.toUpperCase()]), fiatOf(), { class: "input select sm", "aria-label": "Currency" });
  const tableArea = h("div", {}, loading());
  const chartArea = h("div", { class: "chart-area" });
  const colsBtn = h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-haspopup": "menu",
    dataset: { action: "columns" } }, icon("settings"), h("span", { text: "Columns" }));
  body.append(h("div", { class: "panel-stack" },
    h("div", { class: "overview-head" }, h("div", {}, total, meta), h("div", { class: "row" }, fiatSel, colsBtn)),
    tableArea, chartArea));

  const savePrefs = async (patch) => {
    ctx.state.prefs = await api("PATCH", "/api/me/preferences", patch);
  };
  const keep = (patch) => ctx.saveWindowState?.(patch);
  fiatSel.addEventListener("change", () => { keep({ fiat: fiatSel.value }); load().then(chart); });
  colsBtn.addEventListener("click", () => columnMenu(colsBtn));

  let data = null;
  async function load() {
    const fiat = fiatOf();
    try {
      const [prices, folio] = await Promise.all([
        api("GET", `/api/prices?fiat=${fiat}`),
        holdingsAllowed ? api("GET", `/api/portfolio?fiat=${fiat}`).catch(() => null) : null,
      ]);
      data = { prices, folio, fiat };
      draw();
    } catch (err) {
      fill(tableArea, errorBox(err));
    }
  }

  function draw() {
    const { prices, folio, fiat } = data;
    fill(total, folio ? h("span", { class: "big num", text: money(folio.total, fiat) }) : h("span", { class: "big", text: "Prices" }),
      folio ? h("span", { class: "muted", text: " portfolio" }) : null);
    fill(meta, `${prices.source} · ${ago(prices.as_of)}`,
      prices.stale ? h("span", { class: "badge warn", title: prices.error || "", text: "stale" }) : null,
      h("span", { class: "attribution", text: ` · ${prices.attribution}` }));
    const held = Object.fromEntries((folio?.coins || []).map((c) => [c.symbol, c]));
    const watch = prefs().watchlist;
    const bySymbol = Object.fromEntries(prices.prices.map((p) => [p.symbol, p]));
    let symbols = [...new Set([...watch, ...Object.keys(held)])];
    if (!symbols.length) symbols = prices.prices.map((p) => p.symbol);
    const rows = symbols.map((s) => ({ symbol: s, name: bySymbol[s]?.name || held[s]?.name || "", price: bySymbol[s]?.price ?? null,
      change_24h: bySymbol[s]?.change_24h ?? null, holdings: held[s]?.amount ?? null, value: held[s]?.value ?? null,
      watched: watch.includes(s) }));
    const sort = prefs().overview.sort;
    rows.sort((a, b) => {
      const d = sort.by === "name" ? a.name.localeCompare(b.name) : sort.by === "symbol" ? a.symbol.localeCompare(b.symbol)
        : cmpDecimal(a[sort.by] ?? null, b[sort.by] ?? null);
      return sort.direction === "asc" ? d : -d;
    });
    const cols = prefs().overview.columns.filter((c) => holdingsAllowed || !["holdings", "value"].includes(c));
    if (!rows.length) return fill(tableArea, emptyState("No prices", ""));
    const header = (key, label, right) => {
      const active = sort.by === key;
      return h("th", { scope: "col", class: right ? "r" : "", "aria-sort": active ? (sort.direction === "asc" ? "ascending" : "descending") : null },
        h("button", { class: "sort", type: "button", dataset: { sort: key }, onclick: async () => {
          await savePrefs({ overview: { ...prefs().overview, sort: { by: key, direction: active && sort.direction === "desc" ? "asc" : "desc" } } });
          draw();
        } }, label, active ? (sort.direction === "asc" ? " ↑" : " ↓") : ""));
    };
    const tbl = h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", { class: "star-col" }), header("symbol", "Coin"),
        cols.map((c) => header(c === "holdings" || c === "value" || c === "price" || c === "change_24h" ? c : c, COLUMNS[c], true)))),
      h("tbody", {}, rows.map((r) => {
        const star = h("button", { class: `star${r.watched ? " on" : ""}`, type: "button",
          "aria-label": r.watched ? `Remove ${r.symbol} from watchlist` : `Add ${r.symbol} to watchlist`,
          "aria-pressed": String(r.watched), dataset: { star: r.symbol }, text: r.watched ? "★" : "☆",
          onclick: async (e) => {
            e.stopPropagation();
            const next = r.watched ? watch.filter((s) => s !== r.symbol) : [...watch, r.symbol];
            await savePrefs({ watchlist: next });
            draw();
          } });
        const cells = { price: money(r.price, fiat), change_24h: percent(r.change_24h),
          holdings: amount(r.holdings), value: money(r.value, fiat) };
        const tr = h("tr", { class: `clickable${chosen === r.symbol ? " selected" : ""}`, tabindex: "0", dataset: { symbol: r.symbol } },
          h("td", { class: "star-col" }, star),
          h("td", {}, h("strong", { text: r.symbol }), h("span", { class: "muted small", text: ` ${r.name}` })),
          cols.map((c) => h("td", { class: `r num ${c === "change_24h" ? changeClass(r.change_24h) : ""}`, text: cells[c] })));
        tr.addEventListener("click", () => { chosen = r.symbol; keep({ coin: r.symbol }); draw(); chart(); });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") tr.click(); });
        return tr;
      })));
    fill(tableArea, h("div", { class: "table-wrap" }, tbl));
    if (prices.unpriced.length && holdingsAllowed) {
      tableArea.append(h("p", { class: "muted small", text: `No price for: ${prices.unpriced.join(", ")}` }));
    }
  }

  async function chart() {
    if (!chosen) return;
    const fiat = fiatOf();
    const rangeCtl = segmented(RANGES, hours, (v) => { hours = v; keep({ hours: v }); chart(); }, "Range");
    fill(chartArea, h("div", { class: "chart-head" }, h("h3", { text: `${chosen} price` }), rangeCtl), loading());
    try {
      const hist = await api("GET", `/api/prices/history?symbol=${chosen}&fiat=${fiat}&hours=${hours}`);
      const width = Math.max(320, chartArea.clientWidth);
      chartArea.lastChild.replaceWith(hist.rows.length >= 2 ? lineChart(hist.rows, { fiat, width })
        : emptyState("Not enough history yet", hist.rows.length
          ? "The server records a price every 10 minutes; check back soon."
          : `No ${fiat.toUpperCase()} history for ${chosen}. History is recorded for the currencies in Settings → Prices.`));
      // The chart sits under the table: bring it into view, or it opens out of sight.
      chartArea.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (err) {
      chartArea.lastChild.replaceWith(errorBox(err));
    }
  }

  function columnMenu(anchor) {
    document.querySelector(".menu")?.remove();
    const current = new Set(prefs().overview.columns);
    const menu = h("div", { class: "menu", role: "menu" }, h("div", { class: "menu-label", text: "Columns" }),
      Object.entries(COLUMNS).filter(([k]) => holdingsAllowed || !["holdings", "value"].includes(k)).map(([key, label]) => {
        const box = h("input", { type: "checkbox", checked: current.has(key), dataset: { column: key } });
        box.addEventListener("change", async () => {
          const cols = Object.keys(COLUMNS).filter((k) => (k === key ? box.checked : current.has(k)));
          current.clear();
          cols.forEach((c) => current.add(c));
          await savePrefs({ overview: { ...prefs().overview, columns: cols } });
          draw();
        });
        return h("label", { class: "menu-item" }, box, h("span", { text: label }));
      }));
    document.body.append(menu);
    placeBelow(menu, anchor);
    const close = (e) => { if (!menu.contains(e.target) && e.target !== anchor) { menu.remove(); document.removeEventListener("pointerdown", close, true); } };
    setTimeout(() => document.addEventListener("pointerdown", close, true));
  }

  on("prices-changed", load, ctx.signal);
  on("wallets-changed", load, ctx.signal);
  load().then(chart); // a restored window shows its coin's chart again
}
