// Price alerts, at the bottom of the Overview window: yours, and a form to add one. The server
// checks them whenever prices update (app/price_alerts.py) and sends a notification when one
// fires; it fires again only after the price has crossed back.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h, icon } from "../dom.js";
import { ago, money, percent } from "../format.js";
import { button, emptyState, errorBox, form, input, select } from "../ui.js";

const KINDS = [["above", "goes above"], ["below", "goes below"], ["move", "moves 24h by"]];

export function priceAlerts(area, ctx, { symbols, chosen, fiat, onChange }) {
  const list = h("div", { class: "alert-list" });
  const coin = select([], "", { name: "alert_symbol", "aria-label": "Coin", class: "input select sm" });
  const kind = select(KINDS, "above", { name: "alert_kind", "aria-label": "When", class: "input select sm" });
  const value = input({ name: "alert_value", inputmode: "decimal", required: true, autocomplete: "off",
    class: "input sm alert-value", "aria-label": "Price" });
  const unit = h("span", { class: "muted small alert-unit" });
  const setUnit = () => {
    const move = kind.value === "move";
    unit.textContent = move ? "%" : fiat().toUpperCase();
    value.placeholder = move ? "5" : "price";
    value.setAttribute("aria-label", move ? "Percent" : "Price");
  };
  kind.addEventListener("change", setUnit);
  const add = form([h("div", { class: "row alert-form" }, coin, kind, value, unit,
    button("Add alert", { kind: "btn-primary btn-sm", type: "submit", data: { action: "add-alert" } }))], async () => {
    const a = await api("POST", "/api/price-alerts", { symbol: coin.value, fiat: fiat(), kind: kind.value, value: value.value.trim() });
    value.value = "";
    ctx.toast("Alert added", a.state === "waiting"
      ? `${a.text}: that's already true, so it fires the next time it happens.`
      : `${a.text}. You'll get a notification.`);
    load();
  });
  fill(area, h("section", { class: "price-alerts" },
    h("h3", { text: "Price alerts" }),
    h("p", { class: "muted small", text: "Checked whenever prices update. Each fires once, then again only after the price has crossed back. Choose where they arrive in Settings → Notifications." }),
    list, add));

  // `prefer`: the coin just picked in the table becomes the form's coin.
  function refresh(prefer) {
    const all = symbols();
    const keep = prefer || coin.value || chosen();
    fill(coin, all.map((s) => h("option", { value: s, text: s })));
    coin.value = keep && all.includes(keep) ? keep : all[0] || "";
    setUnit();
  }

  async function load() {
    try {
      const { alerts } = await api("GET", "/api/price-alerts");
      onChange(alerts);
      if (!alerts.length) return fill(list, emptyState("No alerts yet", "Add one below, e.g. BTC goes above a price."));
      fill(list, alerts.map((a) => h("div", { class: "alert-row", dataset: { id: a.id, state: a.state } },
        icon("bell"),
        h("div", { class: "alert-main" },
          h("strong", { text: a.text }),
          h("span", { class: "muted small", text: a.price ? ` · now ${money(a.price, a.fiat)}${a.kind === "move" && a.change_24h ? ` (${percent(a.change_24h)})` : ""}` : "" })),
        a.state === "armed" ? h("span", { class: "badge ok", text: "watching" })
          : a.state === "fired" ? h("span", { class: "badge warn", title: a.last_fired_at, text: `fired ${ago(a.last_fired_at)}` })
            : h("span", { class: "badge", title: "It was already true when you added it", text: "waits to cross back" }),
        button("", { kind: "btn-sm btn-ghost", iconName: "close", title: `Delete: ${a.text}`, data: { action: "delete-alert" },
          onclick: async () => {
            try { await api("DELETE", `/api/price-alerts/${a.id}`); } catch (err) { ctx.toast("Couldn't delete it", err.message, "error"); }
            load();
          } }))));
    } catch (err) {
      fill(list, errorBox(err));
    }
  }

  // A fired alert arrives as a notification: show its new state.
  on("notification", (e) => { if (e.detail?.category === "prices") load(); }, ctx.signal);
  on("alerts-changed", () => load(), ctx.signal); // added or deleted in another window
  refresh();
  load();
  return { refresh };
}
