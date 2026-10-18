// Settings → Connections (wallets.connect): read-only exchange keys, and how often wallets
// sync. A key is checked by the server before it's saved: one that can trade or move funds is
// refused; where the exchange can't say, you confirm. Secrets are never shown again.

import { api } from "../api.js";
import { emit } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago } from "../format.js";
import { button, emptyState, errorBox, field, form, input, loading, select } from "../ui.js";

export function connectionsSection(main, ctx) {
  const list = h("div", { class: "panel-stack" }, loading());
  const adder = h("div", {});
  const timing = h("div", {});
  main.append(
    h("section", { class: "settings-block" },
      h("h3", { text: "Exchange connections" }),
      h("p", { class: "muted small", text: "A connection is a read-only API key for one exchange account. Wallets linked to it sync their balances by themselves. Keys that can trade or withdraw are refused." }),
      list, adder),
    h("section", { class: "settings-block" }, h("h3", { text: "How often" }), timing));

  let exchanges = [];

  async function load() {
    try {
      const [conns, exs, settings] = await Promise.all([
        api("GET", "/api/connections"), api("GET", "/api/sync/exchanges"), api("GET", "/api/sync/settings")]);
      exchanges = exs;
      drawList(conns);
      drawAdder();
      drawTiming(settings);
    } catch (err) {
      fill(list, errorBox(err));
    }
  }

  function drawList(conns) {
    if (!conns.length) return fill(list, emptyState("No connections yet", "Add a read-only key below, then link an exchange wallet to it (Wallets → a wallet's menu → Sync from…)."));
    fill(list, conns.map((c) => h("div", { class: "connection-row", dataset: { id: c.id } },
      h("div", { class: "grow" },
        h("strong", { text: c.label }), h("span", { class: "muted small", text: ` · ${c.masked}` }),
        h("p", { class: "muted small", text: `${c.check_summary}${c.checked_at ? ` (checked ${ago(c.checked_at)})` : ""}` }),
        c.wallets.length ? h("p", { class: "small", text: `Syncs: ${c.wallets.map((w) => w.name).join(", ")}` }) : null),
      button("Check again", { kind: "btn-sm", data: { action: "check-connection" }, onclick: async () => {
        try { await api("POST", `/api/connections/${c.id}/check`); ctx.toast("Still read-only", c.label); }
        catch (err) { ctx.toast("Check failed", err.message, "error"); }
        load();
      } }),
      button("Rename", { kind: "btn-sm btn-ghost", onclick: async () => {
        const label = window.prompt("New name", c.label);
        if (!label || label === c.label) return;
        try { await api("PATCH", `/api/connections/${c.id}`, { label }); } catch (err) { ctx.toast("Couldn't rename it", err.message, "error"); }
        load();
      } }),
      button("Remove", { kind: "btn-sm btn-ghost", data: { action: "remove-connection" }, onclick: async () => {
        try { await api("DELETE", `/api/connections/${c.id}`); ctx.toast("Connection removed", "Also delete the key on the exchange's website."); }
        catch (err) { ctx.toast("Not removed", err.message, "error"); }
        load();
      } }))));
  }

  function drawAdder() {
    if (!exchanges.length) return fill(adder, h("p", { class: "muted small", text: "No exchanges are available on this install yet." }));
    const kind = select(exchanges.map((e) => [e.id, e.name]), exchanges[0].id, { name: "exchange", "aria-label": "Exchange" });
    const label = input({ name: "connection_label", required: true, maxlength: "64", placeholder: "e.g. My Kraken" });
    const fieldsArea = h("div", { class: "panel-stack" });
    const confirmArea = h("div", {});
    let inputs = {};
    let confirmBox = null;
    const drawFields = () => {
      const ex = exchanges.find((e) => e.id === kind.value);
      inputs = {};
      confirmBox = null;
      fill(confirmArea);
      fill(fieldsArea,
        h("p", { class: "small" }, "Make a key with ", h("strong", { text: "view permission only" }), ": ",
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
    fill(adder, h("h4", { text: "Add a connection" }), form([
      h("div", { class: "grid-2" }, field("Exchange", kind), field("Name", label)),
      fieldsArea, confirmArea,
      h("div", { class: "actions" }, button("Check and save", { kind: "btn-primary", type: "submit", data: { action: "add-connection" } })),
    ], async () => {
      const body = { kind: kind.value, label: label.value.trim(),
        credentials: Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value])),
        confirm_read_only: Boolean(confirmBox?.checked) };
      try {
        await api("POST", "/api/connections", body);
      } catch (err) {
        if (err.status === 409 && err.data?.detail?.confirm) { // the exchange can't tell: you confirm
          confirmBox = h("input", { type: "checkbox", name: "confirm_read_only", required: true });
          fill(confirmArea, h("div", { class: "notice warn" }, h("p", { text: err.data.detail.message }),
            h("label", { class: "check" }, confirmBox, h("span", { text: err.data.detail.confirm }))));
          return;
        }
        throw err;
      }
      Object.values(inputs).forEach((el) => { el.value = ""; }); // never left on screen
      label.value = "";
      ctx.toast("Connection saved", "Now link an exchange wallet to it (Wallets → the wallet's menu → Sync from…).");
      emit("wallets-changed");
      load();
    }));
  }

  function drawTiming(s) {
    const on = h("input", { type: "checkbox", name: "sync_enabled", checked: s.enabled });
    const every = select([[5, "5 minutes"], [15, "15 minutes"], [30, "30 minutes"], [60, "hour"], [360, "6 hours"], [1440, "day"]].map(([v, t]) => [String(v), t]),
      String(s.interval_minutes), { name: "sync_interval", "aria-label": "Every" });
    const save = async () => {
      try {
        await api("PUT", "/api/sync/settings", { enabled: on.checked, interval_minutes: Number(every.value) });
        ctx.toast(on.checked ? `Syncing every ${every.selectedOptions[0].text}` : "Automatic syncing is off");
      } catch (err) { ctx.toast("Not saved", err.message, "error"); }
    };
    on.addEventListener("change", save);
    every.addEventListener("change", save);
    fill(timing, h("div", { class: "row" }, h("label", { class: "check" }, on, h("span", { text: "Sync automatically, every" })), every),
      h("p", { class: "muted small", text: "Sync now on a wallet works either way." }));
  }

  load();
}
