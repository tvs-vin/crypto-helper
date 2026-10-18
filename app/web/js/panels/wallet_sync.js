// Synced wallets (phase 2) in the Wallets window: the status line on a card, Sync now, and
// choosing where a wallet's balances come from.

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago, amount } from "../format.js";
import { button, can, emptyState, errorBox, form, loading, sheet } from "../ui.js";

/** The line under a synced wallet's title: where from, when, and any problem. */
export function syncLine(w) {
  const s = w.sync;
  if (!s) return null;
  const status = s.last_error
    ? h("span", { class: "badge warn", title: s.last_error, text: "sync problem" })
    : s.last_ok_at ? h("span", { class: "badge ok", text: `synced ${ago(s.last_ok_at)}` })
      : h("span", { class: "badge", text: "not synced yet" });
  return h("div", { class: "sync-line" },
    h("span", { class: "muted small", text: `From ${s.label}` }), status,
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

/** Where a wallet's balances come from: typed in (manual) or an exchange connection. */
export function sourceSheet(body, ctx, w) {
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

export const canLink = (ctx, w) => w.kind === "exchange" && can(ctx, "wallets.connect") && can(ctx, "wallets.edit");
