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
   - 6d. Embeds: separate server, per-item toggles, Discord previews, website iframes
7. Wrap-up: README, `.env.example` (systemd unit and backups move to 3b)

## Parked ideas
- Passkeys / WebAuthn as a second 2FA method, once HTTPS is set up (browsers only allow it
  over HTTPS or `localhost`).
- QR code for 2FA setup (milestone 6, drawn by the web UI).
