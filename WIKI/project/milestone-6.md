---
title: Milestone 6 plan
---

# Milestone 6 plan (web UI)

The agreed scope, written down so it doesn't depend on anyone's memory. Decisions with the
owner are also summarised in [Decisions]({{ site.baseurl }}/project/decisions#milestone-6-decisions).

| Part | Status |
|---|---|
| 6a. NetBird access, design system, desktop (floating + tiled), sign-in flow, themes engine | Done |
| 6b. Data windows: wallets, overview + charts, transfers, audit | Done |
| 6c. Full settings, `.ctheme` upload and sharing, QR 2FA, sessions, users, system | Done |
| 6d. Embeds | Done |

## 6c: the full Settings window
Sections appear only with the permission; the server checks again anyway.

| Section | Contents |
|---|---|
| Account | Change password; 2FA on/off with a **QR code** (server-side SVG via `segno`, shown as an image) plus the setup key; recovery codes (show once, replace); **your active sessions** with "sign out other sessions" (new endpoints) |
| Appearance | Theme picker; **upload `.ctheme`** (validated by `app/themes.py`, errors shown plainly); download any theme; the Template; live preview before saving |
| Display | Currency, watchlist, overview columns and sort, wallet order, reset layout |
| Users | Built as its own **Users** window (`users.manage`) rather than a Settings section: list, create from presets, edit permissions, deactivate, reset password, delete; permissions you don't hold are greyed out |
| Prices | (`prices.manage`) history settings form; extra coins with the look-alike confirmation |
| System | (`super` only) version and commit, health summary (like `doctor`), last backup, price source status; root-only actions show the exact `crypto-helper` command to run |

Theme rules agreed with the owner:
- Uploads are **private** to the uploader; an admin can **publish** one to everyone's theme list.
- Anyone can export a theme as a `.ctheme` file to share.
- Themes are data only: never CSS, URLs or code (checked by the server and again in the browser).
- Stored server-side (new table, migration), with a size limit and a per-user count limit.

## 6d: embeds
Agreed with the owner:
- A **separate embed-only service** (`crypto-helper-embed`, same sandbox), its own port
  (`BOT_EMBED_PORT`, default 8001) and **configurable bind address(es)** (`BOT_EMBED_HOST`),
  **off by default** (`BOT_EMBED_ENABLED=false`). It contains only embed pages: no login, no API.
- Binding the embed port to every interface is allowed only with `BOT_EMBED_ALLOW_PUBLIC=true`
  (`doctor` warns while on). The main server still never binds `0.0.0.0`.
- Each embed link: a long random token; which window, which wallets/coins; **every item has
  its own on/off toggle** (amounts and values start **off** with a warning when enabled; the
  rest start on); theme; optional expiry; view counter; revoke; audited.
- Discord can't show live windows: Discord fetches a title, description and **one image**, so
  embeds render a PNG preview server-side (`Pillow`) and refresh it periodically.
- Websites can `<iframe>` the live embed, only on sites the owner lists (`frame-ancestors`).
- Rate-limited. Reaching it from the internet goes through a tunnel the owner sets up
  (Cloudflare Tunnel or Tailscale Funnel) or the opt-in public bind.

### What 6d shipped
- `crypto-helper embed enable|disable|status`, `serve --embed`, the `crypto-helper-embed`
  unit (installed with the others, enabled only when embeds are on; `update` refreshes it).
- Three kinds (portfolio, wallets, prices), twelve switches, wallet and coin scope, theme
  (custom ones too), currency, refresh, expiry, allowed websites.
- Settings → Embeds: list with preview pictures and view counts, create/edit sheet, copy
  link and frame code, turn off, new link, delete; a notice with the command when the server is off.
- Guide: [Embeds]({{ site.baseurl }}/guides/embeds).

## How each part is verified
Unit tests, real-browser tests (Playwright/Chromium) with screenshots reviewed, mutation checks
on each guard, deploy to the owner's VM with `crypto-helper update`, and a report with
screenshots saved on the VM.
