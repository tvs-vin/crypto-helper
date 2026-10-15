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
All keys are required; unknown keys are refused. At most 32 KB.

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
| Dark | Near-black, violet accent, hairline borders: the default, modelled on the SaaSLauncher design language |
| Light | The same, on a light background |
| Terminal | Phosphor green on black, all monospace, square corners, compact |
| Template | A copy of Dark to start your own from |

The fonts (Inter, Mona Sans, JetBrains Mono) are served by the app itself under the SIL Open
Font License; see `app/web/fonts/`.
