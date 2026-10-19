// Synced wallets (phase 2) in the Wallets window: the status line on a card, Sync now, and
// choosing where a wallet's balances come from.

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago, amount } from "../format.js";
import { button, can, emptyState, errorBox, field, form, input, loading, select, sheet } from "../ui.js";

/** The line under a synced wallet's title: where from, when, and any problem. */
export function syncLine(w) {
  const s = w.sync;
  if (!s) return null;
  const status = s.last_error
    ? h("span", { class: "badge warn", title: s.last_error, text: "sync problem" })
    : s.last_ok_at ? h("span", { class: "badge ok", text: `synced ${ago(s.last_ok_at)}` })
      : h("span", { class: "badge", text: "not synced yet" });
  const info = s.info || {};
  const found = info.used_addresses != null
    ? `${info.used_addresses} address${info.used_addresses === 1 ? "" : "es"} in use${info.types?.length ? ` · ${info.types.join(", ")}` : ""}`
    : null;
  return h("div", { class: "sync-line" },
    h("span", { class: "muted small", text: `From ${s.label}` }), status,
    found ? h("p", { class: "muted small", text: found }) : null,
    s.last_error ? h("p", { class: "warn-text small", text: s.last_error }) : null,
    s.untracked?.length ? h("p", { class: "muted small", title: "Coins the app doesn't track aren't added (scam tokens are common). Add a coin under Settings → Prices to track it.",
      text: `Not tracked: ${s.untracked.map((u) => `${amount(u.amount)} ${u.asset}`).join(", ")}` }) : null);
}

export async function syncNow(ctx, w) {
  try {
    const r = await api("POST", `/api/wallets/${w.id}/sync`);
    if (r.ok) ctx.toast(`${w.display_name} synced`, r.changes.length ? r.changes.join("; ") : "Nothing changed.");
    else ctx.toast(`${w.display_name} didn't sync`, r.error, "error");
  } catch (err) {
    ctx.toast("Couldn't sync", err.message, "error");
  }
  emit("wallets-changed");
}

const SCRIPTS = [["auto", "Find out automatically"], ["wpkh", "Native SegWit (bc1q…)"], ["tr", "Taproot (bc1p…)"],
  ["sh-wpkh", "Nested SegWit (3…)"], ["pkh", "Legacy (1…)"]];

/** Where a wallet's balances come from: typed in, an exchange connection, or addresses. */
export function sourceSheet(body, ctx, w) {
  if (w.kind === "onchain") return chainSheet(body, ctx, w);
  sheet(body, `Balances of ${w.display_name}`, (close) => {
    const area = h("div", { class: "panel-stack" }, loading());
    (async () => {
      try {
        const conns = await api("GET", "/api/connections");
        const current = w.sync?.connection_id ?? "manual";
        const choice = (value, title, text) => {
          const radio = h("input", { type: "radio", name: "source", value: String(value), checked: String(current) === String(value) });
          return h("label", { class: "choice" }, radio, h("span", {}, h("strong", { text: title }), h("span", { class: "muted small", text: text })));
        };
        fill(area, form([
          choice("manual", "Typed in", "You set the balances yourself (as before)."),
          conns.length ? conns.map((c) => choice(c.id, `Sync from ${c.label}`, `${c.exchange} · ${c.masked}`))
            : emptyState("No connections yet", "Add a read-only exchange key in Settings → Connections first."),
          w.holdings.length && !w.sync ? h("p", { class: "notice", text: "Syncing replaces the balances typed in here with the ones on the exchange." }) : null,
          h("div", { class: "actions" }, button("Cancel", { onclick: close }),
            button("Save", { kind: "btn-primary", type: "submit", data: { action: "save-source" } })),
        ], async (f) => {
          const picked = f.querySelector("input[name=source]:checked")?.value || "manual";
          const bodyOut = picked === "manual" ? { kind: "manual" } : { kind: "exchange", connection_id: Number(picked) };
          await api("PUT", `/api/wallets/${w.id}/source`, bodyOut);
          close();
          if (picked !== "manual") await syncNow(ctx, w);
          else emit("wallets-changed");
        }));
      } catch (err) {
        fill(area, errorBox(err));
      }
    })();
    return area;
  });
}

let syncable = null; // networks that can sync from addresses: set by the Wallets window
export function setSyncable(list) { syncable = new Set(list || []); }

export const canLink = (ctx, w) => (w.kind === "exchange" || (w.kind === "onchain" && syncable?.has(w.network)))
  && can(ctx, "wallets.connect") && can(ctx, "wallets.edit");

/** An on-chain wallet: its addresses, or (Bitcoin) an extended public key. */
function chainSheet(body, ctx, w) {
  sheet(body, `Balances of ${w.display_name}`, (close) => {
    const bitcoin = w.network === "bitcoin";
    const current = w.sync ? (w.sync.label?.includes("pub…") ? "xpub" : "addresses") : "manual";
    const radio = (value, title, text) => h("label", { class: "choice" },
      h("input", { type: "radio", name: "source", value, checked: current === value }),
      h("span", {}, h("strong", { text: title }), h("span", { class: "muted small", text })));
    const addresses = h("textarea", { class: "input textarea", name: "watch_addresses", rows: "3", spellcheck: "false",
      placeholder: "One public address per line" });
    addresses.value = w.address || "";
    const xpub = input({ name: "watch_xpub", spellcheck: "false", autocomplete: "off", placeholder: "zpub… / xpub… / ypub…" });
    const script = select(SCRIPTS, "auto", { name: "watch_script", "aria-label": "Address type" });
    return form([
      radio("manual", "Typed in", "You set the balances yourself."),
      radio("addresses", "Sync from addresses", bitcoin
        ? "Public addresses (bc1…, 1…, 3…). A hardware or phone wallet uses a new address for every payment: an xpub (below) sees them all."
        : "Public addresses (0x…): the network's coin plus USDC, USDT and other listed tokens."),
      field("Addresses", addresses, "Up to 50, one per line. Public addresses only: they can't spend anything."),
      bitcoin ? radio("xpub", "Sync from an extended public key (xpub)", "Sees the whole wallet, change included. It can't spend, but it reveals every address of the wallet, so it's stored encrypted.") : null,
      bitcoin ? h("div", { class: "grid-2" }, field("Extended public key", xpub, "Starts with xpub, ypub or zpub. Never an xprv: that one can spend."),
        field("Address type", script)) : null,
      w.holdings.length && !w.sync ? h("p", { class: "notice", text: "Syncing replaces the balances typed in here with the ones on the blockchain." }) : null,
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button("Save", { kind: "btn-primary", type: "submit", data: { action: "save-source" } })),
    ], async (f) => {
      const picked = f.querySelector("input[name=source]:checked")?.value || "manual";
      const out = picked === "manual" ? { kind: "manual" }
        : picked === "xpub" ? { kind: "onchain", xpub: xpub.value.trim(), script: script.value }
          : { kind: "onchain", addresses: addresses.value.split(/\s+/).filter(Boolean) };
      await api("PUT", `/api/wallets/${w.id}/source`, out);
      xpub.value = ""; // not left on screen
      close();
      if (picked !== "manual") await syncNow(ctx, w);
      else emit("wallets-changed");
    });
  });
}
