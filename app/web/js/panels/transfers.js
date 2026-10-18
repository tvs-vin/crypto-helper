// Transfers: practise moving coins between wallets. Simulated: only the numbers here change.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h } from "../dom.js";
import { amount, when } from "../format.js";
import { button, can, emptyState, errorBox, field, form, input, loading, select, table } from "../ui.js";

const LABEL = "Simulated, no real funds move";

export function renderTransfers(body, ctx) {
  const canSend = can(ctx, "transfers.create");
  const formArea = h("div", {});
  const history = h("div", {}, loading());
  const filter = select([["", "All wallets"]], "", { class: "input select sm", "aria-label": "Filter by wallet" });
  let wallets = [];
  let lastId = null;

  body.append(h("div", { class: "panel-stack" },
    h("div", { class: "banner warn", role: "note" }, h("strong", { text: LABEL }),
      " Transfers here only change the balances in this app. Nothing happens on an exchange or blockchain."),
    formArea,
    h("div", { class: "toolbar" }, h("h3", { text: "History" }), h("span", { class: "spacer" }), filter),
    history));
  filter.addEventListener("change", () => loadHistory(true));

  async function loadWallets() {
    wallets = await api("GET", "/api/wallets?archived=false&sort=name");
    fill(filter, h("option", { value: "", text: "All wallets" }),
      ...wallets.map((w) => h("option", { value: w.id, text: w.display_name, selected: String(w.id) === filter.value })));
    if (canSend) drawForm();
  }

  function drawForm() {
    if (wallets.length < 2) {
      fill(formArea, emptyState("You need two wallets", "Create another wallet to practise a transfer."));
      return;
    }
    const opt = (w) => [w.id, `${w.display_name}${w.network_name ? ` (${w.network_name})` : w.kind === "exchange" ? " (exchange)" : ""}`];
    const from = select(wallets.map(opt), wallets[0].id, { name: "from" });
    const to = select(wallets.map(opt), wallets[1].id, { name: "to" });
    const coin = select([], "", { name: "symbol" });
    const amt = input({ name: "amount", inputmode: "decimal", placeholder: "0.1", required: true, spellcheck: "false" });
    const note = input({ name: "note", maxlength: "500", placeholder: "Optional" });
    const hint = h("p", { class: "hint" });
    const byId = (id) => wallets.find((w) => String(w.id) === String(id));
    const sync = () => {
      const src = byId(from.value);
      const dst = byId(to.value);
      fill(coin, ...(src?.holdings.length ? src.holdings.map((x) => h("option", { value: x.symbol, text: `${x.symbol} (${amount(x.amount)})` }))
        : [h("option", { value: "", text: "Nothing to send" })]));
      hint.classList.remove("warn-text");
      if (src && dst && src.network && dst.network && src.network !== dst.network) {
        hint.textContent = `${src.network_name} → ${dst.network_name}: different networks. In real life the coins would be lost without a bridge, so this will be refused.`;
        hint.classList.add("warn-text");
      } else if (src?.kind === "exchange" || dst?.kind === "exchange") {
        hint.textContent = "Involves an exchange: for real, pick the matching network on its deposit/withdrawal page.";
      } else hint.textContent = "";
    };
    from.addEventListener("change", sync);
    to.addEventListener("change", sync);
    const max = button("Max", { kind: "btn-ghost btn-sm", onclick: () => {
      const x = byId(from.value)?.holdings.find((y) => y.symbol === coin.value);
      if (x) amt.value = x.amount;
    } });
    sync();
    const amtId = `t-amt-${Math.random().toString(36).slice(2, 8)}`; // unique: several windows
    fill(formArea, form([
      h("div", { class: "grid-2" }, field("From", from), field("To", to)),
      h("div", { class: "grid-3" }, field("Coin", coin), h("div", { class: "field" }, h("label", { for: amtId, text: "Amount" }),
        h("div", { class: "row" }, Object.assign(amt, { id: amtId }), max)), field("Note", note)),
      hint,
      h("div", { class: "actions" }, button("Send (simulated)", { kind: "btn-primary", type: "submit", data: { action: "send" } })),
    ], async (el) => {
      const r = await api("POST", "/api/transfers", { from_wallet_id: Number(from.value), to_wallet_id: Number(to.value),
        symbol: coin.value, amount: amt.value.trim(), note: note.value });
      ctx.toast("Transfer recorded", `${amount(r.amount)} ${r.symbol}: ${r.from_wallet_name} → ${r.to_wallet_name}. ${LABEL}.`);
      for (const w of r.warnings) ctx.toast("Remember", w, "warn", 10000);
      amt.value = "";
      note.value = "";
      el.querySelector(".notice.error")?.remove();
      emit("wallets-changed");
      emit("transfers-changed");
    }));
  }

  async function loadHistory(reset = false) {
    if (reset) lastId = null;
    try {
      const q = new URLSearchParams({ limit: "50" });
      if (filter.value) q.set("wallet_id", filter.value);
      if (lastId) q.set("before_id", lastId);
      const rows = await api("GET", `/api/transfers?${q}`);
      const tbl = table([
        { label: "When", render: (r) => h("span", { class: "muted small", text: when(r.created_at) }) },
        { label: "From → to", render: (r) => `${r.from_wallet_name} → ${r.to_wallet_name}` },
        { label: "Amount", align: "right", cls: "num", render: (r) => `${amount(r.amount)} ${r.symbol}` },
        { label: "Network", render: (r) => r.network || "—" },
        { label: "Note", render: (r) => r.note || "" },
        { label: "", render: () => h("span", { class: "badge", text: "simulated", title: LABEL }) },
      ], rows, { empty: "No transfers yet." });
      if (reset || !lastId) fill(history, tbl);
      else history.querySelector("tbody")?.append(...tbl.querySelectorAll("tbody tr"));
      history.querySelector(".more")?.remove();
      if (rows.length === 50) {
        lastId = rows.at(-1).id;
        history.append(button("Load more", { kind: "btn-ghost more", onclick: () => loadHistory() }));
      }
    } catch (err) {
      fill(history, errorBox(err));
    }
  }

  on("wallets-changed", loadWallets, ctx.signal);
  on("transfers-changed", () => loadHistory(true), ctx.signal);
  loadWallets().catch((err) => fill(formArea, errorBox(err)));
  loadHistory(true);
}
