// Audit log: who changed what, when, from where. Read-only.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { when } from "../format.js";
import { button, errorBox, input, loading, table } from "../ui.js";

export function renderAudit(body, ctx) {
  const search = input({ placeholder: "Search action, user or detail", "aria-label": "Search the audit log",
    class: "input sm", spellcheck: "false" });
  const area = h("div", {}, loading());
  body.append(h("div", { class: "panel-stack" }, h("div", { class: "toolbar" }, search), area));
  let lastId = null;
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(true), 300); });

  async function load(reset = false) {
    if (reset) lastId = null;
    try {
      const q = new URLSearchParams({ limit: "100" });
      if (search.value.trim()) q.set("q", search.value.trim());
      if (lastId) q.set("before_id", lastId);
      const rows = await api("GET", `/api/audit?${q}`);
      const tbl = table([
        { label: "When", render: (r) => h("span", { class: "muted small nowrap", text: when(r.time) }) },
        { label: "Who", render: (r) => r.username || "—" },
        { label: "Action", render: (r) => h("code", { class: actionClass(r.action), text: r.action }) },
        { label: "Detail", render: (r) => r.detail },
        { label: "From", render: (r) => h("span", { class: "muted small", text: r.source_ip || "" }) },
      ], rows, { empty: search.value ? "Nothing matches." : "Nothing recorded yet." });
      if (!lastId) fill(area, tbl);
      else area.querySelector("tbody")?.append(...tbl.querySelectorAll("tbody tr"));
      area.querySelector(".more")?.remove();
      if (rows.length === 100) {
        lastId = rows.at(-1).id;
        area.append(button("Load more", { kind: "btn-ghost more", onclick: () => load() }));
      }
    } catch (err) {
      fill(area, errorBox(err));
    }
  }

  on("wallets-changed", () => load(true), ctx.signal);
  on("transfers-changed", () => load(true), ctx.signal);
  load(true);
}

const actionClass = (a) => (/fail|lockout|delete|reset/.test(a) ? "act warn" : "act");
