import { h } from "./dom.js";

let box = null;

export function toast(title, text = "", kind = "info", ms = 6000) {
  if (!box) {
    box = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(box);
  }
  const el = h("div", { class: `toast ${kind}` }, h("div", {}, h("strong", { text: title }), text));
  box.append(el);
  if (ms) setTimeout(() => el.remove(), ms);
  return el;
}
