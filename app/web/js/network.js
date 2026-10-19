// Where the web UI listens and who may connect (super): Settings → System and the walkthrough.
// The server and the agent check every rule again. After a change the browser waits for the
// *restarted* server (its boot id changes), then confirms; without that confirmation the agent
// puts the old settings back by itself.

import { api } from "./api.js";
import { fill, h } from "./dom.js";
import { button, copyable, errorBox, input, loading } from "./ui.js";

const CGNAT = [100 * 2 ** 24 + 64 * 2 ** 16, 100 * 2 ** 24 + 127 * 2 ** 16 + 255 * 256 + 255];
const ipv4Int = (ip) => ip.split(".").reduce((n, part) => n * 256 + Number(part), 0);

/** The network to allow for one of this machine's addresses (a suggestion, never automatic). */
export function suggestNetwork(a) {
  if (a.kind === "this machine only" || a.address.includes(":")) return null;
  const n = ipv4Int(a.address);
  if (n >= CGNAT[0] && n <= CGNAT[1]) return "100.64.0.0/10"; // NetBird, Tailscale and co.
  return `${a.address.split(".").slice(0, 3).join(".")}.0/24`;
}

export async function networkEditor(area, ctx, { onSaved } = {}) {
  fill(area, loading());
  let data;
  try {
    data = await api("GET", "/api/server/network");
  } catch (err) {
    fill(area, errorBox(err));
    return;
  }
  const hosts = new Set(data.hosts);
  const nets = [...data.allowed_networks];
  const status = h("div", { class: "net-status", role: "status" });
  const original = JSON.stringify([[...hosts].sort(), [...nets].sort()]);
  const changed = () => JSON.stringify([[...hosts].sort(), [...nets].sort()]) !== original;

  function draw() {
    const fixed = new Set(["127.0.0.1", data.you.via].filter(Boolean));
    const rows = data.addresses.map((a) => {
      const box = h("input", { type: "checkbox", checked: hosts.has(a.address), disabled: fixed.has(a.address),
        dataset: { address: a.address }, "aria-label": `Listen on ${a.address}` });
      box.addEventListener("change", () => { box.checked ? hosts.add(a.address) : hosts.delete(a.address); draw(); });
      return h("label", { class: `net-row${a.kind === "public internet" ? " risky" : ""}` }, box,
        h("code", { text: a.address }), h("span", { class: "muted small", text: a.interface }),
        h("span", { class: `badge${a.kind === "public internet" ? " warn" : ""}`, text: a.kind }),
        a.address === data.you.via ? h("span", { class: "badge ok", text: "you're using this" }) : null);
    });
    const suggestions = [...new Set(data.addresses.filter((a) => hosts.has(a.address)).map(suggestNetwork))]
      .filter((n) => n && !nets.includes(n));
    const add = input({ placeholder: "e.g. 100.64.0.0/10 or 192.168.1.20", "aria-label": "Network to allow",
      spellcheck: "false", name: "allow_network" });
    const addIt = () => { const v = add.value.trim(); if (v && !nets.includes(v)) { nets.push(v); draw(); } };
    add.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addIt(); } });
    const lines = [`BOT_HOST=${[...hosts].join(",")}`, `BOT_ALLOWED_NETWORKS=${nets.join(",")}`,
      `BOT_ALLOW_REMOTE_BIND=${[...hosts].some((x) => !x.startsWith("127.") && x !== "::1")}`];
    fill(area,
      h("p", { class: "muted small" }, "You're connected to ", h("code", { text: `${data.you.via || "?"}:${data.port}` }),
        " from ", h("code", { text: data.you.client_ip || "?" }), "."),
      h("h4", { text: "Listen on" }),
      h("div", { class: "net-list" }, rows),
      [...hosts].some((x) => data.addresses.find((a) => a.address === x)?.kind === "public internet")
        ? h("div", { class: "notice warn", text: "A public internet address lets anyone online reach the sign-in page. Prefer a private network (NetBird, Tailscale, an SSH tunnel)." })
        : null,
      h("h4", { text: "Allow connections from" }),
      h("div", { class: "chips" }, nets.map((n) => h("span", { class: "chip" }, n,
        n === "127.0.0.0/8" ? null : h("button", { class: "chip-x", type: "button", "aria-label": `Remove ${n}`, text: "×",
          onclick: () => { nets.splice(nets.indexOf(n), 1); draw(); } })))),
      h("div", { class: "row" }, add, button("Add", { kind: "btn-sm", onclick: addIt }),
        suggestions.map((s) => button(`+ ${s}`, { kind: "btn-sm btn-ghost", data: { action: "suggest-network" },
          title: "The network of an address you listen on", onclick: () => { nets.push(s); draw(); } }))),
      h("p", { class: "muted small", text: "Never every interface (0.0.0.0): this app only listens on the addresses you tick. 127.0.0.1 always stays. If the server can't be reached after a change, the old settings come back by themselves within 2 minutes." }),
      data.agent
        ? h("div", { class: "actions" }, button("Apply", { kind: "btn-primary", disabled: !changed(), data: { action: "apply-network" }, onclick: apply }))
        : h("div", { class: "panel-stack" },
          h("div", { class: "notice info", text: "Changing these needs the agent (the root helper). Turn it on from the VM, or change the file by hand:" }),
          copyable(data.manual.agent),
          h("p", { class: "muted small" }, "Or in ", h("code", { text: data.manual.file }), ":"),
          copyable(lines.join("\n"), { rows: 3 }),
          h("p", { class: "muted small", text: "then:" }), copyable(data.manual.then)),
      status);
  }

  async function apply() {
    const before = data.boot;
    fill(status, h("p", { class: "small", text: "Saving…" }));
    let out;
    try {
      out = await api("PUT", "/api/server/network", { hosts: [...hosts], allowed_networks: nets });
    } catch (err) {
      fill(status, errorBox(err));
      return;
    }
    const deadline = Date.now() + (out.confirm_within - 5) * 1000;
    while (Date.now() < deadline) {
      const left = Math.round((deadline - Date.now()) / 1000);
      fill(status, h("p", { class: "small", text: `The server is restarting with the new settings… (${left} s)` }));
      await new Promise((r) => setTimeout(r, 1500));
      let now;
      try { now = await api("GET", "/api/server/network"); } catch { continue; } // still restarting
      if (now.boot === before) continue; // the old process, not yet restarted
      try {
        await api("POST", "/api/server/network/confirm");
      } catch (err) {
        fill(status, errorBox(err));
        return;
      }
      ctx.toast("Network settings saved", "The server answered on its new settings.");
      onSaved?.();
      return networkEditor(area, ctx, { onSaved });
    }
    fill(status, h("div", { class: "notice error", text: "The server didn't come back in time, so the agent is putting the old settings back. Reload this page in a minute." }));
  }

  draw();
}
