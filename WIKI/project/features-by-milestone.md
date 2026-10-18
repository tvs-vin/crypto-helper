---
title: Features by milestone
---

# Features by milestone

What each milestone added, in the order it was built. For what's in each *release*, see
`CHANGELOG.md`; for what's planned next, the [Roadmap]({{ site.baseurl }}/project/roadmap).
Every finished milestone adds its section here in the same commit.

## Phase 1 (released as v1.0.0)

### Milestone 1: skeleton and sign-in (2026-10-14)
- The server itself, with settings from environment variables.
- First launch: a one-time setup token creates the `super` account.
- Passwords stored with argon2id; 5 wrong passwords lock an account for 15 minutes.
- Sessions (signed out after 12 hours), sign out, change your password.
- Protection against forged requests, strict security headers, no API docs exposed.
- The permission catalog that every later feature adds to.
- This wiki.

### Milestone 2: users, permissions, audit log (2026-10-14)
- Create, change, deactivate and delete users; reset their passwords.
- Permission presets; nobody can grant a permission they don't hold or manage someone with
  more than they have; `super` can't be changed.
- The audit log: every change, who made it and from where; never a secret.
- The end-to-end tester (`crypto-helper test`).

### Milestone 3: two-factor login and the CLI (2026-10-14)
- Two-factor login with an authenticator app; 10 one-time recovery codes.
- 2FA secrets encrypted at rest with the secret key.
- Database migrations, so upgrades keep your data.
- The `crypto-helper` command (noun first, asks for sudo when needed).

### Milestone 3b: install it as a service (2026-10-14)
- `install.sh`: a sandboxed systemd service with its own system user.
- `crypto-helper service …`, `update` (backs up, rolls back by itself if it fails), `doctor`.
- Daily automatic backups.
- Listens on this machine only unless you choose an address; never on every interface.

### Milestone 4: wallets and practice transfers (2026-10-14)
- Wallets of three kinds: exchange, on-chain (with a network and public address), paper.
- Nicknames, two colors, tags, archive, your own order.
- Exact balances (never rounded), per coin.
- Simulated transfers that follow real network rules (no BTC to an Ethereum address).
- Safe deleting: move the coins first, archive instead, or type the exact name.
- A guard that refuses anything that looks like a recovery phrase or private key.

### Milestone 5: prices and portfolio (2026-10-14)
- Live prices from CoinGecko (one shared snapshot a minute), in 6 currencies.
- What everything is worth: per coin, per wallet, in total.
- Price history recorded in the background (detailed for a day, hourly candles forever).
- Extra coins by CoinGecko id, with a warning about look-alike scam tokens.
- Your preferences: currency, watchlist, columns.

### Milestone 6a: the web desktop (2026-10-14)
- A desktop in the browser: windows you can drag, resize, snap, maximize and tile.
- Sign-in screen, themes (dark, light, terminal), keyboard shortcuts.
- Your layout is saved and comes back when you sign in.
- Reaching it over NetBird (several listen addresses, allowed client networks).

### Milestone 6b: the data windows (2026-10-15)
- Wallets as cards: grouping, filters, sorting, drag to reorder, edit, set balances.
- Overview: portfolio total, prices, 24-hour change, watchlist, price charts.
- Transfers: the practice transfer form and history.
- Audit log: search and paging.

### Milestone 6c: settings, users, themes (2026-10-15)
- Settings: change password, 2FA with a QR code, recovery codes, where you're signed in.
- Upload, preview, share and delete your own themes.
- Users window; system status for `super`.

### Milestone 6d: embeds (2026-10-15)
- Share a read-only view of your portfolio, wallets or prices: a link for Discord (with a
  preview picture) or a frame for a website.
- A separate embed server, off by default, with a switch for every item shown.

### Milestone 7a: apps and the App manager (2026-10-16)
- Each window is an app; choose which apps each account can use, or switch one off for
  everyone (on top of permissions).

### Milestone 7b: services and the agent (2026-10-16)
- The Services window: switch services and features on and off from the browser.
- The agent: a small root helper with a fixed list of jobs.
- Choose services when installing; practice prices; the self-test.
- Several windows of the same app (for example two Overviews), each with its own settings.

### Milestone 7c: Console and Terminal (2026-10-16)
- Console: run a fixed list of `crypto-helper` commands from the browser.
- Terminal: the VM's own login prompt in a window (2FA, password and a code to open; off by
  default; only `super` can grant it).

### Milestone 8a: display scale and wallpapers (2026-10-17)
- Display scale 75-150 %, for your account and per device.
- Wallpapers: built-in ones, and your own pictures, animations and videos (all converted on
  the server).

### Milestones 8b and 8c: theme bundles, guided wallets (2026-10-17)
- Theme bundles: a theme packaged with its wallpapers and icons.
- Guided wallet setup for hardware, phone, desktop and exchange wallets, with the safety
  steps (the app never sees a key).

### Milestone 9a: notifications (2026-10-17)
- The bell, the Notifications window, pop-ups that arrive live.
- Admins can send a notification to one person or everyone.

### Milestone 9b: Discord (2026-10-17)
- Notifications on Discord through your own webhook (stored encrypted); quiet hours.

### Milestone 9c: automatic notifications (2026-10-17)
- Security: new device, password and 2FA changes, lockouts, recovery codes used, a Terminal
  opened.
- System health: backups, updates, crashes, services, disk space, prices, the self-test.

### Milestone 9d: price alerts (2026-10-17)
- Alerts when a coin goes above or below a price or moves a set percent in 24 hours; each
  fires once and re-arms after the price crosses back.

### Milestone 10a: getting started and Help (2026-10-17)
- `README.md` and `.env.example` (every setting).
- Help: this wiki inside the app, with search, and a "?" on every window.

### Milestone 10b: phase 1 review (2026-10-17)
- Checks on every route (sign-in required, changes audited), no secrets in the logs, a size
  limit on requests. Nine findings fixed. See [Phase 1 review]({{ site.baseurl }}/project/phase-1-review).

### Milestone 10c: release (2026-10-17)
- Every dependency pinned to its tested version; tests on GitHub for every change;
  `CHANGELOG.md`; version 1.0.0.

## Phase 2 (in progress)
The plan: [Milestone 11]({{ site.baseurl }}/project/milestone-11). Sections are added here as
each part is finished.
