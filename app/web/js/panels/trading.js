// Live trading (phase 4, real money): your trading keys and your cap. Keys may read and trade,
// never withdraw: the server checks each one with the exchange before saving it. Placing
// orders comes in later parts (13b-13c); nothing here trades yet.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago, money } from "../format.js";
import { button, emptyState, errorBox, field, form, input, loading, select, sheet } from "../ui.js";

export function renderTrading(body, ctx) {
  const area = h("div", { class: "panel-stack" }, loading());
  body.append(area);
  let data = null;
  let typing = false; // unsaved typing in the window: live updates wait, so it isn't wiped
  area.addEventListener("input", () => { typing = true; });

  async function load(fromUpdate = false) {
    if (fromUpdate && typing) return;
    try {
      data = await api("GET", "/api/trading");
      draw();
    } catch (err) {
      fill(area, errorBox(err));
    }
  }

  function draw() {
    const onExchanges = data.exchanges.filter((e) => e.on);
    fill(area,
      h("div", { class: `notice ${data.live_allowed ? "" : "warn"}`, dataset: { live: String(data.live_allowed) } },
        h("strong", { text: "Real money." }),
        h("p", { class: "small", text: "Trading keys can read and trade on an exchange, never withdraw. Live bots (coming in the next parts) trade with them, within your cap." }),
        h("p", { class: "small", text: data.live_allowed
          ? "Ready for live trading: green."
          : "Ready for live trading isn't green yet (Paper trading), so no live order can be placed (project rule 10)." })),
      capSection(),
      keySection(onExchanges));
  }

  function capSection() {
    const c = data.caps;
    const box = h("section", { class: "panel-stack" },
      h("h3", { text: "Your cap" }),
      h("p", { class: "trading-cap" }, h("span", { class: "big num", dataset: { role: "cap" }, text: money(c.cap, "usd") }),
        h("span", { class: "muted small", text: c.cap_is_default ? " (the default)" : "" })),
      h("p", { class: "muted small", text: `The most your live bots may control at once, in USD. ${c.ceiling ? `An admin set a ceiling of ${money(c.ceiling, "usd")}.` : "No ceiling set."}` }));
    if (!data.may.change_cap) {
      box.append(h("p", { class: "muted small", text: "An admin sets your cap (Users)." }));
      return box;
    }
    const amount = input({ name: "cap", inputmode: "decimal", value: c.cap, class: "input sm", "aria-label": "Cap in USD" });
    const code = input({ name: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "8", class: "input sm", placeholder: "only to raise it" });
    box.append(form([
      h("div", { class: "row" }, field("New cap (USD)", amount), field("2FA code", code, "Raising it needs a current code")),
      h("div", { class: "actions" }, button("Save cap", { kind: "btn-sm btn-primary", type: "submit", data: { action: "save-cap" } })),
    ], async () => {
      data.caps = await api("PUT", "/api/trading/me/cap", { cap: amount.value.trim(), code: code.value.trim() || null });
      code.value = "";
      typing = false;
      ctx.toast("Cap saved", money(data.caps.cap, "usd"));
      draw();
    }));
    return box;
  }

  function keySection(onExchanges) {
    const may = data.may;
    const canAdd = (may.trade || may.shared_keys) && may.two_factor && onExchanges.length;
    const why = !may.two_factor ? "Turn on two-factor login first (Settings → Account)."
      : !onExchanges.length ? "Live trading isn't switched on for any exchange yet (super, in Services)."
        : "";
    return h("section", { class: "panel-stack" },
      h("div", { class: "row" }, h("h3", { text: "Trading keys" }), h("span", { class: "spacer" }),
        button("Add a trading key", { kind: "btn-sm btn-primary", disabled: !canAdd, data: { action: "add-key" }, onclick: () => addKey(onExchanges) })),
      why ? h("p", { class: "muted small", dataset: { role: "why" }, text: why }) : null,
      data.keys.length ? h("div", { class: "panel-stack" }, data.keys.map(keyCard))
        : emptyState("No trading keys", "Add one for an exchange that's switched on. Make it on the exchange with trading allowed and withdrawals off, locked to this server's address."));
  }

  function keyCard(k) {
    return h("div", { class: "key-card", dataset: { key: k.id } },
      h("div", { class: "row" }, h("strong", { text: k.label }), h("span", { class: "muted small", text: ` ${k.masked}` }),
        h("span", { class: "spacer" }),
        h("span", { class: `badge ${k.shared ? "warn" : "ok"}`, text: k.shared ? "shared" : "personal" })),
      h("p", { class: "small", text: k.check }),
      k.ip_locked === false ? h("p", { class: "small warn-text", text: "Not locked to this server's address: lock it on the exchange (its API key settings)." }) : null,
      k.exchange_on ? null : h("p", { class: "small warn-text", text: `Live trading on ${k.exchange} is switched off.` }),
      h("p", { class: "muted small", text: `Added by ${k.created_by} ${ago(k.created_at)}${k.checked_at ? `; checked ${ago(k.checked_at)}` : ""}.` }),
      h("div", { class: "actions" },
        button("Check again", { kind: "btn-sm", data: { action: "recheck-key" }, onclick: async () => {
          try { await api("POST", `/api/trading/keys/${k.id}/check`); ctx.toast("Checked", k.label); } catch (err) { ctx.toast("Check failed", err.message, "error"); }
          load();
        } }),
        button("Delete", { kind: "btn-sm btn-ghost", data: { action: "delete-key" }, onclick: async () => {
          try { await api("DELETE", `/api/trading/keys/${k.id}`); ctx.toast("Key deleted", "Delete it on the exchange's website too."); } catch (err) { ctx.toast("Not deleted", err.message, "error"); }
          load();
        } })));
  }

  function addKey(onExchanges) {
    sheet(body, "Add a trading key", (close) => {
      const kind = select(onExchanges.map((e) => [e.id, e.name]), onExchanges[0].id, { name: "exchange", "aria-label": "Exchange" });
      const label = input({ name: "key_label", required: true, maxlength: "64", placeholder: "e.g. My Kraken trading" });
      const scope = select([...(data.may.trade ? [["personal", "Personal (only your bots)"]] : []), ...(data.may.shared_keys ? [["shared", "Shared (people allowed shared keys)"]] : [])],
        data.may.trade ? "personal" : "shared", { name: "scope", "aria-label": "Who may use it" });
      const fieldsArea = h("div", { class: "panel-stack" });
      const confirmArea = h("div", {});
      let inputs = {};
      let confirmBox = null;
      const drawFields = () => {
        const ex = onExchanges.find((e) => e.id === kind.value);
        inputs = {};
        confirmBox = null;
        fill(confirmArea);
        fill(fieldsArea,
          h("p", { class: "small" }, "Make a key that can ", h("strong", { text: "trade but never withdraw" }), ", locked to this server's address: ",
            h("a", { href: "#", class: "help-link", text: `${ex.name} guide`, onclick: (e) => { e.preventDefault(); ctx.wm?.openHelp?.(ex.guide); } })),
          ex.fields.map((f) => {
            const control = f.multiline
              ? h("textarea", { class: "input textarea", name: `cred_${f.name}`, rows: "4", required: true, spellcheck: "false", autocomplete: "off" })
              : input({ name: `cred_${f.name}`, type: f.secret ? "password" : "text", required: true, autocomplete: "off", spellcheck: "false" });
            inputs[f.name] = control;
            return field(f.label, control, f.help || null);
          }));
      };
      kind.addEventListener("change", drawFields);
      drawFields();
      return form([
        h("div", { class: "grid-2" }, field("Exchange", kind), field("Name", label)),
        field("Who may use it", scope),
        fieldsArea, confirmArea,
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Check and save", { kind: "btn-primary", type: "submit", data: { action: "save-key" } })),
      ], async () => {
        const payload = { kind: kind.value, label: label.value.trim(), shared: scope.value === "shared",
          credentials: Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value])),
          confirm_no_withdrawals: Boolean(confirmBox?.checked) };
        try {
          await api("POST", "/api/trading/keys", payload);
        } catch (err) {
          if (err.status === 409 && err.data?.detail?.confirm) { // the exchange can't tell: you confirm
            confirmBox = h("input", { type: "checkbox", name: "confirm_no_withdrawals", required: true });
            fill(confirmArea, h("div", { class: "notice warn" }, h("p", { text: err.data.detail.message }),
              h("label", { class: "check" }, confirmBox, h("span", { text: err.data.detail.confirm }))));
            return;
          }
          throw err;
        }
        Object.values(inputs).forEach((el) => { el.value = ""; }); // never left on screen
        close();
        ctx.toast("Trading key saved", "Checked with the exchange.");
        load();
      });
    });
  }

  on("trading-changed", () => load(true), ctx.signal);
  load();
}
