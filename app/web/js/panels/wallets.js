// Wallets: every wallet with its nickname, colors and tags; balances and values; grouping,
// filters, your own order (drag cards); create, edit, set balances, archive, safe delete.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h, icon } from "../dom.js";
import { amount, money } from "../format.js";
import { button, can, chips, emptyState, errorBox, field, form, input, loading, segmented,
  select, sheet, table } from "../ui.js";

let metaPromise = null;
const meta = () => (metaPromise ??= api("GET", "/api/meta/networks"));

export function renderWallets(body, ctx) {
  const editable = can(ctx, "wallets.edit");
  const seesValue = can(ctx, "prices.view");
  const view = { group: "wallet", kind: "", tag: "", sort: "custom", archived: "false" };

  const list = h("div", { class: "wallet-area" }, loading());
  const summary = h("p", { class: "summary muted" });
  const kindSel = select([["", "All kinds"], ["exchange", "Exchange"], ["onchain", "On-chain"], ["paper", "Paper"]],
    "", { "aria-label": "Kind", class: "input select sm" });
  const sortSel = select([["custom", "My order"], ["name", "Name"], ["created", "Newest"],
    ...(seesValue ? [["value", "Value"]] : [])], "custom", { "aria-label": "Sort", class: "input select sm" });
  const tagIn = input({ placeholder: "Filter by tag", "aria-label": "Filter by tag", class: "input sm",
    spellcheck: "false" });
  const archivedBox = h("input", { type: "checkbox", "aria-label": "Show archived" });
  kindSel.addEventListener("change", () => { view.kind = kindSel.value; load(); });
  sortSel.addEventListener("change", () => { view.sort = sortSel.value; load(); });
  archivedBox.addEventListener("change", () => { view.archived = archivedBox.checked ? "true" : "false"; load(); });
  let tagTimer;
  tagIn.addEventListener("input", () => { clearTimeout(tagTimer); tagTimer = setTimeout(() => { view.tag = tagIn.value.trim(); load(); }, 250); });

  const toolbar = h("div", { class: "toolbar" },
    segmented([["wallet", "Wallets"], ["coin", "Coins"]], "wallet", (v) => { view.group = v; load(); }, "Group by"),
    kindSel, tagIn, sortSel,
    h("label", { class: "check" }, archivedBox, h("span", { text: "Archived" })),
    h("span", { class: "spacer" }),
    editable ? button("New wallet", { kind: "btn-primary btn-sm", iconName: "wallet", data: { action: "new-wallet" },
      onclick: () => editWallet(body, ctx, null) }) : null);
  body.append(h("div", { class: "panel-stack" }, toolbar, summary, list));

  let wallets = [];
  async function load() {
    try {
      const q = new URLSearchParams({ archived: view.archived, sort: view.sort });
      if (view.kind) q.set("kind", view.kind);
      if (view.tag) q.set("tag", view.tag);
      wallets = await api("GET", `/api/wallets?${q}`);
      const fiat = wallets[0]?.value_fiat || ctx.state.prefs?.fiat || "usd";
      if (view.group === "coin") await renderCoins(fiat);
      else renderCards(fiat);
    } catch (err) {
      fill(list, errorBox(err));
    }
  }

  function renderCards(fiat) {
    const shown = wallets.length;
    const stale = wallets.some((w) => w.prices_stale);
    fill(summary, `${shown} wallet${shown === 1 ? "" : "s"}`,
      stale ? h("span", { class: "badge warn", text: "prices stale" }) : null);
    if (!shown) {
      fill(list, emptyState(view.tag || view.kind ? "No wallets match" : "No wallets yet",
        editable ? "Create one to start tracking balances." : "", editable && !view.tag && !view.kind
          ? button("New wallet", { kind: "btn-primary", onclick: () => editWallet(body, ctx, null) }) : null));
      return;
    }
    const grid = h("div", { class: "wallet-grid" });
    for (const w of wallets) grid.append(card(w, fiat));
    fill(list, grid);
    if (view.sort === "custom") enableReorder(grid);
  }

  function card(w, fiat) {
    const band = h("div", { class: "band" });
    band.style.background = `linear-gradient(90deg, ${w.colors.primary}, ${w.colors.secondary})`;
    const where = [labelKind(w.kind), w.network_name, w.provider].filter(Boolean).join(" · ");
    const rows = w.holdings.length
      ? h("table", { class: "holdings" }, h("tbody", {}, w.holdings.map((x) => h("tr", {},
          h("td", { class: "sym", text: x.symbol }),
          h("td", { class: "r num", text: amount(x.amount) }),
          seesValue ? h("td", { class: "r num muted", text: x.value == null ? "—" : money(x.value, fiat) }) : null))))
      : h("p", { class: "muted small", text: "No balances yet." });
    const menuBtn = editable ? h("button", { class: "win-btn", type: "button", "aria-label": `Actions for ${w.display_name}`,
      dataset: { action: "wallet-menu" }, onclick: (e) => walletMenu(e.currentTarget, w) }, icon("apps")) : null;
    const el = h("article", { class: `wallet-card${w.archived ? " archived" : ""}`, dataset: { id: w.id },
      draggable: view.sort === "custom" ? "true" : null },
      band,
      h("header", {},
        h("div", { class: "titles" },
          h("h3", { class: "nick", text: w.display_name }),
          w.nickname ? h("p", { class: "name", text: w.name }) : null,
          h("p", { class: "where", text: where })),
        menuBtn),
      chips(w.tags, w.system_tags.filter((t) => !t.startsWith("coin:"))),
      rows,
      seesValue ? h("footer", {}, h("span", { class: "muted", text: "Total" }),
        h("strong", { class: "num", text: w.value == null ? "—" : money(w.value, fiat) })) : null);
    const dot = h("span", { class: "color-dot" });
    dot.style.background = w.colors.primary;
    el.querySelector(".nick").prepend(dot);
    return el;
  }

  async function renderCoins(fiat) {
    const [totals, folio] = await Promise.all([
      api("GET", `/api/holdings/summary?include_archived=${view.archived === "true"}`),
      seesValue ? api("GET", `/api/portfolio?include_archived=${view.archived === "true"}`).catch(() => null) : null,
    ]);
    const values = Object.fromEntries((folio?.coins || []).map((c) => [c.symbol, c]));
    fill(summary, `${totals.length} coin${totals.length === 1 ? "" : "s"}`,
      folio ? h("span", { class: "muted", text: ` · total ${money(folio.total, folio.fiat)}` }) : null);
    const byCoin = {};
    for (const w of wallets) for (const x of w.holdings) (byCoin[x.symbol] ??= []).push([w, x]);
    fill(list, table([
      { label: "Coin", render: (r) => h("strong", { text: r.symbol }) },
      { label: "Total", align: "right", cls: "num", render: (r) => amount(r.total) },
      ...(seesValue ? [{ label: "Value", align: "right", cls: "num", render: (r) => money(values[r.symbol]?.value ?? null, folio?.fiat || fiat) }] : []),
      { label: "Held in", render: (r) => h("div", { class: "held-in" }, (byCoin[r.symbol] || []).map(([w, x]) =>
        h("span", { class: "chip", text: `${w.display_name}: ${amount(x.amount)}` }))) },
    ], totals, { empty: "No balances yet." }));
  }

  function walletMenu(anchor, w) {
    document.querySelector(".menu")?.remove();
    const item = (text, action, fn, danger = false) => h("button", { class: `menu-item${danger ? " danger" : ""}`,
      type: "button", role: "menuitem", dataset: { action }, onclick: () => { menu.remove(); fn(); } }, h("span", { text }));
    const menu = h("div", { class: "menu", role: "menu" },
      item("Set a balance", "set-balance", () => setBalance(body, w)),
      item("Edit", "edit", () => editWallet(body, ctx, w)),
      item(w.archived ? "Unarchive" : "Archive", "archive", async () => {
        try {
          await api("PATCH", `/api/wallets/${w.id}`, { archived: !w.archived });
          emit("wallets-changed");
        } catch (err) { ctx.toast("Couldn't change it", err.message, "error"); }
      }),
      item("Delete…", "delete", () => deleteWallet(body, w, wallets), true));
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    Object.assign(menu.style, { top: `${r.bottom + 4}px`, left: `${Math.max(8, r.right - 220)}px` });
    const close = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("pointerdown", close, true); } };
    setTimeout(() => document.addEventListener("pointerdown", close, true));
    menu.querySelector("button")?.focus();
  }

  function enableReorder(grid) {
    let dragged = null;
    grid.addEventListener("dragstart", (e) => {
      dragged = e.target.closest(".wallet-card");
      dragged?.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    grid.addEventListener("dragover", (e) => {
      if (!dragged) return;
      e.preventDefault();
      const over = e.target.closest(".wallet-card");
      if (!over || over === dragged) return;
      const r = over.getBoundingClientRect();
      const after = e.clientY > r.top + r.height / 2 || e.clientX > r.left + r.width / 2;
      over.parentNode.insertBefore(dragged, after ? over.nextSibling : over);
    });
    grid.addEventListener("dragend", async () => {
      dragged?.classList.remove("dragging");
      dragged = null;
      const ids = [...grid.querySelectorAll(".wallet-card")].map((c) => Number(c.dataset.id));
      try {
        await api("PUT", "/api/me/wallet-order", { wallet_ids: ids });
      } catch (err) { ctx.toast("Couldn't save the order", err.message, "warn"); }
    });
  }

  on("wallets-changed", load, ctx.signal);
  on("prices-changed", load, ctx.signal);
  load();
}

const labelKind = (k) => ({ exchange: "Exchange", onchain: "On-chain", paper: "Paper" }[k] || k);

// ---- dialogs -------------------------------------------------------------------------------

function editWallet(body, ctx, w) {
  sheet(body, w ? `Edit ${w.display_name}` : "New wallet", (close) => {
    const name = input({ value: w?.name || "", required: true, maxlength: "64", spellcheck: "false", name: "name" });
    const nick = input({ value: w?.nickname || "", maxlength: "64", name: "nickname", placeholder: "Shown as the big title" });
    let kind = w?.kind || "paper";
    const kindCtl = segmented([["exchange", "Exchange"], ["onchain", "On-chain"], ["paper", "Paper"]], kind,
      (v) => { kind = v; sync(); }, "Kind");
    const network = select([["", "Loading…"]], "", { name: "network" });
    const provider = input({ value: w?.provider || "", maxlength: "64", name: "provider", placeholder: "Coinbase, Ledger, MetaMask…" });
    const address = input({ value: w?.address || "", maxlength: "128", name: "address", spellcheck: "false",
      placeholder: "Public address (optional)" });
    const notes = h("textarea", { class: "input textarea", maxlength: "4000", name: "notes", rows: "3" });
    notes.value = w?.notes || "";
    const tags = input({ value: (w?.tags || []).join(", "), name: "tags", placeholder: "long-term, savings" });
    const primary = h("input", { type: "color", class: "color", name: "color_primary", value: w?.colors.primary || "#7545fc" });
    const autoPrimary = h("input", { type: "checkbox", checked: !w || w.colors.primary_is_default });
    let mode = w?.colors.secondary_mode || "auto";
    const secondary = h("input", { type: "color", class: "color", name: "color_secondary", value: w?.colors.secondary || "#5f33cc" });
    const scheme = select([["analogous", "Analogous"], ["complementary", "Complementary"], ["triadic", "Triadic"], ["shade", "Shade"]],
      w?.colors.scheme || "analogous", { name: "color_scheme" });
    const modeCtl = segmented([["auto", "Automatic"], ["custom", "Pick"]], mode, (v) => { mode = v; sync(); }, "Second color");
    const netField = field("Network", network, "On-chain wallets live on exactly one network.");
    const schemeWrap = h("span", {}, scheme);
    const secondaryWrap = h("span", {}, secondary);

    function sync() {
      netField.classList.toggle("hidden", kind === "exchange");
      schemeWrap.classList.toggle("hidden", mode !== "auto");
      secondaryWrap.classList.toggle("hidden", mode !== "custom");
      primary.disabled = autoPrimary.checked;
    }
    autoPrimary.addEventListener("change", sync);
    meta().then((m) => {
      fill(network, ...[["", kind === "paper" ? "No network" : "Choose…"], ...Object.entries(m.networks)]
        .map(([v, t]) => h("option", { value: v, text: t, selected: v === (w?.network || "") })));
    });
    sync();

    return form([
      h("div", { class: "grid-2" }, field("Name", name, "Unique; used to confirm deleting."),
        field("Nickname", nick, "The big title on the card.")),
      field("Kind", kindCtl),
      netField,
      h("div", { class: "grid-2" }, field("Provider", provider), field("Public address", address,
        "From the wallet's Receive screen. Never a recovery phrase or private key.")),
      field("Tags", tags, "Up to 20, comma-separated."),
      field("Notes", notes),
      h("div", { class: "field" }, h("label", { text: "Colors" }),
        h("div", { class: "color-row" },
          h("label", { class: "check" }, autoPrimary, h("span", { text: "Main color from the name" })), primary),
        h("div", { class: "color-row" }, modeCtl, schemeWrap, secondaryWrap)),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button(w ? "Save" : "Create wallet", { kind: "btn-primary", type: "submit" })),
    ], async () => {
      const body = {
        name: name.value, nickname: nick.value || null, kind,
        network: kind === "exchange" ? null : network.value || null,
        provider: provider.value || null, address: address.value.trim() || null, notes: notes.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        color_primary: autoPrimary.checked ? null : primary.value,
        color_secondary_mode: mode, color_scheme: scheme.value,
        ...(mode === "custom" ? { color_secondary: secondary.value } : {}),
      };
      if (w) await api("PATCH", `/api/wallets/${w.id}`, body);
      else await api("POST", "/api/wallets", body);
      close();
      ctx.toast(w ? "Saved" : "Wallet created", body.nickname || body.name);
      emit("wallets-changed");
    });
  });
}

