---
title: Milestone 7 plan
---

# Milestone 7: apps, services, console and terminal

Agreed with the owner on 2026-10-16. Built in three parts, each reported before the next.

| Part | Status |
|---|---|
| 7a. App access layer and the App manager window | In progress |
| 7b. The root agent, the Services window, choosing services at setup | Planned |
| 7c. Console and Terminal windows | Planned |

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
