// Services (services.manage): system services through the agent, feature switches for the
// whole install, and the self-test. The server checks everything; this only shows it.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h } from "../dom.js";
import { ago } from "../format.js";
import { button, copyable, errorBox, loading, toggle } from "../ui.js";

const FEATURES = [
  ["paper_wallets", "Paper wallets", "Practice wallets with made-up balances. Off: no new ones (existing ones stay)."],
  ["practice_transfers", "Practice transfers", "Simulated transfers between tracked wallets. Off: history stays, no new transfers."],
  ["price_history", "Price history recording", "Saves prices every few minutes for the charts (settings in Settings → Prices)."],
  ["balance_history", "Balance history recording", "Saves every wallet's balances and value every hour for the value-over-time charts (settings in Settings → Prices)."],
];

export function renderServices(body, ctx) {
  const area = h("div", { class: "panel-stack" }, loading());
  body.append(area);
  let poll = null;
  ctx.signal.addEventListener("abort", () => clearTimeout(poll));

  async function load() {
    clearTimeout(poll);
    try {
      const data = await api("GET", "/api/services");
      fill(area, agentNotice(data), systemSection(data), featureSection(data), liveSection(data), testSection(data));
      if (data.selftest.running) poll = setTimeout(load, 2000);
    } catch (err) {
      fill(area, errorBox(err));
    }
  }

  const act = async (fn, msg, after) => {
    try {
      const out = await fn();
      if (msg) ctx.toast(msg);
      after?.(out);
    } catch (err) {
      ctx.toast("Couldn't do that", err.message, "error");
    }
    load();
  };

  function agentNotice(data) {
    if (data.agent.available) return null;
    return h("div", { class: "notice warn" },
      h("strong", { text: "The agent is off. " }),
      "Feature switches and the self-test work, but system services can't be switched from here until it's on. On the VM run:",
      copyable(data.agent.command));
  }

  function state(s) {
    if (!s) return h("span", { class: "badge", text: "unknown" });
    const good = s.active === "active";
    return h("span", { class: `badge ${good ? "ok" : "warn"}`, text: s.active });
  }

  function row(name, desc, s, controls, extra = null) {
    return h("div", { class: "service-row", dataset: { service: name.toLowerCase().split(" ")[0] } },
      // s === undefined: not a system service (no running state to show).
      h("div", {}, h("div", { class: "row" }, h("strong", { text: name }), s === undefined ? null : state(s)),
        h("p", { class: "muted small", text: desc }), extra),
      h("div", { class: "row service-controls" }, controls));
  }

  function systemSection(data) {
    const s = data.services || {};
    const off = !data.agent.available;
    const embedOn = s.embed ? s.embed.configured : data.embed.enabled;
    const backupsOn = s.backups ? s.backups.enabled === "enabled" : null;
    const restart = (svc, label) => button(label, { kind: "btn-sm", disabled: off, data: { action: `restart-${svc}` },
      onclick: () => act(() => api("POST", `/api/services/${svc}/restart`), svc === "web" ? "Restarting the web UI: it's back in a few seconds" : "Restarted") });
    return h("section", { class: "panel-stack" },
      h("h3", { text: "System services" }),
      row("Web UI", "This app. Restarting it reconnects in a few seconds.", s.web, [restart("web", "Restart")]),
      row("Embed server", "Serves embed links (Settings → Embeds) on its own port.", s.embed,
        [toggle(embedOn, off, off ? "Needs the agent" : "Turn the embed server on or off",
          (v) => act(() => api("POST", "/api/services/embed/switch", { on: v }), `Embed server ${v ? "on" : "off"}`), "switch-embed"),
        restart("embed", "Restart")],
        h("p", { class: "muted small", text: `Links use ${data.embed.links}` })),
      row("Daily backups", "Copies the database once a day and keeps the newest 14.", s.backups,
        // Without the agent their state is unknown: show that rather than a guessed "Off".
        [backupsOn === null ? h("span", { class: "muted small", text: "state unknown" })
          : toggle(backupsOn, off, "Turn daily backups on or off",
            (v) => act(() => api("POST", "/api/services/backups/switch", { on: v }), `Daily backups ${v ? "on" : "off"}`), "switch-backups"),
        button("Back up now", { kind: "btn-sm", disabled: off, data: { action: "backup-now" },
          onclick: () => act(() => api("POST", "/api/services/backups/run"), "Backup started") })],
        h("p", { class: "muted small", text: data.backup ? `Newest: ${data.backup.name}, ${ago(new Date(data.backup.modified * 1000).toISOString().slice(0, 19))}` : "No backups yet." })),
      shellRow("console", "Console", "Lets people with the Console permission run a fixed set of crypto-helper commands (status, doctor, logs…).", s, off),
      shellRow("terminal", "Terminal", "Lets people with the Terminal permission open the VM's login prompt in a window. They still need a Linux password.", s, off),
      row("Agent", "The root helper that switches the services above. Managed from the VM only.",
        off ? { active: "off" } : s.agent,
        [off ? null : h("code", { class: "small", title: "To turn it off, on the VM", text: "sudo crypto-helper agent disable" })]));
  }

  function shellRow(key, name, desc, s, off) {
    const isOn = s[key]?.active === "on";
    return row(name, desc, s[key] ? { active: s[key].active } : null,
      [s[key] ? toggle(isOn, off, off ? "Needs the agent" : `Turn the ${name} on or off`,
        (v) => act(() => api("POST", `/api/services/${key}/switch`, { on: v }), `${name} ${v ? "on" : "off"}`), `switch-${key}`)
        : h("span", { class: "muted small", text: "state unknown" })]);
  }

  function feature(data, key, name, desc, warnText = null) {
    const isOn = data.features[key];
    return row(name, desc, undefined,
      [toggle(isOn, false, `Turn ${name.toLowerCase()} ${isOn ? "off" : "on"}`,
        (v) => act(() => api("PUT", "/api/services/features", { [key]: v }), `${name} ${v ? "on" : "off"}`,
          () => { if (key === "practice_prices") emit("prices-changed"); }), `feature-${key}`)],
      warnText && isOn ? h("p", { class: "warn-text small", text: warnText }) : null);
  }

  function featureSection(data) {
    return h("section", { class: "panel-stack features" },
      h("h3", { text: "Features" }),
      FEATURES.map(([k, n, d]) => feature(data, k, n, d)));
  }

  function liveSection(data) {
    const isSuper = ctx.state.me?.is_super;
    return h("section", { class: "panel-stack live-switches" },
      h("h3", { text: "Live trading (real money)" }),
      h("p", { class: "muted small", text: "Which exchanges people may add trading keys for. Only super can switch one on (2FA needed); anyone here can switch one off. Live orders also need Ready for live trading to be green." }),
      data.live.map((x) => row(x.name, x.on ? "Live trading allowed" : "Off", undefined,
        [toggle(x.on, !x.on && !isSuper, !x.on && !isSuper ? "Only super can switch this on" : `Live trading on ${x.name} ${x.on ? "off" : "on"}`,
          (v) => act(() => api("PUT", "/api/services/live", { exchange: x.id, on: v }), `Live trading on ${x.name} ${v ? "on" : "off"}`), `live-${x.id}`)])));
  }

  function testSection(data) {
    const st = data.selftest;
    const last = st.last;
    let result = h("p", { class: "muted small", text: "Not run yet." });
    if (st.running) {
      result = h("p", { class: "small", role: "status", text: `Running since ${ago(st.started_at)}… (about a minute)` });
    } else if (last) {
      const summary = last.error ? `Couldn't finish: ${last.error}`
        : `${last.passed} passed, ${last.failed} failed (${last.checks} checks)`;
      result = h("div", { class: "panel-stack selftest-result" },
        h("p", {}, h("span", { class: `badge ${last.ok ? "ok" : "warn"}`, text: last.ok ? "passed" : "problems" }),
          ` ${summary} · ${ago(last.finished_at)} · started by ${last.started_by}`),
        last.failures?.length ? h("ul", { class: "small" }, last.failures.map((f) =>
          h("li", {}, h("strong", { text: `${f.suite}: ${f.check}` }), h("span", { class: "muted", text: ` ${f.message}` })))) : null,
        last.log?.length ? h("details", {}, h("summary", { class: "small", text: "Output" }),
          h("pre", { class: "log", text: last.log.join("\n") })) : null);
    }
    return h("section", { class: "panel-stack" },
      h("h3", { text: "Test tools" }),
      feature(data, "practice_prices", "Practice prices",
        "Made-up prices instead of CoinGecko, for trying things out. Price history pauses while it's on.",
        "On: every price in the app (and in embeds) is made up."),
      row("Self-test", "Runs every end-to-end check against a throwaway copy of the server. Never touches your data.", undefined,
        [button(st.running ? "Running…" : "Run self-test", { kind: "btn-sm btn-primary", disabled: st.running, data: { action: "run-selftest" },
          onclick: () => act(() => api("POST", "/api/services/selftest"), "Self-test started") })], result));
  }

  on("services-changed", load, ctx.signal);
  load();
}