function setBalance(body, w) {
  sheet(body, `Balance in ${w.display_name}`, (close) => {
    const sym = input({ name: "symbol", required: true, maxlength: "10", placeholder: "BTC", spellcheck: "false",
      autocapitalize: "characters", list: "coin-list" });
    const amt = input({ name: "amount", required: true, inputmode: "decimal", placeholder: "0.25", spellcheck: "false" });
    const list = h("datalist", { id: "coin-list" });
    api("GET", "/api/prices/supported").then((s) => fill(list, ...s.coins.map((c) => h("option", { value: c.symbol, text: c.name }))))
      .catch(() => {});
    return form([
      h("p", { class: "muted", text: "Type the exact amount you hold. Up to 18 decimal places; 0 removes the coin." }),
      h("div", { class: "grid-2" }, field("Coin", sym), field("Amount", amt)), list,
      w.holdings.length ? h("div", { class: "chips" }, w.holdings.map((x) => h("button", { class: "chip button", type: "button",
        text: `${x.symbol} ${amount(x.amount)}`, onclick: () => { sym.value = x.symbol; amt.value = x.amount; amt.focus(); } }))) : null,
      h("div", { class: "actions" }, button("Cancel", { onclick: close }), button("Save balance", { kind: "btn-primary", type: "submit" })),
    ], async () => {
      await api("PUT", `/api/wallets/${w.id}/holdings/${encodeURIComponent(sym.value.trim().toUpperCase())}`,
        { amount: amt.value.trim() });
      close();
      emit("wallets-changed");
    });
  });
}

