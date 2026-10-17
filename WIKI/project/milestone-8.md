---
title: Milestone 8 plan
---

# Milestone 8: scale, wallpapers, theme bundles, guided wallets

Agreed with the owner on 2026-10-16. Three parts, each reported before the next. The old
wrap-up milestone (README, `.env.example`) is now milestone 9.

| Part | Status |
|---|---|
| 8a. Display scale and wallpapers | Done |
| 8b. Theme bundles (`.ctheme` packages with wallpapers and icons) | Planned |
| 8c. Guided wallet creation | Planned |

## 8a: display scale and wallpapers
**Scale** (owner: "both"): a slider in Settings → Display, 75%-150%. The account has a default
that follows you; any device can override it for itself (kept in that browser). The whole
desktop scales together, and window dragging, snapping and tiling still line up.

**Wallpapers** (owner: video plus animated GIF/WebP, re-encoded):
- A built-in set, plus uploads: still images (PNG, JPEG, WebP), animated GIF/WebP, and short
  videos (MP4, WebM).
- Every upload is **re-encoded on the server** (Pillow for images, ffmpeg for video and big
  animations) so only clean, size-limited files reach browsers; metadata (e.g. photo location)
  is stripped. Limits on file size, pixel size and video length; per-user count limit.
- Private to the uploader; an admin with `themes.publish` can publish one for everyone, the
  same way as themes.
- Settings: fit (fill, fit, centre, tile), dim and blur so windows stay readable.
- Animation pauses when the tab is hidden and is off when the device asks for reduced motion
  (with a manual pause too). Videos are muted and never autoplay sound.
- Served from this server only (Content-Security-Policy `media-src 'self'`), never a URL.

## 8b: theme bundles
- `.ctheme` becomes a zip package: `theme.json` (the colours, as today) plus `wallpapers/` and
  `icons/`. A `.ctheme.d` folder is the editable form; `crypto-helper theme pack <folder>` makes
  the shareable file, and the Appearance settings can download a bundle. Plain JSON `.ctheme`
  files keep working.
- Icons (owner: both): **vector path data** in `theme.json` (only shape commands accepted, drawn
  like the built-in icons) and/or **PNG** files (re-encoded). Any icon a theme leaves out uses
  the built-in one.
- Bundles are checked like uploads: zip safety (no paths outside the bundle, no links, size and
  file-count limits before unpacking, no zip bombs), each file re-encoded, unknown files refused.
- A bundled wallpaper can be the theme's default wallpaper.

## 8c: guided wallet creation
Owner: guided creation now; key generation in the app is parked (see Decisions).
- A wizard for **hardware wallets, phone apps, desktop apps and exchange accounts**: what each is
  for, choosing one, setting it up, and the safety basics (seed phrase on paper only, never a
  photo, never typed into any website including this one; check the receive address on the
  device; a small test transfer first). For an exchange account: it explains that the exchange
  holds the coins, and covers 2FA and withdrawal protection.
- It ends by adding the wallet to Crypto Helper by its **public** address (or as an exchange
  wallet), with the network and coin checks the Wallets window already does. Crypto Helper never
  sees a key or a seed phrase; the existing seed-phrase guard still refuses one if pasted.

## Next to think about (owner, 2026-10-16)
After milestone 8: **server notifications**, sent to one user or to all users. To be planned
once 8 is done.
