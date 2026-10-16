// Console (console.use): a fixed set of crypto-helper commands, run on the VM by the agent.
// Nothing typed here becomes part of a command: you pick one from the list.

import { api } from "../api.js";
import { fill, h } from "../dom.js";
import { button, copyButton, errorBox, loading, select } from "../ui.js";

export function renderConsole(body, ctx) {
  const output = h("div", { class: "console-output" });
  const list = h("div", { class: "console-commands" }, loading());
  const lines = select([[50, "50 lines"], [200, "200 lines"], [1000, "1000 lines"]], 200, { "aria-label": "Log lines" });
  body.append(h("div", { class: "panel-stack" },
    h("p", { class: "muted small", text: "Runs on the VM as the administrator. Each run is recorded in the audit log." }),
    list, output));

  async function run(cmd, btn) {
    for (const b of list.querySelectorAll("button")) b.disabled = true;
    fill(output, h("p", { class: "small", role: "status", text: `Running ${cmd.id}…` }));
    try {
      const r = await api("POST", "/api/console/run", { command: cmd.id, ...(cmd.id === "logs" ? { lines: Number(lines.value) } : {}) });
      const pre = h("pre", { class: "log console-log", text: r.output || "(no output)" });
      fill(output, h("div", { class: "row" },
        h("strong", { text: `crypto-helper ${cmd.id}` }),
        h("span", { class: `badge ${r.exit_code === 0 ? "ok" : "warn"}`, text: r.exit_code === 0 ? "ok" : `exit ${r.exit_code}` }),
        h("span", { class: "spacer" }), copyButton(r.output, pre, "Copy")), pre);
    } catch (err) {
      fill(output, errorBox(err));
    } finally {
      for (const b of list.querySelectorAll("button")) b.disabled = false;
      btn?.focus();
    }
  }

  api("GET", "/api/console/commands").then((cmds) => fill(list, cmds.map((c) => {
    const btn = button(c.id, { kind: "btn-sm", title: c.description, data: { command: c.id }, onclick: () => run(c, btn) });
    return h("div", { class: "console-command" }, btn, h("span", { class: "muted small", text: c.description }),
      c.id === "logs" ? lines : null);
  }))).catch((err) => fill(list, errorBox(err)));
  void ctx;
}
