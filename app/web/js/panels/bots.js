// Bots: the Backtester's plans run from today on, on paper or (live bots) with real orders. Each bot
// decides once a day on the day's close, its orders fill at the live price with fees and
// slippage within its limits, and a buy-and-hold twin gets the same money for comparison. The
// kill switch at the top stops every bot at once until someone re-arms it.

import { api } from "../api.js";
import { on } from "../bus.js";
import { lineChart } from "../chart.js";
import { fill, h } from "../dom.js";
import { ago, money, when } from "../format.js";
import { planDefaults, planForm, planParams } from "../plan-form.js";
import { button, can, emptyState, errorBox, field, form, input, loading, segmented, select, sheet, table } from "../ui.js";

const PAPER = "Made-up money at real, live prices: nothing is ever sent to an exchange.";

export function renderBots(body, ctx) {
  const kill = h("div", { class: "panel-stack" });
  const ready = h("div", {});
  const main = h("div", { class: "panel-stack" }, loading());
  body.append(h("div", { class: "panel-stack" }, kill, ready, main));
  let data = null;
  let openId = Number(ctx.windowState?.bot) || null; // the bot shown in detail, remembered

  async function load() {
    try {
      const [d, r] = await Promise.all([api("GET", "/api/bots"), api("GET", "/api/bots/readiness")]);
      data = d;
      drawKill(data.kill);
      drawReady(r);
      if (openId && data.bots.some((b) => b.id === openId)) await showBot(openId);
      else { openId = null; drawList(); }
    } catch (err) {
      fill(main, errorBox(err));
    }
  }

  function drawKill(k) {
    if (k.tripped && k.drill) {
      const d = k.drill;
      const good = d.all_stopped && d.check_refused;
      fill(kill, h("div", { class: `notice ${good ? "warn" : "error"} kill-banner`, role: "alert", dataset: { kill: "drill" } },
        h("div", {}, h("strong", { text: "Kill switch drill: every bot is stopped." }),
          h("p", { class: "small", text: `${d.bots_stopped} bot${d.bots_stopped === 1 ? "" : "s"} stopped, ${d.orders_cancelled} waiting order${d.orders_cancelled === 1 ? "" : "s"} cancelled, and the bot check ${d.check_refused ? "refused to trade" : "still ran (the drill failed)"}. Re-arm to complete the drill; bots stopped by a drill keep their clean days.` })),
        can(ctx, "bots.run") ? button("Re-arm…", { kind: "btn-sm", data: { action: "rearm" }, onclick: rearm }) : null));
      return;
    }
    if (k.tripped) {
      fill(kill, h("div", { class: "notice error kill-banner", role: "alert", dataset: { kill: "tripped" } },
        h("div", {}, h("strong", { text: "Kill switch tripped: every bot is stopped." }),
          h("p", { class: "small", text: `Why: ${k.reason} (${k.by}, ${ago(k.at)}). Waiting orders were cancelled. Bots stay paused until it's re-armed, then each is started again by hand.` })),
        can(ctx, "bots.run") ? button("Re-arm…", { kind: "btn-sm", data: { action: "rearm" }, onclick: rearm }) : null));
      return;
    }
    const lastTrip = k.last ? h("p", { class: "muted small", text: `Last tripped ${when(k.last.at)}: ${k.last.reason}. Re-armed by ${k.rearmed_by} ${ago(k.rearmed_at)}.` }) : null;
    fill(kill, h("div", { class: "notice kill-banner", dataset: { kill: "armed" } },
      h("div", {}, h("strong", { text: "Kill switch: armed" }),
        h("p", { class: "small muted", text: "Stops every bot at once and cancels their waiting orders. It also trips by itself if a bot loses its daily limit or prices stay stale for 15 minutes." }),
        lastTrip),
      can(ctx, "bots.stop") ? button("Stop all bots", { kind: "btn-sm btn-danger", data: { action: "kill" }, onclick: stopAll }) : null));
  }

  function drawReady(r) {
    const row = (ok, title, detail, action) => h("li", { class: `ready-row ${ok ? "ok" : "todo"}` },
      h("span", { class: "ready-mark", "aria-hidden": "true", text: ok ? "✓" : "○" }),
      h("div", { class: "ready-text" }, h("strong", { text: title }), detail), action);
    const best = [...r.bots].sort((a, b) => b.clean_days - a.clean_days)[0];
    const botsDetail = r.bots.length ? h("div", { class: "panel-stack" }, r.bots.map((b) => h("div", { class: "ready-bot", dataset: { bot: b.id } },
      h("div", { class: "row" }, h("span", { text: b.name }), h("span", { class: "spacer" }),
        h("span", { class: "muted small num", text: `${Math.min(b.clean_days, r.clean_days).toFixed(1)} of ${r.clean_days} ${r.test_clock ? "test days (minutes)" : "days"}` })),
      h("progress", { max: String(r.clean_days), value: String(Math.min(b.clean_days, r.clean_days)), "aria-label": `${b.name}: clean days` }),
      h("p", { class: "muted small", text: [
        ...b.checks.filter((c) => !c.ok && c.key !== "clean")
          .map((c) => (c.key === "running" ? `${c.detail[0].toUpperCase()}${c.detail.slice(1)}.` : `${c.label}: ${c.detail}.`)),
        b.ready_on ? `Ready on ${b.ready_on} if nothing goes wrong.` : "",
        b.last_reset ? `Started counting again ${ago(b.last_reset.at)} (${b.last_reset.why}).` : "",
      ].filter(Boolean).join(" ") }))))
      : h("p", { class: "muted small", text: "No bots yet: start one below." });
    const d = r.drill;
    const lastDrill = d.in_progress ? "A drill is under way: re-arm the kill switch to complete it." : d.last ? `Last drill ${when(d.last.at)} by ${d.last.by}: ${d.last.bots_stopped} stopped, ${d.last.orders_cancelled} orders cancelled, check ${d.last.check_refused ? "refused" : "RAN"}${d.last.rearmed_at ? `, re-armed by ${d.last.rearmed_by}` : ", not re-armed yet"}.` : "No drill yet.";
    const c = r.selfcheck;
    const failed = c.last ? c.last.results.filter((x) => !x.ok) : [];
    const checkText = !c.last ? "Not run yet." : c.outdated ? `Passed ${when(c.last.at)}, but the risk code has changed since: run it again.`
      : c.last.passed ? `Passed ${when(c.last.at)}: ${c.last.results.map((x) => x.name).join(", ")}.`
        : `FAILED ${when(c.last.at)}: ${failed.map((x) => `${x.name} (${x.problem})`).join("; ")}.`;
    const open = ctx.windowState?.ready === true;
    const box = h("details", { class: "readiness", open, dataset: { ready: String(r.ready) } },
      h("summary", {}, h("span", { class: `badge ${r.ready ? "ok" : "warn"}`, text: r.ready ? (r.test_clock ? "ready (test)" : "ready") : "not ready" }),
        h("span", { text: " Ready for live trading?" }),
        h("span", { class: "muted small", text: r.ready ? " All three checks are green." : ` ${[best?.ok, d.ok, c.ok].filter(Boolean).length} of 3 checks green.` })),
      r.test_clock ? h("p", { class: "notice warn", dataset: { testClock: "on" }, text: "TEST CLOCK: a day here is a minute (development and test servers only). Results on this clock never unlock live trading." }) : null,
      h("p", { class: "muted small", text: r.ready && !r.test_clock
        ? "All green: switching live trading on (phase 4) is allowed once it's built."
        : "Project rule 10: live trading (phase 4) can only be switched on when all three are green, on the real clock." }),
      h("ul", { class: "ready-list" },
        row(Boolean(best?.ok), `A bot ran cleanly on paper for ${r.clean_days} days`, botsDetail, null),
        row(d.ok, `The kill switch was tested in the last ${d.days} ${r.test_clock ? "test days (minutes)" : "days"}`, h("p", { class: "muted small", text: lastDrill }),
          can(ctx, "bots.stop") && !data.kill.tripped ? button("Run a drill…", { kind: "btn-sm", data: { action: "drill" }, onclick: runDrill }) : null),
        row(c.ok, "The loss limits work in this version (self-check)", h("p", { class: `small ${failed.length ? "" : "muted"}`, text: checkText }),
          can(ctx, "bots.run") ? button("Run the self-check", { kind: "btn-sm", data: { action: "selfcheck" }, onclick: runCheck }) : null)));
    box.addEventListener("toggle", () => ctx.saveWindowState?.({ ready: box.open }));
    fill(ready, box);
  }

  function runDrill() {
    sheet(body, "Kill switch drill", (close) => {
      const reason = input({ name: "reason", maxlength: "200", placeholder: "e.g. monthly drill" });
      return form([
        h("p", { text: "A drill trips the kill switch for real: every bot is paused and every waiting order is cancelled. The app then checks that nothing is still running and that the bot check refuses to trade." }),
        h("p", { class: "muted small", text: "Re-arm afterwards to complete it, then start the bots again. Bots stopped by a drill keep their clean days." }),
        field("Note (for the audit log)", reason),
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Start the drill", { kind: "btn-danger", type: "submit", data: { action: "confirm-drill" } })),
      ], async () => {
        const r = await api("POST", "/api/bots/drill", { reason: reason.value.trim() });
        close();
        const d = r.kill.drill;
        ctx.toast(d.all_stopped && d.check_refused ? "Drill: everything stopped" : "Drill FAILED", "Re-arm to complete it.", d.all_stopped && d.check_refused ? "" : "error");
        load();
      });
    });
  }

  async function runCheck() {
    try {
      const r = await api("POST", "/api/bots/selfcheck");
      ctx.toast(r.passed ? "Self-check passed" : "Self-check FAILED", `${r.results.filter((x) => x.ok).length} of ${r.results.length} checks`, r.passed ? "" : "error");
      ctx.saveWindowState?.({ ready: true });
      load();
    } catch (err) {
      ctx.toast("Couldn't run the self-check", err.message, "error");
    }
  }

  function stopAll() {
    sheet(body, "Stop every bot", (close) => {
      const reason = input({ name: "reason", maxlength: "200", placeholder: "e.g. testing the kill switch" });
      return form([
        h("p", { text: "Every running bot is paused and every waiting order is cancelled, now. Nothing starts again until someone re-arms the switch and starts each bot." }),
        field("Why (for the audit log)", reason),
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Stop every bot", { kind: "btn-danger", type: "submit", data: { action: "confirm-kill" } })),
      ], async () => {
        const r = await api("POST", "/api/bots/kill", { reason: reason.value.trim() });
        close();
        ctx.toast("Kill switch tripped", "Every bot is stopped.", "warn");
        drawKill(r.kill);
        load();
      });
    });
  }

  function rearm() {
    sheet(body, "Re-arm the kill switch", (close) => {
      const typed = input({ name: "confirm", autocomplete: "off", placeholder: "REARM" });
      const go = button("Re-arm", { kind: "btn-primary", type: "submit", disabled: true, data: { action: "confirm-rearm" } });
      typed.addEventListener("input", () => { go.disabled = typed.value !== "REARM"; });
      return form([
        h("p", { text: `It tripped because: ${data.kill.reason}. Make sure that's sorted first.` }),
        h("p", { class: "muted small", text: "Re-arming doesn't start any bot: you start each one again yourself." }),
        field("Type REARM to confirm", typed),
        h("div", { class: "actions" }, button("Cancel", { onclick: close }), go),
      ], async () => {
        await api("POST", "/api/bots/rearm", { confirm: typed.value });
        close();
        ctx.toast("Kill switch re-armed", "Start bots again one by one.");
        load();
      });
    });
  }

  function drawList() {
    if (ctx.windowState?.bot) ctx.saveWindowState?.({ bot: 0 }); // window state takes no null
    const add = can(ctx, "bots.run")
      ? button("New bot", { kind: "btn-primary btn-sm", data: { action: "new-bot" }, disabled: data.bots.length >= data.max, onclick: newBot })
      : null;
    if (!data.bots.length) {
      fill(main, emptyState("No bots yet",
        `A bot runs one of the Backtester's plans from today on, with paper money, next to a buy-and-hold twin. ${PAPER}`, add));
      return;
    }
    fill(main,
      h("div", { class: "row" }, h("h3", { text: `Bots (${data.bots.length} of ${data.max})` }), h("span", { class: "spacer" }), add),
      h("p", { class: "muted small", text: data.bots.some((b) => b.mode === "live")
        ? "Paper bots use made-up money at real prices. LIVE bots trade real money with your trading keys, within your cap."
        : PAPER }),
      h("div", { class: "bot-cards" }, data.bots.map(card)));
  }

  function card(b) {
    const s = b.summary;
    const cur = b.currency;
    return h("div", { class: `bot-card${b.mode === "live" ? " live" : ""}`, dataset: { bot: b.id, mode: b.mode } },
      h("div", { class: "row" }, h("h4", { text: b.name }), b.mode === "live" ? h("span", { class: "badge live-badge", text: "LIVE" }) : null,
        h("span", { class: "spacer" }), statusBadge(b)),
      h("p", { class: "muted small", text: b.text }),
      b.live ? h("p", { class: "small", text: `Real money with ${b.live.key || "no key (deleted)"} · ${b.live.order_kind} orders${b.live.order_kind === "limit" ? `, ${b.live.protection_pct} % protection` : ""}${b.live.sending ? ` · ${b.live.sending} on its way to the exchange` : ""}` }) : null,
      s.value === undefined
        ? h("p", { class: "muted small", text: `${money(s.put_in, cur)} put in · live prices unavailable just now` })
        : h("div", { class: "bot-figures" },
          h("p", { class: "big num", text: money(s.value, cur) }),
          h("p", { class: `num ${Number(s.profit) >= 0 ? "up" : "down"}`, text: `${Number(s.profit) >= 0 ? "+" : ""}${money(s.profit, cur)} (${s.return_pct ?? "—"} %)` }),
          h("p", { class: "muted small num", text: `Buy and hold: ${money(s.benchmark, cur)} (${s.benchmark_return_pct ?? "—"} %) · ${money(s.put_in, cur)} put in` })),
      b.status_reason ? h("p", { class: "small", text: b.status_reason }) : null,
      b.pending ? h("p", { class: "muted small", text: `${b.pending} order${b.pending > 1 ? "s" : ""} waiting for the next check` }) : null,
      h("div", { class: "actions" },
        button("Open", { kind: "btn-sm", data: { action: "open-bot" }, onclick: () => showBot(b.id) }),
        runButton(b)));
  }

  function statusBadge(b) {
    return h("span", { class: `badge ${b.status === "running" ? "ok" : "warn"}`, text: b.status });
  }

  function runButton(b) {
    if (!can(ctx, "bots.run")) return null;
    if (b.status === "running") {
      return button("Pause", { kind: "btn-sm btn-ghost", data: { action: "pause-bot" }, onclick: () => act(b, "pause") });
    }
    return button("Start", { kind: "btn-sm btn-ghost", data: { action: "start-bot" }, disabled: data.kill.tripped,
      title: data.kill.tripped ? "Re-arm the kill switch first" : "", onclick: () => act(b, "start") });
  }

  async function act(b, what) {
    try {
      await api("POST", `/api/bots/${b.id}/${what}`);
      load();
    } catch (err) {
      ctx.toast(`Couldn't ${what} ${b.name}`, err.message, "error");
    }
  }

  async function showBot(id) {
    openId = id;
    if (ctx.windowState?.bot !== id) ctx.saveWindowState?.({ bot: id });
    let b;
    try {
      b = await api("GET", `/api/bots/${id}`);
    } catch (err) {
      fill(main, errorBox(err));
      return;
    }
    const s = b.summary;
    const cur = b.currency;
    const fact = (label, value) => [h("dt", { text: label }), h("dd", { class: "num", text: value })];
    const lim = b.limits || {};
    const limits = [
      lim.max_order ? `orders of at most ${money(lim.max_order, cur)}` : null,
      lim.max_daily_spend ? `at most ${money(lim.max_daily_spend, cur)} spent a day` : null,
      lim.position_loss_pct ? `pauses if a coin falls ${lim.position_loss_pct} % below what it paid` : null,
      lim.daily_loss_pct ? `trips the kill switch if it loses ${lim.daily_loss_pct} % in a day` : null,
    ].filter(Boolean);
    const width = Math.max(320, main.clientWidth || 700);
    const better = s.value !== undefined && Number(s.value) >= Number(s.benchmark);
    const holdings = Object.entries(s.holdings);
    fill(main,
      h("div", { class: "row" }, button("← All bots", { kind: "btn-sm btn-ghost", data: { action: "all-bots" }, onclick: () => { openId = null; load(); } }),
        h("span", { class: "spacer" }), runButton(b)),
      h("div", { class: "row" }, h("h3", { text: b.name }), statusBadge(b)),
      h("p", { class: "muted small", text: `${b.text}. Started ${when(b.created_at)}${b.owner ? ` by ${b.owner}` : ""}.${b.mode === "live" ? "" : ` ${PAPER}`}` }),
      b.live ? h("div", { class: "notice warn", dataset: { role: "live-notice" } }, h("strong", { text: "LIVE: real money." }),
        h("p", { class: "small", text: `Orders go to the exchange with ${b.live.key || "no key (deleted)"}: immediate-or-cancel ${b.live.order_kind} orders${b.live.order_kind === "limit" ? ` at most ${b.live.protection_pct} % worse than the price` : ""}. Fills and fees are the exchange's own. Buy and hold stays on paper, for comparison.` })) : null,
      b.status_reason ? h("p", { class: "notice warn", text: b.status_reason }) : null,
      s.value === undefined ? h("p", { class: "notice", text: "Live prices are unavailable just now: values show again when they're back." }) : h("div", { class: "bt-cards" },
        h("div", { class: `bt-card${better ? " better" : ""}` }, h("h4", { text: "This bot" }),
          h("p", { class: "big num", text: money(s.value, cur) }),
          h("p", { class: `num ${Number(s.profit) >= 0 ? "up" : "down"}`, text: `${Number(s.profit) >= 0 ? "+" : ""}${money(s.profit, cur)} (${s.return_pct ?? "—"} %)` }),
          h("dl", { class: "bt-facts" }, fact("Put in", money(s.put_in, cur)), fact("Cash", money(s.cash, cur)),
            fact("Gains taken", money(s.realized, cur)), fact("Gains not taken", money(s.unrealized, cur)),
            fact("Fees + slippage", `${money(s.fees, cur)} + ${money(s.slippage, cur)}`))),
        h("div", { class: `bt-card${!better ? " better" : ""}` }, h("h4", { text: "Buy and hold" }),
          h("p", { class: "big num", text: money(s.benchmark, cur) }),
          h("p", { class: `num ${s.benchmark_return_pct >= 0 ? "up" : "down"}`, text: `${s.benchmark_return_pct ?? "—"} %` }),
          h("p", { class: "muted small", text: "The same money on the same days, straight into the same coins, never sold." }))),
      holdings.length ? h("p", { class: "small", text: `Holds ${holdings.map(([sym, u]) => `${u} ${sym}`).join(", ")}.` }) : null,
      h("p", { class: "muted small", text: limits.length ? `Limits: ${limits.join("; ")}.` : "No limits." }),
      b.points.length >= 2
        ? [lineChart(b.points, { fiat: cur, width, height: 200, key: "value", also: [{ key: "benchmark", label: "Hold" }], main: "Bot",
          label: "Value over time: this bot (solid) and buy and hold (dashed)" }),
        h("p", { class: "muted small", text: "Solid: this bot. Dashed: buy and hold. A point every hour while it runs." })]
        : h("p", { class: "muted small", text: "The chart fills in as the bot runs (a point every hour)." }),
      h("h4", { text: "Orders" }),
      table([
        { label: "Decided on", render: (o) => o.decided_for || "" },
        { label: "", render: (o) => h("span", { class: `badge ${o.side === "buy" ? "ok" : "warn"}`, text: o.side }) },
        { label: "Coin", render: (o) => o.symbol },
        { label: "Status", render: (o) => h("span", { class: "small", text: o.status === "filled" ? `filled ${ago(o.filled_at)}` : o.status }) },
        { label: "Units", align: "right", cls: "num", render: (o) => o.units || "" },
        { label: "Price", align: "right", cls: "num", render: (o) => (o.price ? money(o.price, cur) : "") },
        { label: "Value", align: "right", cls: "num", render: (o) => (o.value ? money(o.value, cur) : o.side === "buy" ? `${money(o.requested, cur)} asked` : "") },
        { label: "Fee", align: "right", cls: "num", render: (o) => (o.fee ? money(o.fee, cur) : "") },
        { label: "Note", render: (o) => h("span", { class: "muted small", text: o.note || "" }) },
      ], b.orders, { empty: "No orders yet", rowKey: (o) => String(o.id) }),
      h("div", { class: "actions" },
        button("Download orders (CSV)", { kind: "btn-sm", data: { action: "bot-csv" }, onclick: () => { window.location.href = `/api/bots/${b.id}/orders.csv`; } }),
        can(ctx, "bots.run") ? button("Delete bot…", { kind: "btn-sm btn-ghost", data: { action: "delete-bot" }, onclick: () => remove(b) }) : null));
  }

  function remove(b) {
    sheet(body, `Delete ${b.name}`, (close) => form([
      h("p", { text: "Its orders and chart go too. Download the orders first if you want to keep them." }),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button("Delete", { kind: "btn-danger", type: "submit", data: { action: "confirm-delete" } })),
    ], async () => {
      await api("DELETE", `/api/bots/${b.id}`);
      close();
      openId = null;
      load();
    }));
  }

  async function newBot() {
    let meta;
    try {
      meta = await api("GET", "/api/bots/meta");
    } catch (err) {
      ctx.toast("Couldn't open the form", err.message, "error");
      return;
    }
    const state = planDefaults();
    // Live bots (real money): only for people who may trade live, with a key to trade with.
    let trading = null;
    if (can(ctx, "live.trade")) {
      try { trading = await api("GET", "/api/trading"); } catch { trading = null; }
    }
    const keys = (trading?.keys || []).filter((k) => k.exchange_on);
    sheet(body, "New bot", (close) => {
      const name = input({ name: "bot_name", maxlength: "80", placeholder: "e.g. Weekly BTC" });
      const limits = limitsFields();
      const liveArea = h("div", { class: "panel-stack" });
      let mode = "paper";
      const keySel = select(keys.map((k) => [String(k.id), `${k.label} (${k.exchange})`]), keys[0] ? String(keys[0].id) : "", { name: "trading_key", "aria-label": "Trading key" });
      const kindSel = select([["limit", "Limit, with price protection"], ["market", "Market"]], "limit", { name: "order_kind", "aria-label": "Orders" });
      const protection = input({ name: "protection_pct", value: "1", inputmode: "decimal", class: "input sm", "aria-label": "Protection %" });
      const drawLive = () => fill(liveArea, mode === "live" ? h("div", { class: "notice warn live-choice" },
        h("strong", { text: "Real money." }),
        h("p", { class: "small", text: `Orders go to the exchange with your trading key, within your cap (${trading.caps.cap ? money(trading.caps.cap, "usd") : "$150"}) and this bot's limits. ${trading.live_allowed ? "" : "Ready for live trading isn't green yet: it can't start until it is."}` }),
        h("div", { class: "grid-2" }, field("Trading key", keySel), field("Orders", kindSel)),
        field("Price protection (%)", protection, "A limit order is at most this much worse than the price the bot saw (0.1 to 5 %).")) : null);
      const modeCtl = trading ? segmented([["paper", "Paper"], ["live", "Live (real money)"]], "paper", (v) => { mode = v; drawLive(); }, "Mode") : null;
      return form([
        h("p", { class: "muted small", text: "The bot makes its first decision on yesterday's close, and fills it within a minute. Paper bots use made-up money at real prices." }),
        field("Name", name),
        modeCtl ? field("Mode", modeCtl, keys.length ? "Live: needs Ready for live trading to be green, and US dollars." : "Live needs a trading key for an exchange that's switched on (Live trading).") : null,
        liveArea,
        planForm(meta, state, { dates: false }),
        limits.el,
        h("div", { class: "actions" }, button("Cancel", { onclick: close }),
          button("Start bot", { kind: "btn-primary", type: "submit", data: { action: "create-bot" } })),
      ], async () => {
        const live = mode === "live" ? { mode: "live", trading_key_id: Number(keySel.value) || null, order_kind: kindSel.value, protection_pct: protection.value.trim() } : {};
        const b = await api("POST", "/api/bots", { name: name.value.trim() || "Paper bot", params: planParams(state, { dates: false }), limits: limits.collect(), ...live });
        close();
        ctx.toast("Bot started", b.text);
        showBot(b.id);
      });
    });
  }

  on("bots-changed", load, ctx.signal);
  on("prices-changed", () => { if (!openId) load(); }, ctx.signal);
  load();
}

