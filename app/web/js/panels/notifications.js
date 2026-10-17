// Notifications: yours, newest first (they also arrive live as toasts), and, with
// notifications.send, a form to send one to a person or to everyone.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h, icon } from "../dom.js";
import { ago } from "../format.js";
import { PANELS } from "../panels.js";
import { button, can, emptyState, errorBox, field, form, input, loading, segmented, select } from "../ui.js";

const LEVEL_ICON = { info: "list", warning: "shield", critical: "shield" };
const CATEGORY = { security: "Security", system: "System", prices: "Prices", messages: "Message" };

export function renderNotifications(body, ctx) {
  let filter = "all";
  const list = h("div", { class: "notification-list" }, loading());
  const head = h("div", { class: "toolbar" },
    segmented([["all", "All"], ["unread", "Unread"]], filter, (v) => { filter = v; load(); }, "Show"),
    h("span", { class: "spacer" }),
    button("Mark all read", { kind: "btn-sm", data: { action: "read-all" }, onclick: () => act(() => api("POST", "/api/notifications/read", {})) }),
    button("Clear read", { kind: "btn-sm btn-ghost", data: { action: "clear-read" }, onclick: () => act(() => api("DELETE", "/api/notifications")) }));
  body.append(h("div", { class: "panel-stack" }, head, list, can(ctx, "notifications.send") ? compose(ctx) : null));

  async function act(fn) {
    try { await fn(); } catch (err) { ctx.toast("Couldn't do that", err.message, "error"); }
    emit("notifications-changed");
  }

  async function load() {
    try {
      const data = await api("GET", `/api/notifications${filter === "unread" ? "?unread=true" : ""}`);
      if (!data.items.length) return fill(list, emptyState(filter === "unread" ? "Nothing unread" : "No notifications", ""));
      fill(list, data.items.map((n) => {
        const item = h("article", { class: `notification level-${n.level}${n.read ? "" : " unread"}`, dataset: { id: n.id } },
          h("span", { class: "notification-icon" }, icon(LEVEL_ICON[n.level] || "list")),
          h("div", { class: "notification-main" },
            h("div", { class: "row" }, h("strong", { text: n.title }),
              h("span", { class: "badge", text: CATEGORY[n.category] || n.category }),
              h("span", { class: "muted small", text: `${ago(n.created_at)}${n.sender !== "system" ? ` · from ${n.sender}` : ""}` })),
            n.body ? h("p", { class: "small", text: n.body }) : null,
            h("div", { class: "row" },
              n.link && PANELS[n.link] ? button(`Open ${PANELS[n.link].title}`, { kind: "btn-sm", onclick: () => { ctx.wm.open(n.link); read(); } }) : null,
              n.read ? null : button("Mark read", { kind: "btn-sm btn-ghost", data: { action: "read-one" }, onclick: read }),
              button("Delete", { kind: "btn-sm btn-ghost", onclick: () => act(() => api("DELETE", `/api/notifications/${n.id}`)) }))));
        function read() { act(() => api("POST", "/api/notifications/read", { ids: [n.id] })); }
        return item;
      }));
    } catch (err) {
      fill(list, errorBox(err));
    }
  }

  on("notifications-changed", load, ctx.signal);
  on("notification", load, ctx.signal);
  load();
}

function compose(ctx) {
  const to = select([["all", "Everyone"]], "all", { name: "to", "aria-label": "To" });
  api("GET", "/api/notifications/recipients").then((us) => us.forEach((u) => to.append(h("option", { value: String(u.id), text: u.username }))))
    .catch(() => {});
  const title = input({ name: "title", required: true, maxlength: "120" });
  const text = h("textarea", { class: "input textarea", name: "body", maxlength: "1000", rows: "3" });
  const level = select([["info", "Info"], ["warning", "Warning"], ["critical", "Critical"]], "info", { name: "level" });
  const link = select([["", "No link"], ...Object.entries(PANELS).map(([k, p]) => [k, `Open ${p.title}`])], "", { name: "link" });
  const f = form([
    h("h3", { text: "Send a notification" }),
    h("div", { class: "grid-2" }, field("To", to), field("Level", level)),
    field("Title", title), field("Message", text), field("Button", link, "Optional: a window it opens"),
    h("div", { class: "actions" }, button("Send", { kind: "btn-primary", type: "submit", data: { action: "send-notification" } })),
  ], async () => {
    const r = await api("POST", "/api/notifications/send", {
      to: to.value === "all" ? "all" : Number(to.value), title: title.value, body: text.value,
      level: level.value, link: link.value || null,
    });
    ctx.toast("Sent", `To ${r.to}: ${r.sent} ${r.sent === 1 ? "person" : "people"} (anyone who turned messages off doesn't get it).`);
    title.value = "";
    text.value = "";
  });
  return h("section", { class: "settings-block compose" }, f);
}
