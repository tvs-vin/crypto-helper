---
title: Themes
---

# Themes (`.ctheme`)

A theme is a small JSON file with the extension `.ctheme`. It's **data only**: colors, a font
choice from a fixed list, and a few bounded numbers. It can't contain CSS, URLs or code, so
a theme someone sends you can't load anything from elsewhere, track you, or break the page.
Anything else is refused, both by the server and again by the browser.

Start from **Template** (Settings → Theme, or `app/web/themes/template.ctheme`): it has every
key with the Dark theme's values.

## Uploading and sharing
- Upload in Settings → Appearance: a plain `.ctheme` (JSON) or a **bundle** (below). Up to 20
  per user. API: `POST /api/themes/upload` with the file as the raw body (either kind), or
  `POST /api/themes` with `{"content": "<file text>"}` (plain only).
- Uploads are **private** to you. Someone with `themes.publish` (admins by default) can
  **publish** their own theme so everyone sees it in their list, and unpublish any published
  one. Anyone can **download** a theme they can see and send the file to someone (a bundle
  downloads as a bundle, with its wallpapers and icons; `GET /api/themes/{id}/bundle`).
- If a theme you're using is deleted or unpublished, you go back to Dark.
- A refused file gets a list of what's wrong (by key), never the offending values.

## Format
```json
{
  "format": "crypto-helper-theme",
  "version": 1,
  "name": "My theme",
  "author": "you",
  "description": "optional, up to 300 characters",
  "mode": "dark",
  "colors": { "desktop": "#0C0C13", "...": "every key below" },
  "fonts": { "body": "Inter", "heading": "Mona Sans", "mono": "JetBrains Mono" },
  "shape": { "radius": 6, "window_radius": 8, "border_width": 1 },
  "effects": { "glow": true, "shadow": "soft" },
  "density": "comfortable"
}
```
All keys above are required; unknown keys are refused. At most 1 MB. Three keys are optional:

| Key | What |
|---|---|
| `icons` | Replace icons with vector shapes: `{"chart": ["M2.5 13.5h11", "M3.5 11l2.5-3.5 …"]}`. Each icon is 1-8 SVG path strings drawn in a 16×16 box, using only path letters, numbers, spaces, commas, dots and signs (nothing that could be anything but a shape). |
| `icon_images` | Replace icons with small pictures: `{"wallet": "data:image/png;base64,…"}`. PNG only, re-encoded by the server to at most 64×64 (and 16 KB); in a bundle, put them in `icons/` instead. |
| `wallpaper` | The theme's own wallpaper, used when your wallpaper is **Theme's own**: a built-in one (`"builtin:dusk"`), or in a bundle one of its files (`"wallpapers/sky.webp"`). |

Icon names: `minimize maximize restore close apps console terminal plus server appgrid tile
floating logout settings wallet chart transfer users list shield`. Any icon a theme leaves out
keeps the built-in one; switching to another theme brings the built-in icons back.

## Bundles
A **bundle** is a `.ctheme` that's a zip of a theme with its wallpapers and icons. You make it
from a folder (the editable form, by convention `name.ctheme.d`):
```
sunset.ctheme.d/
  theme.json             the theme, as above ("wallpaper": "wallpapers/dusk.webp")
  wallpapers/dusk.webp   up to 5: png, jpg, webp, gif, mp4, webm
  icons/wallet.png       PNG icons, named after the icon they replace
```
```bash
crypto-helper theme check sunset.ctheme.d     # everything the server checks, wallpapers converted
crypto-helper theme pack sunset.ctheme.d      # -> sunset.ctheme, ready to upload
crypto-helper theme unpack sunset.ctheme      # -> sunset.ctheme.d, to edit
```
`examples/themes/sunset.ctheme.d` in the repo is a working example.

On upload, a bundle is checked before anything is unpacked, then each part like an upload of
its own:
- Only the names above (no paths out of the bundle, no links, no encryption), at most 60
  files and 80 MB, 200 MB unpacked, and nothing compressed suspiciously well (zip bombs).
- `theme.json`: every rule on this page. A `wallpaper` must be a file in the bundle.
- Wallpapers: converted like any [wallpaper upload]({{ site.baseurl }}/guides/using-the-desktop#wallpaper).
  They belong to the theme: visible to whoever can see the theme, gone when it's deleted.
- Icons: re-encoded PNGs; a name that isn't an icon is refused.

`theme pack` only packs those files (anything else in the folder, or a link, is an error, so
nothing private goes in by accident).

## Colors
Each is `#RGB`, `#RRGGBB` or `#RRGGBBAA` (the last two digits are opacity).

| Key | Used for |
|---|---|
| `desktop` | The desktop behind the windows |
| `desktop_glow` | The soft glow from the desktop's corners, or `"none"` |
| `surface` | Window bodies, menus, the sign-in box |
| `surface_alt` | Inputs, hovered rows, secondary areas |
| `titlebar` / `titlebar_active` | Window title bars, inactive / focused |
| `taskbar` | The bar at the bottom |
| `border` / `border_strong` | Hairlines / emphasised borders (focused window, inputs) |
| `text` / `text_muted` / `heading` | Body text / secondary text / headings and important text |
| `accent` / `accent_hover` / `accent_text` | Buttons, highlights / their hover / text on them |
| `positive` / `negative` / `warning` | Gains / losses and errors / warnings |
| `focus` | Keyboard focus ring |
| `overlay` | The dimmed layer behind the sign-in box (use some transparency) |
| `selection` | Selected text |

## Other values
| Key | Allowed |
|---|---|
| `mode` | `dark` or `light` (tells the browser which way to draw scrollbars and form controls) |
| `fonts.body`, `fonts.heading`, `fonts.mono` | `Inter`, `Mona Sans`, `JetBrains Mono`, `system-ui`, `sans-serif`, `serif`, `monospace` |
| `shape.radius` | 0-16 (pixels; buttons and inputs) |
| `shape.window_radius` | 0-20 (pixels; windows) |
| `shape.border_width` | 0-3 (pixels) |
| `effects.glow` | `true` / `false` |
| `effects.shadow` | `none`, `soft`, `strong` |
| `density` | `comfortable` or `compact` (tighter spacing and smaller text) |
| `name` | 1-40 characters; `author` up to 60; no `<` `>` or control characters |

## Built-in themes
| Theme | Look |
|---|---|
| Dark | Near-black, violet accent, hairline borders: the default, modelled on the SaaSLauncher design language. Its own wallpaper: Aurora |
| Light | The same, on a light background. Its own wallpaper: Paper |
| Terminal | Phosphor green on black, all monospace, square corners, compact. Its own wallpaper: Midnight grid |
| Template | A copy of Dark to start your own from |

The fonts (Inter, Mona Sans, JetBrains Mono) are served by the app itself under the SIL Open
Font License; see `app/web/fonts/`.
