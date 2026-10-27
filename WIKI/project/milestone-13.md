---
title: Milestone 13 plan
---

# Milestone 13: live trading, small and capped (phase 4)

Agreed with the owner on 2026-10-27. Phase 4 is the first time the app touches **real money**:
bots place real orders on an exchange, with trade-only keys and per-person caps. It can be
built now; **switching live trading on** needs **Ready for live trading?** green on the real
clock (project rule 10). Five parts, reported one by one.

| Part | Status |
|---|---|
| 13a. Trading keys (personal and shared), exchange switches, permissions, caps | Done |
| 13b. Placing orders: each exchange's order calls (limit with price protection, or market), tested against local fakes | Planned |
| 13c. Live bots: the paper engine with real orders, caps enforced, real fills reconciled, the kill switch cancels real orders | Planned |
| 13d. Safety in practice: a first tiny order, drills on live bots, what happens when things fail, notifications | Planned |
| 13e. Phase 4 review, plan real transfers with the owner, release v1.3.0 | Planned |

## Owner's answers
- **Exchanges:** all four (Coinbase, Kraken, Gemini, Binance.US); **super switches each one on
  for live trading** (in Services), and people choose among those switched on.
- **Caps:** per person, **$150 by default** when none is set. An admin sets a person's cap, and
  a **ceiling** it can't go above; a person with the `live.cap` permission can change their own
  cap up to that ceiling. No maximum built into the code (the owner's choice).
- **Unattended within caps:** once live trading is switched on, bots place orders by themselves
  within their caps and limits. No per-order approval.
- **Keys:** each person's own trading keys, plus **shared** trading keys for those with the
  permission to make and use them.
- **Going live:** install-wide readiness is enough (any bot's 14 clean days, a recent drill,
  the self-check). A new live bot doesn't need its own paper run first.
- **Who:** a new permission given by admins on purpose (in no preset), and 2FA required.
- **Orders:** both kinds, chosen per bot: **limit with price protection** (default) or
  **market**.
- **Real transfers** (from your own wallets): planned with the owner at the end of phase 4
  (13e), not built in it.

## Rules for the whole phase
- **Never a key that can withdraw or transfer** (hard rule #2). A trading key may only read and
  trade. Each exchange's key is checked in the strongest way that exchange allows, and refused
  if it can withdraw; where an exchange can't tell us, the person must confirm it and the
  guide shows exactly which boxes to leave unticked. Every key is re-checked before trading.
- **Lock keys to this server's address** where the exchange allows it (recommended in every
  guide, which shows how to find the address the exchange will see). If your home address changes, the
  exchange refuses the key and bots pause with a clear message.
- **Order calls only, never withdrawals.** Each exchange client lists the exact paths it may
  call for trading (`TRADE_ENDPOINTS`, next to `READ_ENDPOINTS`); a test refuses anything that
  moves funds off the exchange. No exchange SDKs: plain HTTPS, signed like phase 2.
- **Caps are checked in code before every order**, under the database lock, against what that
  person's live bots already hold and have waiting. An order that would go over is cut down
  or refused, never "fixed later".
- **Nothing stays open if the server dies:** orders are placed so they can't linger
  (immediate-or-cancel, or a short expiry where the exchange supports it), so a crash never
  leaves a forgotten order on the book.
- **The kill switch reaches the exchange:** tripping it cancels every live bot's open orders on
  the exchange too, and works from the command line without the web server.
- **Real trades are real for taxes:** every fill lands in the trade log (marked as a bot's), so
  tax exports include it. Paper bots stay out of it, as before.
- **Live trading switched on needs readiness `live_allowed`** (green on the real clock) and is
  checked again before every order; the test clock can never allow it.
- Network calls never hold the database lock; every exchange call has a time limit and a local
  fake for tests.

## 13a: trading keys, switches, permissions, caps
- **Live trading switches** in Services (super): one per exchange, all off at first.
- **Trading keys:** added by a person, encrypted like connections, shown masked; *personal*
  (only the owner's live bots can use it; admins can delete it) or *shared* (made and used only
  by people with `live.keys.shared`). A key is checked when added and before trading:
  can trade, can't withdraw, and whether it's address-locked.
- **Permissions:** `live.trade` (run live bots with your own keys), `live.keys.shared` (make
  and use shared trading keys), `live.cap` (change your own cap, up to your ceiling); admins
  set caps and ceilings in Users. All in no preset: given on purpose. Live actions need 2FA
  turned on (and a 2FA code to raise a cap).
- **Caps:** each person's cap (default $150) and ceiling, in USD (converted for other
  currencies at the live price); shown in Settings and in Users; every change audited.

## 13b: placing orders
For each switched-on exchange: place a limit order (price protection: at most N % worse than
the price the bot saw, default 1 %) or a market order, check it, cancel it; exchange minimums
and step sizes respected. Built against each exchange's current documentation (checked when
built, dated in the wiki), tested against local fakes that verify signatures, and on the
exchange's own test environment where one exists.

## 13c: live bots
The same engine, plans and risk limits as paper bots, with a real account behind it. A live bot
belongs to its person and uses one of their trading keys (or a shared one). Decisions as on
paper; orders sent to the exchange; fills read back and reconciled with the exchange's own
record (a mismatch pauses the bot). Caps and limits checked before every order; the kill switch,
loss limits and stale prices stop it and cancel its orders on the exchange.

## 13d: safety in practice
- A **first tiny order** for each new key (the smallest the exchange allows), filled and
  read back, before a live bot may trade with it.
- **Drills** on live bots (real cancels); what happens when the exchange is down, the key is
  revoked, the address changes, the server restarts mid-order; each case tested.
- Notifications for every live fill, cut order, pause and failure (Discord with the usual
  detail switches).

## 13e: review, transfers, release
Phase 4 review (security and quality, like phases 1 and 3), the **real transfers plan** with
the owner (the spec's rules: allow-listed addresses, network confirmation, a small test transfer
first, approved on your own wallet or hardware wallet, the app never holding a key that can
sign), then **v1.3.0**.

## Read the results with care
- At entry-level fees (0.6–1.2 % a trade) a small bot is unlikely to beat buying and holding;
  phase 4 is for running your own plan safely, not for making money.
- Every live sale is a taxable event in the US; the trade log keeps them for your tax tool.
- Caps limit what bots may put in, not what the market does to it: $150 in a coin can still
  fall a lot. The loss limits and kill switch are there for that.

## Not in phase 4
Withdrawals or keys that can withdraw, real transfers (planned in 13e for later), leverage,
margin, futures, shorting, and lending or staking.
