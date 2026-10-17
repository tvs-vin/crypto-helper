---
title: Roadmap
---

# Roadmap

| Phase | Scope | Money at risk |
|---|---|---|
| 1 | Dashboard: auth, users/permissions, wallets (paper), simulated transfers, prices, web UI | None |
| 2 | Read-only exchange keys, on-chain balances by public address | None |
| 3 | Track-and-alert engine, backtester, paper trading, kill switch | None (paper) |
| 4 | Live: tiny capped positions, hardware-wallet approved transfers | Small |

## Phase 1 milestones
1. Skeleton and auth: **done**
2. Users, permissions, audit: **done**
3. 2FA (TOTP), recovery codes, migrations, encryption at rest, `crypto-helper` CLI: **done**
3b. Installable service: `install.sh`, sandboxed systemd unit, service user, daily backups, `crypto-helper service|update|doctor|serve|version|config`, automatic rollback, service lifecycle test: **done**
4. Wallets, holdings, simulated transfers: **done**
5. Prices, portfolio, price history, extra coins, preferences: **done**
6. Web UI (detailed plan: [Milestone 6 plan]({{ site.baseurl }}/project/milestone-6))
   - 6a. NetBird access, design system, desktop with floating + tiled windows, sign-in flow, themes: **done**
   - 6b. Data windows (wallets, overview, transfers, audit): **done**
   - 6c. Full settings, `.ctheme` upload and sharing, QR 2FA, sessions, users, system: **done**
   - 6d. Embeds: separate server, per-item toggles, Discord previews, website iframes: **done**
7. Apps, services, console and terminal (plan: [Milestone 7 plan]({{ site.baseurl }}/project/milestone-7))
   - 7a. App access layer and App manager: **done**
   - 7b. Root agent, Services window, choosing services at setup: **done**
   - 7c. Console and Terminal windows: **done**
8. Scale, wallpapers, theme bundles, guided wallets (plan: [Milestone 8 plan]({{ site.baseurl }}/project/milestone-8))
   - 8a. Display scale and wallpapers: **done**
   - 8b. Theme bundles (`.ctheme` packages with wallpapers and icons): **done**
   - 8c. Guided wallet creation: **done**
9. Notifications (plan: [Milestone 9 plan]({{ site.baseurl }}/project/milestone-9))
   - 9a. Notification centre, sending by hand, live delivery
   - 9b. Discord webhooks
   - 9c. Automatic: security events and system health
   - 9d. Price alerts (the start of track-and-alert)
10. Wrap-up: README, `.env.example` (systemd unit and backups move to 3b)

## Parked ideas
- Passkeys / WebAuthn as a second 2FA method, once HTTPS is set up (browsers only allow it
  over HTTPS or `localhost`).
- QR code for 2FA setup (milestone 6, drawn by the web UI).
