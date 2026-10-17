// The desktop's wallpaper: a picture, an animation or a muted looping video behind the
// windows, dimmed and blurred to taste. Moving wallpapers stand still when the device asks for
// reduced motion or you choose "still", and pause while the tab is hidden.

import { api } from "./api.js";
import { fill, h } from "./dom.js";
import { currentTheme } from "./theme.js";

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
let layer = null;
let list = null;
let shown = null; // { pref, desktop } last applied, to re-apply when something changes

export async function wallpaperList(force = false) {
  if (force || !list) list = await api("GET", "/api/wallpapers");
  return list;
}

async function resolve(source) {
  if (source.startsWith("builtin:")) {
    return (await wallpaperList()).builtin.find((w) => w.key === source) || null;
  }
  if (source.startsWith("user:")) {
    const id = Number(source.slice(5));
    const known = (await wallpaperList()).uploaded.find((w) => w.id === id);
    return known || api("GET", `/api/wallpapers/${id}`).catch(() => null);
  }
  if (source === "theme") { // the theme's own: a built-in one, or one its bundle brought
    const ref = currentTheme()?.wallpaper;
    return ref ? resolve(ref) : null;
  }
  return null; // "none"
}

export async function applyWallpaper(desktop, pref) {
  shown = { desktop, pref };
  if (!layer) {
    layer = h("div", { class: "wallpaper", "aria-hidden": "true" });
    desktop.prepend(layer);
  }
  const item = pref && pref.source !== "none" ? await resolve(pref.source).catch(() => null) : null;
  if (shown?.pref !== pref) return; // a newer choice arrived while this one loaded
  layer.className = "wallpaper";
  if (!item) return fill(layer);
  const still = pref.motion === "still" || reduced.matches;
  const fit = item.kind === "video" && pref.fit === "tile" ? "cover" : pref.fit;
  let media;
  if (fit === "tile") {
    media = h("div", { class: "wallpaper-media" });
    media.style.backgroundImage = `url("${still && item.kind !== "image" ? item.poster : item.url}")`;
  } else if (item.kind === "video" && !still) {
    media = h("video", { class: "wallpaper-media", src: item.url, poster: item.poster, loop: true,
      muted: true, playsinline: true, autoplay: true, disablepictureinpicture: true, preload: "auto" });
    media.muted = true; // the property, not just the attribute: browsers only autoplay muted video
  } else {
    media = h("img", { class: "wallpaper-media", alt: "", decoding: "async",
      src: still && item.kind !== "image" ? item.poster : item.url });
  }
  if (pref.blur) media.style.filter = `blur(${pref.blur}px)`;
  const dim = h("div", { class: "wallpaper-dim" });
  dim.style.opacity = String((pref.dim ?? 25) / 100);
  layer.classList.add(`fit-${fit}`, ...(pref.blur ? ["blurred"] : []));
  fill(layer, media, dim);
  layer.dataset.wallpaper = item.key;
  layer.dataset.motion = item.kind !== "image" && !still ? "on" : "off";
}

export function clearWallpaper() {
  shown = null;
  if (layer) fill(layer);
}

/** Forget the cached list (after an upload or delete) and redraw. */
export function refreshWallpaper() {
  list = null;
  if (shown) applyWallpaper(shown.desktop, shown.pref);
}

// A hidden tab doesn't need a moving wallpaper; the device's motion setting can change live.
document.addEventListener("visibilitychange", () => {
  const video = layer?.querySelector("video");
  if (!video) return;
  if (document.hidden) video.pause();
  else video.play().catch(() => {});
});
reduced.addEventListener("change", () => { if (shown) applyWallpaper(shown.desktop, shown.pref); });
