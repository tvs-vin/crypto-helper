// Settings → Embeds: links that show chosen wallet or price data outside the app (Discord
// previews, website iframes). Every item has its own switch; amounts and values start off.

import { api } from "../api.js";
import { fill, h } from "../dom.js";
import { ago } from "../format.js";
import { BUILTIN } from "../theme.js";
import { button, copyable, emptyState, errorBox, field, form, input, loading, segmented,
  select, sheet } from "../ui.js";

const KIND_TEXT = {
  portfolio: "Portfolio: your coins as shares of the total",
  wallets: "Wallets: the wallet cards",
  prices: "Prices: a price table",
};

export function embedsSection(main, ctx) {
  const area = h("div", { class: "panel-stack" }, loading());
  main.append(area);
  draw(area, ctx);
}

async function draw(area, ctx) {
  try {
    const [meta, embeds] = await Promise.all([api("GET", "/api/embeds/meta"), api("GET", "/api/embeds")]);
    fill(area,
      meta.enabled ? null : h("div", { class: "notice warn" },
        h("strong", { text: "The embed server is off. " }),
        "You can set embeds up now; the links open once it's on. On the VM run:",
        copyable(meta.enable_command)),
      h("p", { class: "muted small", text: `Links use ${meta.base_url}. Discord shows each embed's preview image; websites you list can show the live page.` }),
      h("div", { class: "actions" }, button("New embed", { kind: "btn-primary", data: { action: "new-embed" },
        onclick: () => edit(area, ctx, meta, null) })),
      embeds.length ? h("div", { class: "embed-list" }, embeds.map((e) => card(area, ctx, meta, e)))
        : emptyState("No embeds yet", "Make one to share a view of your portfolio or prices."));
  } catch (err) {
    fill(area, errorBox(err));
  }
}

function card(area, ctx, meta, e) {
  const expired = e.expires_at && new Date(`${e.expires_at}Z`) < new Date();
  const status = !e.enabled ? "off" : expired ? "expired" : "on";
  const sensitive = Object.entries(meta.items).filter(([k, v]) => v.sensitive && e.options.items[k]).map(([, v]) => v.label);
  const act = async (fn) => { try { await fn(); draw(area, ctx); } catch (err) { ctx.toast("Couldn't do that", err.message, "error"); } };
  return h("article", { class: "embed-card", dataset: { embed: e.id } },
    h("img", { class: "embed-preview", src: `/api/embeds/${e.id}/preview.png?v=${Date.now()}`, alt: `Preview of ${e.name}`,
      width: "300", height: "158", loading: "lazy" }),
    h("div", { class: "panel-stack" },
      h("div", { class: "row" }, h("h3", { text: e.name }),
        h("span", { class: `badge ${status === "on" ? "ok" : "warn"}`, text: status }),
        h("span", { class: "muted small", text: `${e.kind} · ${e.views} view(s)${e.last_viewed_at ? `, last ${ago(e.last_viewed_at)}` : ""}` })),
      sensitive.length ? h("p", { class: "warn-text small", text: `Shows: ${sensitive.join(", ")}` }) : null,
      h("label", { class: "muted small", text: "Link (Discord, chat, a browser)" }), copyable(e.url),
      e.options.allowed_origins.length
        ? h("div", {}, h("label", { class: "muted small", text: `For ${e.options.allowed_origins.join(", ")}` }), copyable(e.iframe))
        : h("p", { class: "muted small", text: "No websites may show it in a frame yet (add one under Edit)." }),
      h("div", { class: "row" },
        button("Edit", { kind: "btn-sm", data: { action: "edit-embed" }, onclick: () => edit(area, ctx, meta, e) }),
        button(e.enabled ? "Turn off" : "Turn on", { kind: "btn-sm", data: { action: "toggle-embed" },
          onclick: () => act(() => api("PATCH", `/api/embeds/${e.id}`, { enabled: !e.enabled })) }),
        button("New link", { kind: "btn-sm", title: "The current link stops working", data: { action: "rotate-embed" },
          onclick: () => act(() => api("POST", `/api/embeds/${e.id}/rotate`)) }),
        button("Delete", { kind: "btn-sm btn-ghost", data: { action: "delete-embed" },
          onclick: () => act(() => api("DELETE", `/api/embeds/${e.id}`)) }))));
}

