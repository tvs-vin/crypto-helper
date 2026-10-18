---
title: Milestone 11 plan
---

# Milestone 11: real balances, read-only (phase 2)

Agreed with the owner on 2026-10-18. Phase 2 brings real data in **without anything that can
move money**: read-only exchange keys and public addresses. Five parts, reported one by one.

| Part | Status |
|---|---|
| 11a. Sync foundation (sources, schedule, status, encrypted credentials) | Planned |
| 11b. Exchanges: Coinbase, Kraken, Gemini, Binance.US (read-only keys) | Planned |
| 11c. On-chain: Bitcoin (addresses and xpub), Ethereum + L2s (ETH and common tokens) | Planned |
| 11d. Trade log: trade history from connected exchanges, CSV export for taxes | Planned |
| 11e. Balance history: each wallet's holdings and value over time, charts | Planned |

Owner's answers: exchanges **Coinbase, Kraken, Gemini, Binance.US**; networks **Bitcoin** and
**Ethereum + L2s** first; Bitcoin wallets by **xpub** (the `embit` library is approved for the
key maths); the **trade log in phase 2**.

Defaults (no objection): no exchange SDKs or web3 libraries (plain HTTPS, signed with the
`cryptography` package the app already uses); public data sources, with the owner's own free
API keys optional; sync every 15 minutes plus **Sync now**.

## Rules for the whole phase
- **Never a key that can trade or withdraw** (hard rule #2). Each exchange's key is checked
  in the strongest way that exchange allows, without doing anything with it:
  - Coinbase and Gemini report a key's permissions: anything beyond view/auditor is refused.
  - Kraken and Binance.US: checked as far as their APIs allow (worked out and documented in
    11b); where a permission can't be seen, the guide shows exactly which boxes must stay
    unticked and the owner confirms it.
- **API secrets are not wallet keys**, and they're handled like the other secrets: encrypted at
  rest, entered once, never shown again (only a masked label), never logged, never audited in
  full. The seed phrase and private key rules (#4) are unchanged: nothing here ever asks for one.
- **Read-only calls only.** Each exchange client contains only the endpoints it needs to read
  (balances, trades, the permission check), so nothing that could place an order or withdraw is
  even there to call by mistake. A test lists each client's endpoints.
- **Network calls never hold a database lock** (fetch first, then write), and every source has
  a time limit and a mock for tests. Sync failures are logged per wallet and, if they keep
  failing, sent as a notification.
- **Exact amounts:** everything from an API is parsed as text into `Decimal`.

## 11a: sync foundation
- A wallet's **source**: `manual` (today), `exchange` (a connection to one exchange account), or
  `onchain` (one or more public addresses or an xpub on one network). Paper wallets stay manual.
- **Connections** (Settings or the Wallets window): add, check, rename, remove; the secret is
  stored encrypted and only a masked label is shown.
- **Sync:** a background job every 15 minutes (adjustable), plus **Sync now** on a wallet. Synced
  holdings replace the wallet's balances; they can't be edited by hand (the wallet can be
  switched back to manual). Coins the app doesn't know are listed as "not tracked" rather than
  added automatically (no spam tokens).
- **Status** on each wallet: last synced, next sync, last error. Repeated failures (e.g. a key
  revoked on the exchange) → a notification to the wallet's creator and admins.
- Audit: connections added/removed, sources changed (never the secret).

## 11b: exchanges
Read-only clients for **Coinbase** (Advanced Trade API, CDP keys), **Kraken**, **Gemini** and
**Binance.US**: balances (spot; staking/earn where the read-only API shows them).
- A **guide per exchange** with numbered steps and screenshots-in-words: where to create the
  key, which single permission to tick, IP allow-listing (recommended where offered), how to
  revoke it.
- The permission check on every save, and again on each sync (a key changed on the exchange
  side to allow trading is refused from then on).
- Rate limits respected; clear errors ("Kraken says the key is invalid: was it deleted?").

## 11c: on-chain
- **Bitcoin:** single addresses, or an **xpub/ypub/zpub** (watch-only, as exported by Ledger,
  Trezor, Sparrow, BlueWallet…): the app derives the wallet's receive and change addresses
  (`embit`), scans until it finds an unused gap (20 by default), and sums them. Balances from a
  public Esplora API (mempool.space by default; any Esplora URL, including your own node's, can
  be set).
- **Ethereum, Base, Arbitrum, Optimism, Polygon:** ETH/POL and a fixed list of well-known tokens
  per network (USDC, USDT, DAI, WBTC…, with their official contract addresses in
  `app/networks.py`). Unknown tokens are ignored (airdropped scam tokens are common). Public RPC
  endpoints by default; your own (Alchemy, Infura…) can be set.
- The xpub is treated as private (it reveals every address of the wallet): encrypted, masked.

## 11d: trade log
- Trades (fills) from each connected exchange: time, pair, side, quantity, price, fee and fee
  coin, exchange trade id (no duplicates on re-import). First import goes as far back as each
  exchange allows; later syncs fetch new ones.
- A **Trade log** window: filter by exchange, coin, date; **CSV export** in a plain layout that
  tax software can import (and documented columns).
- Cost basis and gains are left to tax software (phase 3 may add a summary).

## 11e: balance history
- After each sync, each wallet's holdings and their value are recorded (kept detailed for a
  while, then compacted daily, like price history).
- Charts: per wallet (in the Wallets window) and the whole portfolio over time (Overview).

## Not in phase 2
Trading of any kind, withdrawals, transfers, private keys or seed phrases, DeFi positions,
NFTs, other networks (they can follow the same pattern later).
