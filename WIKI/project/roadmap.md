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
3b. Installable service: `install.sh`, systemd unit, service user, `crypto-helper service|update|doctor`
4. Wallets, holdings, simulated transfers
5. Prices and preferences
6. Web UI (windows, tiling, themes)
7. Wrap-up: README, `.env.example` (systemd unit and backups move to 3b)

## Parked ideas
- Passkeys / WebAuthn as a second 2FA method, once HTTPS is set up (browsers only allow it
  over HTTPS or `localhost`).
- QR code for 2FA setup (milestone 6, drawn by the web UI).
