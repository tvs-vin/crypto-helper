// Getting started: what's set up and what isn't, for your account (and, for super, the
// server). It ticks itself from what's really there; each item opens the walkthrough at it.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { button, errorBox, loading } from "../ui.js";

export function renderStart(body, ctx) {
  const area = h("div", { class: "panel-stack start" }, loading());
  body.append(area);

  async function load() {
    let s;
    try {
      s = await api("GET", "/api/onboarding");
    } catch (err) {
      fill(area, errorBox(err));
      return;
    }
    const pct = s.total ? Math.round((s.done / s.total) * 100) : 100;
    const bar = h("div", { class: "progress", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(s.total),
      "aria-valuenow": String(s.done), "aria-label": "Set up so far" }, h("span"));
    bar.firstChild.style.width = `${pct}%`;
    const row = (step) => h("li", { class: `start-item${step.done ? " done" : ""}`, dataset: { step: step.id } },
      h("span", { class: "tick", "aria-hidden": "true", text: step.done ? "✓" : "" }),
      h("span", { class: "start-title" }, h("span", { text: step.title }),
        step.required && !step.done ? h("span", { class: "badge warn", text: "required" }) : null),
      button(step.done ? "Look again" : "Do it", { kind: `btn-sm ${step.done ? "btn-ghost" : ""}`, data: { action: "start-step" },
        onclick: () => ctx.walkthrough?.({ at: step.id }) }));
    fill(area,
      h("div", { class: "start-head" },
        h("div", {}, h("h3", { text: s.done === s.total ? "All set" : `${s.done} of ${s.total} done` }), bar),
        button("Walk me through it", { kind: "btn-primary btn-sm", data: { action: "start-walkthrough" },
          onclick: () => ctx.walkthrough?.({}) })),
      s.server ? h("section", {}, h("h4", { text: "Your server" }), h("ol", { class: "start-list" }, s.server.map(row))) : null,
      h("section", {}, h("h4", { text: s.server ? "Getting to know it" : "Your account" }), h("ol", { class: "start-list" }, s.account.map(row))));
  }

  on("onboarding-changed", load, ctx.signal);
  on("wallets-changed", load, ctx.signal);
  load();
}