function deleteWallet(body, w, all) {
  sheet(body, `Delete ${w.display_name}`, (close) => {
    const area = h("div", { class: "panel-stack" });
    const done = () => { close(); emit("wallets-changed"); emit("transfers-changed"); };
    const run = async (fn) => {
      area.querySelector(".notice.error")?.remove();
      try { await fn(); done(); } catch (e) { area.prepend(errorBox(e)); }
    };
    if (!w.holdings.length) {
      // Empty: still ask. (The server refuses anyway if it turns out to hold something.)
      area.append(
        h("p", { text: `${w.display_name} holds nothing. Delete it? Transfer history keeps its name.` }),
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Delete wallet", { kind: "btn-danger", data: { action: "confirm-delete" },
            onclick: () => run(() => api("DELETE", `/api/wallets/${w.id}`)) })));
      return area;
    }
    const others = all.filter((o) => o.id !== w.id && !o.archived);
    const target = select(others.map((o) => [o.id, o.display_name]), others[0]?.id, { "aria-label": "Move to" });
    const confirmIn = input({ placeholder: w.name, spellcheck: "false", autocomplete: "off",
      "aria-label": "Type the wallet name" });
    const forceBtn = button("Delete with its balances", { kind: "btn-danger", disabled: true,
      data: { action: "force-delete" } });
    confirmIn.addEventListener("input", () => { forceBtn.disabled = confirmIn.value !== w.name; });
    forceBtn.addEventListener("click", () => run(() =>
      api("DELETE", `/api/wallets/${w.id}?force=true&confirm_name=${encodeURIComponent(confirmIn.value)}`)));
    area.append(
      h("p", { text: "This wallet still holds:" }),
      h("div", { class: "chips" }, w.holdings.map((x) => h("span", { class: "chip", text: `${amount(x.amount)} ${x.symbol}` }))),
      h("section", { class: "choice" }, h("h3", { text: "Move everything, then delete" }),
        h("p", { class: "muted", text: "All or nothing: if any coin can't go there (network rules), nothing moves." }),
        others.length ? h("div", { class: "row" }, target, button("Move and delete", { kind: "btn-primary",
          data: { action: "move-delete" }, onclick: () => run(() => api("DELETE", `/api/wallets/${w.id}?move_to=${target.value}`)) }))
          : h("p", { class: "muted", text: "No other active wallet to move into." })),
      h("section", { class: "choice" }, h("h3", { text: "Archive instead" }),
        h("p", { class: "muted", text: "Hides it and freezes its balances. Nothing is lost; you can unarchive later." }),
        button("Archive", { data: { action: "archive-instead" },
          onclick: () => run(() => api("PATCH", `/api/wallets/${w.id}`, { archived: true })) })),
      h("section", { class: "choice danger" }, h("h3", { text: "Delete it anyway" }),
        h("p", { text: "The balances above are deleted for good. Transfer history keeps the wallet's name. To confirm, type its name:" }),
        h("p", {}, h("code", { text: w.name })),
        h("div", { class: "row" }, confirmIn, forceBtn)));
    return area;
  });
}