/** The risk limits, filled in with their defaults. */
function limitsFields() {
  const v = { max_order: input({ name: "max_order", inputmode: "decimal", class: "input sm", placeholder: "no limit" }),
    max_daily_spend: input({ name: "max_daily_spend", inputmode: "decimal", class: "input sm", placeholder: "no limit" }),
    position_loss_pct: input({ name: "position_loss_pct", inputmode: "decimal", class: "input sm", value: "30" }),
    daily_loss_pct: input({ name: "daily_loss_pct", inputmode: "decimal", class: "input sm", value: "15" }) };
  const el = h("fieldset", { class: "panel-stack bot-limits" }, h("legend", { text: "Limits" }),
    h("div", { class: "grid-2" },
      field("Largest order (in the plan's currency)", v.max_order, "Bigger buys are cut down to this."),
      field("Most spent in a day", v.max_daily_spend, "Buys past it are cut, or wait for tomorrow's decision.")),
    h("div", { class: "grid-2" },
      field("Pause if a coin is this % below what it paid", v.position_loss_pct, "The bot pauses and tells you."),
      field("Kill switch if the bot loses this % in a day", v.daily_loss_pct, "Stops every bot.")));
  return { el, collect: () => Object.fromEntries(Object.entries(v).map(([k, i]) => [k, i.value.trim() || null])) };
}

/** From the Backtester: run a tested plan on paper from today. */
export function paperSheet(body, ctx, params, text) {
  sheet(body, "Run it on paper", (close) => {
    const name = input({ name: "bot_name", maxlength: "80", value: (text || "Paper bot").slice(0, 80) });
    const limits = limitsFields();
    const plan = Object.fromEntries(Object.entries(params).filter(([k]) => k !== "start" && k !== "end"));
    return form([
      h("p", { text: `${text}, from today on, next to a buy-and-hold twin.` }),
      h("p", { class: "muted small", text: PAPER }),
      field("Name", name),
      limits.el,
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button("Start bot", { kind: "btn-primary", type: "submit", data: { action: "create-bot" } })),
    ], async () => {
      const b = await api("POST", "/api/bots", { name: name.value.trim() || "Paper bot", params: plan, limits: limits.collect() });
      close();
      ctx.toast("Bot started", `${b.name}: see Bots.`);
      ctx.wm.open("bots");
    });
  });
}
