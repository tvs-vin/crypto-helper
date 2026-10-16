---
title: Milestone 7 plan
---

# Milestone 7: apps, services, console and terminal

Agreed with the owner on 2026-10-16. Built in three parts, each reported before the next.

| Part | Status |
|---|---|
| 7a. App access layer and the App manager window | Done |
| 7b. The root agent, the Services window, choosing services at setup | Done |
| 7c. Console and Terminal windows | Done |

The old wrap-up milestone (README, `.env.example`) is now milestone 8.

## 7a: apps and the App manager
Owner's answers: apps sit **on top of** permissions; a per-app master switch turns an app off
for everyone **except super**.
- An *app* is a window: Wallets, Overview, Transfers, Audit log, Users, App manager (and later
  Services, Console, Terminal). Settings is always available (account security lives there).
- To use an app an account needs **both**: the app switched on for it (and not switched off
  for everyone), and the permissions the app needs. `super` can always use every app.
- **Enforced by the server**: each API endpoint names the apps that use it, and answers 403 if
  the account can use none of them (e.g. turning Wallets off for someone blocks wallet editing,
  while Transfers can still list wallets). Hiding a window is not the check.
- Each account stores its app list (`users.apps`; empty means "every app", so existing
  accounts keep working and new apps appear as they're added).
- **App manager** window, permission `apps.manage`: a grid of apps × accounts, and the
  master switch per app. Same rules as the Users window: never super, never yourself, never a
  user with permissions you don't hold, and only apps you can use yourself. Audited.

## 7b: agent and Services
Owner's answers: services are turned on and off from a **Services** window (own permission,
`services.manage`), and the setup offers which services to install.
- The web app runs sandboxed and can't start system services, so a small root **agent**
  (`crypto-helper-agent.service`) does a fixed list of jobs over a private Unix socket: turn
  our own services on/off, run allowlisted `crypto-helper` commands, open a login prompt.
  It never runs arbitrary commands.
- Installing the agent is the one choice made from SSH (setup asks; or
  `crypto-helper agent enable`). Everything else is then in the Services window.
- The Services window covers everything built so far: the web UI, embed server, daily
  backups, price history recording, paper wallets, practice transfers, practice (mock)
  prices, the self-test (end-to-end tester on a throwaway copy), and Console/Terminal.

## 7c: Console and Terminal
Owner's answers: **both, as two apps**; only **super can grant** the terminal; **2FA and
re-confirming** password + code to open.
- **Console** (`console.use`): runs only allowlisted `crypto-helper` commands (status,
  doctor, logs, version, prices check, embed status, update check, backup) through the agent.
- **Terminal** (`terminal.use`, grantable only by super): the VM's own `login:` prompt in a
  pty opened by the agent. Signing in needs a **Linux** account's password (checked by the
  system's `login`, not our code); then a normal shell where `sudo` works as over SSH.
- Opening either needs 2FA on the account; the terminal re-asks password + code each time.
  Opens are rate-limited per account (limits password guessing at the login prompt), opens
  and closes are audited, keystrokes are never logged.

### 7c design (as built)
- Both are **off until switched on** in the Services window (agent writes `BOT_CONSOLE_ENABLED`
  / `BOT_TERMINAL_ENABLED` in the root-owned config; the agent refuses while off).
- **Console**: the agent runs an allowlisted `crypto-helper` command (ids map to fixed argv,
  never text from the request) as a one-off systemd unit (`systemd-run --wait --pipe`), so
  the agent's own sandbox stays shut (no network) while commands like `prices check` work.
  Output is captured (size and time limits) and shown. Needs `console.use` + 2FA on the account.
- **Terminal**: the agent starts a one-off unit running `crypto-helper agent terminal-bridge`
  (root, not sandboxed: a real login session needs that). The bridge makes a one-time socket
  (root:crypto-helper 660, random name, peer user checked, accepts one connection, then
  deletes it), opens a pty and runs `/bin/login -h <client ip>`: the system's own login (PAM)
  checks the Linux password. The web app relays between a WebSocket and that socket.
  Opening needs `terminal.use` (only super can grant it), 2FA, password + code again, a
  one-time 30-second ticket; at most 10 opens an hour per account. The WebSocket checks
  the allowed networks, the Origin, the session cookie, and re-checks the session and
  permission every 30 s. Keystrokes are never logged; opens and closes are audited.
- Browser side: xterm.js 5.5 (MIT, vendored, checksums checked) with the canvas renderer,
  attached before opening so xterm never injects `<style>` elements: works under the strict CSP.

## Queued after 7b/7c (owner's requests, 2026-10-16, to be planned together)
1. A **scale** setting in Settings → Display.
2. **Wallpapers**, including animated ones.
3. Themes that **bundle wallpapers and icons**: `.ctheme` becomes a folder / `.ctheme.d`-style package.
4. **Wallet creation** from inside Crypto Helper. Owner's answer (2026-10-16): build the
   **guided** version now: step-by-step creation in a hardware or phone wallet (keys stay there),
   then Crypto Helper tracks its public address. The owner also wants **key generation in the
   app later**: that conflicts with hard rules 4 and 9 (never create or hold a key or seed
   phrase), so it is **parked** and needs an explicit rule change first; see Decisions.
5. **Several windows of the same app**: **done** (up to 4 for Overview, Wallets, Transfers,
   Audit log; per-window state, starting with Overview's currency, coin and range).
   Original note: (Overview as the main example). Today windows are keyed
   by app everywhere (window manager, taskbar, saved layout, and the server's "each app once"
   layout rule), so each window needs its own id and its own saved state (e.g. which coin and
   chart range an Overview shows), with a per-app limit; apps like Settings stay single.
