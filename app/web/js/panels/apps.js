// App manager (apps.manage): which apps each account can use, and switches that turn an app
// off for everyone except super. The server enforces every rule (never super or yourself,
// only accounts whose permissions you hold, only apps you can use); this window shows them.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h, icon } from "../dom.js";
import { PANELS } from "../panels.js";
import { button, chips, errorBox, loading, toggle } from "../ui.js";

export function renderApps(body, ctx) {
  const area = h("div", { class: "panel-stack" }, loading());
  body.append(h("div", { class: "panel-stack" },
    h("p", { class: "muted small", text: "An account can open an app when it's switched on for them, isn't switched off for everyone, and they hold the permissions it needs. Super can always use every app." }),
    area));

  async function load() {
    try {
      const data = await api("GET", "/api/apps");
      fill(area, accountsGrid(data), appsTable(data));
    } catch (err) {
      fill(area, errorBox(err));
    }
  }

  const act = async (fn, msg) => {
    try {
      await fn();
      if (msg) ctx.toast(msg);
      emit("apps-changed");
    } catch (err) {
      ctx.toast("Couldn't change that", err.message, "error");
      load();
    }
  };

  function appsTable(data) {
    const using = (id) => data.accounts.filter((a) => a.is_active && a.status[id] === null).length;
    return h("section", { class: "panel-stack" },
      h("h3", { text: "Switch an app off for everyone" }),
      h("div", { class: "table-wrap" }, h("table", { class: "table apps-table" },
        h("thead", {}, h("tr", {}, ["App", "Needs", "Accounts", "For everyone"].map((t, i) =>
          h("th", { scope: "col", class: i === 2 ? "r" : "", text: t })))),
        h("tbody", {}, data.apps.map((a) => h("tr", { dataset: { app: a.id } },
          h("td", {}, h("span", { class: "app-name" }, icon(PANELS[a.id]?.icon || "apps"), h("strong", { text: a.name })),
            h("p", { class: "muted small", text: a.description })),
          h("td", {}, chips(a.needs)),
          h("td", { class: "r", text: String(using(a.id)) }),
          h("td", {}, toggle(a.enabled, !a.can_grant,
            a.can_grant ? `Turn ${a.name} ${a.enabled ? "off" : "on"} for everyone (super keeps it)` : "You can only switch apps you can use yourself",
            (on_) => act(() => api("PUT", `/api/apps/${a.id}/enabled`, { enabled: on_ }),
              `${a.name} turned ${on_ ? "on" : "off"} for everyone`), `switch-${a.id}`))))))),
      h("p", { class: "muted small", text: `Always available, can't be switched off: ${data.core.map((c) => PANELS[c]?.title || c).join(", ")}.` }));
  }

  function accountsGrid(data) {
    const grantable = new Set(data.apps.filter((a) => a.can_grant).map((a) => a.id));
    const ids = data.apps.map((a) => a.id);
    const row = (acc) => {
      const chosen = new Set(acc.chosen === "all" ? ids : acc.chosen);
      const cells = data.apps.map((a) => {
        const reason = acc.status[a.id];
        const box = h("input", { type: "checkbox", checked: chosen.has(a.id), dataset: { app: a.id },
          disabled: Boolean(acc.locked) || !grantable.has(a.id),
          "aria-label": `${a.name} for ${acc.username}`,
          title: acc.locked || (!grantable.has(a.id) ? "You can only switch apps you can use yourself" : "") });
        box.addEventListener("change", () => {
          const next = new Set(chosen);
          if (box.checked) next.add(a.id); else next.delete(a.id);
          act(() => api("PUT", `/api/apps/accounts/${acc.id}`, { apps: ids.filter((i) => next.has(i)) }),
            `${a.name} ${box.checked ? "on" : "off"} for ${acc.username}`).then(load);
        });
        // On, but still unusable (missing permission or off for everyone): say why.
        const note = chosen.has(a.id) && reason && !acc.is_super
          ? h("span", { class: "cell-note", title: reason, "aria-label": reason }, icon("shield")) : null;
        return h("td", { class: "c" }, h("label", { class: "grid-check" }, box, note));
      });
      return h("tr", { dataset: { account: acc.username }, class: acc.is_active ? "" : "muted" },
        h("td", {}, h("strong", { text: acc.username }),
          acc.is_super ? h("span", { class: "badge", text: "super" }) : null,
          acc.id === ctx.state.me.id ? h("span", { class: "badge ok", text: "you" }) : null,
          acc.is_active ? null : h("span", { class: "badge warn", text: "deactivated" })),
        ...cells,
        h("td", {}, acc.chosen === "all"
          ? h("span", { class: "muted small", title: "Every app, including ones added later", text: "all apps" })
          : acc.locked ? null : button("Allow all", { kind: "btn-sm btn-ghost", data: { action: "allow-all", account: acc.username },
            title: "Every app, including ones added later",
            onclick: () => act(() => api("PUT", `/api/apps/accounts/${acc.id}`, { apps: "all" }), `All apps for ${acc.username}`).then(load) })));
    };
    return h("section", { class: "panel-stack" },
      h("h3", { text: "Accounts" }),
      h("div", { class: "table-wrap" }, h("table", { class: "table apps-grid" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col", text: "Account" }),
          data.apps.map((a) => h("th", { scope: "col", class: "c", title: a.name },
            h("span", { class: "app-head" }, icon(PANELS[a.id]?.icon || "apps"), h("span", { text: a.name })))),
          h("th", { scope: "col", text: "" }))),
        h("tbody", {}, data.accounts.map(row)))),
      h("p", { class: "muted small" }, icon("shield"), " Switched on but can't be used yet: hover to see why (usually a permission, given in the Users window)."));
  }

  on("apps-changed", () => { load(); ctx.refreshMe?.(); }, ctx.signal);
  on("users-changed", load, ctx.signal);
  load();
}
