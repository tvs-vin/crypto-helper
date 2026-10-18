// Settings → Appearance → Wallpaper: pick one (built-in, yours, or published), upload your own
// (the server checks and re-encodes it), and tune how it sits behind the windows.

import { api } from "../api.js";
import { emit, on } from "../bus.js";
import { fill, h } from "../dom.js";
import { currentTheme } from "../theme.js";
import { refreshWallpaper, wallpaperList } from "../wallpaper.js";
import { button, errorBox, loading, segmented, select } from "../ui.js";

const KIND = { video: "Video", animated: "Animated", image: null };

export function wallpaperBlock(ctx) {
  const grid = h("div", { class: "wallpaper-grid" }, loading());
  const status = h("div", { class: "wallpaper-status" });
  const fileIn = h("input", { type: "file", class: "hidden", "aria-label": "Upload a wallpaper" });
  const pref = () => ({ source: "none", fit: "cover", dim: 25, blur: 0, motion: "auto", ...(ctx.state.prefs.wallpaper || {}) });

  const save = async (patch) => {
    const next = { ...pref(), ...patch };
    ctx.state.prefs = await api("PATCH", "/api/me/preferences", { wallpaper: next });
    emit("wallpaper-changed");
  };

  // Tuning controls: live preview while dragging, saved when let go.
  const range = (key, max, label, suffix) => {
    const el = h("input", { type: "range", class: "range", min: "0", max: String(max), step: "1", value: String(pref()[key]),
      "aria-label": label, dataset: { action: `wallpaper-${key}` } });
    const out = h("output", { class: "range-value", text: `${el.value}${suffix}` });
    el.addEventListener("input", () => {
      out.textContent = `${el.value}${suffix}`;
      ctx.state.prefs = { ...ctx.state.prefs, wallpaper: { ...pref(), [key]: Number(el.value) } };
      emit("wallpaper-changed");
    });
    el.addEventListener("change", () => save({ [key]: Number(el.value) }));
    return h("div", { class: "row scale-row" }, h("span", { class: "muted small range-label", text: label }), el, out);
  };
  const fit = select([["cover", "Fill"], ["contain", "Fit"], ["center", "Centre"], ["tile", "Tile"]], pref().fit,
    { "aria-label": "How it fits", dataset: { action: "wallpaper-fit" } });
  fit.addEventListener("change", () => save({ fit: fit.value }));
  const motion = segmented([["auto", "Animate"], ["still", "Still"]], pref().motion, (v) => save({ motion: v }), "Motion");

  async function draw() {
    try {
      const data = await wallpaperList(true);
      fileIn.accept = data.accept;
      const current = pref().source;
      const tile = (key, name, poster, item = null) => {
        const t = h("button", { class: `wallpaper-tile${current === key ? " selected" : ""}`, type: "button",
          "aria-pressed": String(current === key), dataset: { wallpaper: key }, title: name,
          onclick: async () => { await save({ source: key }); draw(); } },
        poster ? h("img", { src: poster, alt: "", loading: "lazy" }) : h("span", { class: "wallpaper-none", text: "None" }),
        h("span", { class: "wallpaper-name" }, name,
          item && KIND[item.kind] ? h("span", { class: "badge", text: KIND[item.kind] }) : null,
          item?.mine ? h("span", { class: "badge ok", text: "yours" }) : null,
          item && !item.builtin && item.published ? h("span", { class: "badge", text: "shared" }) : null));
        return t;
      };
      const selected = data.uploaded.find((w) => w.key === current);
      const own = currentTheme()?.wallpaper;
      const ownItem = own ? [...data.builtin, ...data.uploaded].find((w) => w.key === own)
        || (own.startsWith("user:") ? await api("GET", `/api/wallpapers/${own.slice(5)}`).catch(() => null) : null) : null;
      fill(grid,
        tile("none", "None", null),
        tile("theme", ownItem ? `Theme's own (${ownItem.name})` : "Theme's own (none)", ownItem?.poster || null, ownItem),
        data.builtin.map((w) => tile(w.key, w.name, w.poster, w)),
        data.uploaded.map((w) => tile(w.key, w.name, w.poster, w)));
      fill(status, selected ? h("div", { class: "row" },
        h("span", { class: "muted small", text: `${selected.name}: ${selected.width}×${selected.height}${selected.duration_ms ? `, ${Math.round(selected.duration_ms / 1000)} s` : ""}` }),
        h("span", { class: "spacer" }),
        data.can_publish ? button(selected.published ? "Stop sharing" : "Share with everyone", { kind: "btn-sm", data: { action: "share-wallpaper" },
          onclick: () => act(() => api("PATCH", `/api/wallpapers/${selected.id}`, { published: !selected.published }), selected.published ? "No longer shared" : "Shared with everyone") }) : null,
        selected.mine ? button("Delete", { kind: "btn-sm btn-ghost", data: { action: "delete-wallpaper" },
          onclick: () => act(async () => { await api("DELETE", `/api/wallpapers/${selected.id}`); await save({ source: "none" }); }, "Wallpaper deleted") }) : null)
        : null);
      if (!data.video) status.append(h("p", { class: "muted small", text: "Video wallpapers need ffmpeg on the server; pictures and animations work." }));
    } catch (err) {
      fill(grid, errorBox(err));
    }
  }

  async function act(fn, msg) {
    try { await fn(); ctx.toast(msg); } catch (err) { ctx.toast("Couldn't do that", err.message, "error"); }
    refreshWallpaper();
    draw();
  }

  fileIn.addEventListener("change", async () => {
    const file = fileIn.files[0];
    fileIn.value = "";
    if (!file) return;
    const name = file.name.replace(/\.[^.]+$/, "").slice(0, 60) || "My wallpaper";
    const busy = h("p", { class: "small", role: "status", text: `Processing “${name}”… (videos take a little while)` });
    fill(status, busy);
    try {
      const w = await api("POST", `/api/wallpapers?name=${encodeURIComponent(name)}`, file);
      await save({ source: w.key });
      ctx.toast("Wallpaper added", `“${w.name}” is now your wallpaper.`);
    } catch (err) {
      fill(status, errorBox(err));
      return;
    }
    draw();
  });

  draw();
  on("theme-changed", draw, ctx.signal); // "Theme's own" follows the theme
  return h("section", { class: "settings-block" }, h("h3", { text: "Wallpaper" }),
    h("p", { class: "muted", text: "Pictures, animations (GIF/WebP) or short videos (MP4/WebM). Uploads are checked and converted on the server; they're private unless an admin shares them." }),
    grid,
    h("div", { class: "row" }, button("Upload…", { data: { action: "upload-wallpaper" }, onclick: () => fileIn.click() }), fileIn,
      h("span", { class: "spacer" }), fit, motion),
    status,
    range("dim", 80, "Dim", "%"), range("blur", 20, "Blur", " px"));
}
