// Help: the wiki, from the installed copy (app/help.py). The server sends each page as a small
// structure of blocks and inline pieces; it's built here with h() like everything else, so
// nothing in a page is ever used as HTML. Wiki links open inside this window.

import { api } from "../api.js";
import { on } from "../bus.js";
import { fill, h } from "../dom.js";
import { emptyState, errorBox, input, loading } from "../ui.js";

export function renderHelp(body, ctx) {
  const nav = h("nav", { class: "help-nav", "aria-label": "Help pages" });
  const search = input({ type: "search", name: "help_search", placeholder: "Search help", "aria-label": "Search help" });
  const results = h("div", { class: "help-results" });
  const main = h("article", { class: "help-page", tabindex: "-1" });
  const back = h("button", { class: "btn btn-ghost btn-sm", type: "button", disabled: true, dataset: { action: "help-back" },
    "aria-label": "Back" }, h("span", { text: "← Back" }));
  body.append(h("div", { class: "help" },
    h("div", { class: "help-side" }, search, results, nav),
    h("div", { class: "help-main" }, h("div", { class: "help-bar" }, back), main)));

  const history = [];
  let current = null;
  let sections = [];

  back.addEventListener("click", () => {
    const prev = history.pop();
    back.disabled = !history.length;
    if (prev) show(prev.id, prev.anchor, false);
  });

  async function show(id, anchor = null, remember = true) {
    if (remember && current && current !== id) {
      history.push({ id: current });
      back.disabled = false;
    }
    if (id === current && anchor) return scrollTo(anchor);
    fill(main, loading());
    try {
      const page = await api("GET", `/api/help/page?id=${encodeURIComponent(id)}`);
      current = page.id;
      if (page.id.length <= 40) ctx.saveWindowState?.({ page: page.id, anchor: "" });
      fill(main, page.blocks.map((b) => block(b, page.id)));
      markNav();
      if (anchor) scrollTo(anchor);
      else main.scrollTop = 0;
    } catch (err) {
      fill(main, errorBox(err));
    }
  }

  function scrollTo(anchor) {
    const el = [...main.querySelectorAll("[data-anchor]")].find((e) => e.dataset.anchor === anchor);
    el?.scrollIntoView({ block: "start" });
  }

  // ---- building a page ------------------------------------------------------------------------

  function pieces(parts) {
    return parts.map(([kind, text, target]) => {
      if (kind === "code") return h("code", { text });
      if (kind === "strong") return h("strong", { text });
      if (kind === "em") return h("em", { text });
      if (kind === "link" && target?.url) {
        return h("a", { href: target.url, target: "_blank", rel: "noopener noreferrer", title: target.url, text });
      }
      if (kind === "link" && target?.page) {
        return h("a", { href: "#", class: "help-link", dataset: { page: target.page }, text,
          onclick: (e) => { e.preventDefault(); show(target.page, target.anchor); } });
      }
      return text;
    });
  }

  function block(b, pageId) {
    switch (b.t) {
      case "h": return h(`h${Math.min(b.level + 1, 5)}`, { dataset: { anchor: b.id } }, pieces(b.text));
      case "p": return h("p", {}, pieces(b.text));
      case "quote": return h("blockquote", {}, pieces(b.text));
      case "code": return h("pre", { class: "help-code" }, h("code", { text: b.text }));
      case "table": return h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, b.head.map((c) => h("th", {}, pieces(c))))),
        h("tbody", {}, b.rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, pieces(c))))))));
      case "ul": case "ol": return h(b.t, {}, b.items.map((it) =>
        h("li", {}, pieces(it.text), it.blocks.map((x) => block(x, pageId)))));
      default: return null;
    }
  }

  // ---- contents and search ----------------------------------------------------------------------

  function drawNav() {
    fill(nav, sections.map((s) => h("div", { class: "help-section" },
      h("h4", { text: s.title }),
      s.pages.map((p) => h("a", { href: "#", class: "help-nav-item", dataset: { page: p.id }, text: p.title,
        onclick: (e) => { e.preventDefault(); show(p.id); } })))));
    markNav();
  }

  function markNav() {
    nav.querySelectorAll(".help-nav-item").forEach((a) => a.classList.toggle("active", a.dataset.page === current));
  }

  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(runSearch, 200);
  });
  search.addEventListener("keydown", (e) => { if (e.key === "Escape") { search.value = ""; runSearch(); } });
  ctx.signal?.addEventListener("abort", () => clearTimeout(timer));

  async function runSearch() {
    const q = search.value.trim();
    nav.hidden = Boolean(q);
    if (!q) return fill(results);
    try {
      const { results: hits } = await api("GET", `/api/help/search?q=${encodeURIComponent(q)}`);
      if (search.value.trim() !== q) return; // typed on meanwhile
      fill(results, hits.length ? hits.map((r) => h("a", { href: "#", class: "help-hit", dataset: { page: r.id },
        onclick: (e) => { e.preventDefault(); show(r.id, r.anchor); } },
      h("strong", { text: r.title }), r.snippet ? h("span", { class: "muted small", text: r.snippet }) : null))
        : emptyState("Nothing found", "Try other words."));
    } catch (err) {
      fill(results, errorBox(err));
    }
  }

  // Another window's "?" button (wm.openHelp).
  on("help-show", (e) => show(e.detail.page, e.detail.anchor), ctx.signal);

  (async () => {
    try {
      ({ sections } = await api("GET", "/api/help"));
      drawNav();
      show(ctx.windowState?.page || "index", ctx.windowState?.anchor || null, false);
    } catch (err) {
      fill(main, errorBox(err));
    }
  })();
  return { show };
}

