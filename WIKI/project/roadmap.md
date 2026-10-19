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
   - 9a. Notification centre, sending by hand, live delivery: **done**
   - 9b. Discord webhooks: **done**
   - 9c. Automatic: security events and system health: **done**
   - 9d. Price alerts (the start of track-and-alert): **done**
10. Wrap-up and release (plan: [Milestone 10 plan]({{ site.baseurl }}/project/milestone-10))
   - 10a. README, `.env.example`, the Help window: **done**
   - 10b. Phase 1 review (security and quality): **done** ([report]({{ site.baseurl }}/project/phase-1-review))
   - 10c. Pinned dependencies, CI, changelog, merge to `main`, tag v1.0.0: **done**

**Phase 1 is complete: v1.0.0 (2026-10-17).**

## Phase 2 milestones
11. Real balances, read-only (plan: [Milestone 11 plan]({{ site.baseurl }}/project/milestone-11))
   - 11a. Sync foundation (sources, schedule, status, encrypted credentials): **done**
   - 11b. Exchanges: Coinbase, Kraken, Gemini, Binance.US (read-only keys): **done**
   - 11c. On-chain: Bitcoin (addresses and xpub), Ethereum + L2s: **done**
   - 11d. Trade log with CSV export for taxes: **done**
   - 11e. Balance history and charts: **done**

**Phase 2 is complete (2026-10-19).** Next: release it, then plan phase 3 (track-and-alert
engine, backtester, paper trading, kill switch) with the owner.

## Parked ideas
- Passkeys / WebAuthn as a second 2FA method, once HTTPS is set up (browsers only allow it
  over HTTPS or `localhost`).
- QR code for 2FA setup (milestone 6, drawn by the web UI).