function edit(area, ctx, meta, e) {
  const body = area.closest(".window-body");
  sheet(body, e ? `Edit ${e.name}` : "New embed", (close) => {
    const o = e?.options || {};
    const name = input({ value: e?.name || "", required: true, maxlength: "60", name: "name" });
    const heading = input({ value: o.heading || "", maxlength: "80", name: "heading", placeholder: "Defaults to the name" });
    let kind = e?.kind || "portfolio";
    const kindHint = h("p", { class: "hint", text: KIND_TEXT[kind] });
    const kindCtl = segmented([["portfolio", "Portfolio"], ["wallets", "Wallets"], ["prices", "Prices"]], kind,
      (v) => { kind = v; kindHint.textContent = KIND_TEXT[v]; walletsField.classList.toggle("hidden", v === "prices"); }, "Kind");
    const items = h("div", { class: "perm-list" }, Object.entries(meta.items).map(([key, it]) => {
      const box = h("input", { type: "checkbox", dataset: { item: key }, checked: o.items ? o.items[key] : it.default });
      const warnLine = h("span", { class: "warn-text small", text: it.sensitive ? " Shows how much you hold to anyone with the link." : "" });
      return h("label", { class: "check perm" }, box, h("span", {}, it.label, it.sensitive ? warnLine : null));
    }));
    const walletBox = h("div", { class: "perm-list" }, loading());
    const walletsField = field("Wallets (none ticked: all active wallets)", walletBox);
    walletsField.classList.toggle("hidden", kind === "prices");
    api("GET", "/api/wallets?sort=name").then((ws) => fill(walletBox, ws.map((w) => h("label", { class: "check" },
      h("input", { type: "checkbox", value: w.id, checked: (o.wallet_ids || []).includes(w.id) }), h("span", { text: w.display_name })))));
    const symbols = input({ value: (o.symbols || []).join(", "), name: "symbols", placeholder: "BTC, ETH (empty: all)" });
    const theme = select(BUILTIN.map((t) => [t, t[0].toUpperCase() + t.slice(1)]), o.theme || "dark", { name: "theme" });
    api("GET", "/api/themes").then((t) => t.custom.forEach((c) => theme.append(h("option", { value: c.key, text: c.name, selected: c.key === o.theme }))));
    const fiat = select(["usd", "eur", "gbp", "jpy", "cad", "aud"].map((f) => [f, f.toUpperCase()]), o.fiat || ctx.state.prefs.fiat, { name: "fiat" });
    const refresh = select([[60, "1 minute"], [300, "5 minutes"], [900, "15 minutes"], [3600, "1 hour"]], o.refresh_seconds || 300, { name: "refresh" });
    const origins = h("textarea", { class: "input textarea", rows: "2", name: "origins", placeholder: "https://myblog.example.com" });
    origins.value = (o.allowed_origins || []).join("\n");
    const expires = input({ type: "date", name: "expires", value: e?.expires_at ? localDate(e.expires_at) : "" });
    return form([
      h("div", { class: "grid-2" }, field("Name", name, "Only you see this"), field("Heading", heading)),
      field("Show", h("div", {}, kindCtl, kindHint)),
      field("What it shows (each one separately)", items),
      walletsField,
      h("div", { class: "grid-2" }, field("Coins", symbols), field("Currency", fiat)),
      h("div", { class: "grid-2" }, field("Theme", theme), field("Refreshes every", refresh)),
      field("Websites that may show it in a frame (one per line)", origins, "Discord doesn't need this; it uses the preview image."),
      field("Stops working on (optional)", expires),
      h("div", { class: "actions" }, button("Cancel", { onclick: close }),
        button(e ? "Save" : "Create embed", { kind: "btn-primary", type: "submit", data: { action: "save-embed" } })),
    ], async () => {
      const options = {
        heading: heading.value,
        items: Object.fromEntries([...items.querySelectorAll("input")].map((b) => [b.dataset.item, b.checked])),
        wallet_ids: [...walletBox.querySelectorAll("input:checked")].map((b) => Number(b.value)),
        symbols: symbols.value.split(",").map((s) => s.trim()).filter(Boolean),
        theme: theme.value, fiat: fiat.value, refresh_seconds: Number(refresh.value),
        allowed_origins: origins.value.split("\n").map((s) => s.trim()).filter(Boolean),
      };
      // The end of the chosen day where the user is, sent as UTC (the server stores UTC).
      const expires_at = expires.value ? new Date(`${expires.value}T23:59:59`).toISOString() : null;
      if (e) await api("PATCH", `/api/embeds/${e.id}`, { name: name.value, options, expires_at });
      else await api("POST", "/api/embeds", { name: name.value, kind, options, expires_at });
      close();
      ctx.toast(e ? "Embed saved" : "Embed created");
      draw(area, ctx);
    });
  });
}

function localDate(utcText) {
  const d = new Date(`${utcText}Z`);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
