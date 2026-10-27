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

**Phase 2 is complete: v1.1.0 (2026-10-19).**

## Phase 3 milestones
12. Track-and-alert engine, backtester, paper trading (plan: [Milestone 12 plan]({{ site.baseurl }}/project/milestone-12))
   - 12a. Onboarding (first-time server setup, walkthrough, account rules) and smarter alerts (portfolio, wallet changes, allocation drift, trend signals, daily prices): **done**
   - 12b. Live windows (newest data everywhere, launcher follows permissions, remote open) and importing past prices: **done**
   - 12c. Backtester: DCA, rebalancing, buy the dip, trend, with fees and slippage: **done**
   - 12d. Paper trading: orders and profit/loss, risk limits, kill switch: **done**
   - 12e. Readiness tracker, phase 3 review, release v1.2.0: **done** ([review]({{ site.baseurl }}/project/phase-3-review))

**Phase 3 is complete: v1.2.0 (2026-10-22).** Phase 4 (live trading) can be planned and built
now; switching it on requires **Ready for live trading?** to be green on the real clock (project
rule 10; [decision of 2026-10-23]({{ site.baseurl }}/project/decisions#the-14-days-and-where-the-gate-sits-2026-10-23)).

## Phase 4 milestones
13. Live trading, small and capped (plan: [Milestone 13 plan]({{ site.baseurl }}/project/milestone-13))
   - 13a. Trading keys (personal and shared), exchange switches, permissions, caps
   - 13b. Placing orders on each exchange (limit with price protection, or market)
   - 13c. Live bots: real orders within caps, reconciled fills, kill switch on the exchange
   - 13d. Safety in practice: first tiny order, live drills, failure cases, notifications
   - 13e. Phase 4 review, real transfers plan, release v1.3.0

## Parked ideas
- Passkeys / WebAuthn as a second 2FA method, once HTTPS is set up (browsers only allow it
  over HTTPS or `localhost`).
- QR code for 2FA setup (milestone 6, drawn by the web UI).
