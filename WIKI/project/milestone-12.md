---
title: Milestone 12 plan
---

# Milestone 12: the track-and-alert engine, backtester and paper trading (phase 3)

Agreed with the owner on 2026-10-19. Phase 3 is the first part that *acts* on prices, so it's
built **entirely on paper**: plans run against real prices with paper balances, and nothing can
place a real order or move real coins (hard rules #1, #2 and #10). Four parts, reported one by
one.

| Part | Status |
|---|---|
| 12a. Onboarding (first-time server setup for super, a walkthrough for every account, account rules) | Done |
| 12a. Smarter alerts: portfolio, wallet changes, allocation drift, trend signals; daily price history from Coinbase | Done |
| 12b. Live windows (every window shows the newest data, the launcher follows permissions, admins open windows remotely) and importing past prices | Done |
| 12c. Backtester: DCA, rebalancing, buy the dip, trend, with fees and slippage | Planned |
| 12d. Paper trading: the same plans live on paper, orders and profit/loss, risk limits, kill switch | Planned |
| 12e. Readiness tracker, phase 3 review, release v1.2.0 | Planned |

Owner's answers: order **alerts, then backtester, then paper trading**; strategies **DCA,
rebalancing, buy the dip and trend (moving average)**, all four; alerts about holdings go **to
Discord, configurable in full like embeds** (a switch per detail, the revealing ones off by
default); past prices from **Coinbase's public price history** (free, no key).

## Rules for the whole phase
- **Paper only.** The trading engine writes to paper accounts in this app's own database. It has
  no code path to an exchange: the exchange clients stay read-only (`READ_ENDPOINTS`, enforced by
  a test), and no order endpoint is added anywhere in this phase.
- **Paper trades never mix with real ones.** They're kept apart from the trade log, so they can
  never end up in a tax export.
- **Fees and slippage in every result** (backtests and paper trades alike), with defaults from
  each exchange's published fee schedule (checked when 12c is built) and adjustable. Slippage:
  the price you actually get is a little worse than the quote.
- **No looking ahead.** A backtest decides on a day's closing price and trades at the *next*
  day's opening price, as a real bot would have to.
- **Stops are easy, starts are deliberate.** The kill switch is one click (and one command on
  the VM), works even when other things fail, and needs a person to re-arm it.
- **Network calls never hold a database lock**, as before; every new data source has a time
  limit and a local fake for tests.
- **Results are not advice.** Every backtest says plainly that past prices don't predict future
  ones.

## 12a: onboarding (added by the owner)
Built first, reported on its own; the alerts half then adds its own onboarding step.
- **First-time setup is super's:** after the setup token and password, super is walked through
  the **server**: two-factor login (required for super), backing up the encryption key, **where
  it listens and who may connect** (listen addresses and allowed networks), services (backups,
  embeds, Console, Terminal) and feature switches, the data settings (price and balance
  history, sync), and inviting people. Server settings that live in the root-owned config go
  through the **agent** (fixed, validated actions); without the agent the page shows the exact
  commands instead.
- **Network changes can't lock you out:** the main server still never listens on every
  interface (`0.0.0.0`); addresses must belong to this machine; after a change the browser has
  to reach the server again and confirm within 2 minutes, or the agent puts the old settings
  back by itself.
- **Every account** (super too) then gets the walkthrough for using it, only with the steps its
  permissions allow: what the app does and never does, a new password if required, 2FA,
  currency, theme and scale, coins to watch, first wallets (guided setup, exchange key,
  address or xpub, paper), notifications and Discord, and a tour of the desktop.
- **Getting started** checklist window afterwards, reopenable from the launcher, ticking items
  off from what's really set up. Existing accounts see it once too, with done steps ticked.
- **Account rules, enforced by the server:**
  - *Must change password:* an option when creating an account, and **Require a new password
    at next sign-in** for any account in the Users window. Until it's changed, that session can
    only change the password.
  - *Requires 2FA:* super always; for others an admin ticks it per account. Until 2FA is on,
    that session can only set it up.
- The setup screen explains the setup token (it proves you own the server), with the command
  to copy.
- Built: the walkthrough reuses the real screens (2FA enrolment, Services, Users, notification
  and price settings) and shrinks to a bar while you work in a window; Getting started is a
  window of its own. The server enforces the rules on every route (a test asks each one). The
  network change is checked by the web app and the agent, confirmed only by the restarted
  server (boot id), and undone by the agent otherwise (also after the agent itself restarts).
  Guide: [First steps]({{ site.baseurl }}/guides/first-steps).

## 12a: smarter alerts
New alert kinds, next to the price alerts from milestone 9:
- **Portfolio value:** above or below an amount, or a move of X% over 24 hours or 7 days (from
  the balance history of 11e).
- **Wallet balance changed:** a synced wallet's coin went up or down (a deposit, a withdrawal,
  a reward), with an optional minimum, so an unexpected withdrawal is noticed quickly.
- **Allocation drift:** set target percentages (e.g. BTC 60%, ETH 40%); you're told when a coin
  is off by more than N points. The same targets are used by the rebalancing strategy later.
- **Trend signals:** a coin crosses its N-day moving average, or falls X% from its recent high
  (the same signals the trend and buy-the-dip strategies use).

**Daily price history:** daily open/high/low/close for each coin with a Coinbase USD market,
downloaded once from Coinbase's public candles (300 days per request, no key) and topped up
daily. Coins without a Coinbase market can't have trend signals or backtests (shown as such).

**Discord, configurable like embeds:** each detail a notification can carry gets a switch per
person: amounts, values, wallet names, percentages. Switches that reveal holdings start **off**,
so by default Discord gets the gist ("Coinbase: BTC balance went down") and the app shows
everything. Secrets never go to Discord, whatever the switches say.

Alerts fire once and re-arm (like price alerts), respect quiet hours, and are never raised from
stale or practice prices.

Built: an Alerts window with every kind (price alerts too); daily prices for 16 of the 18
built-in coins (not TRX or USDC: no Coinbase USD market), downloaded years back once and topped
up hourly; wallet changes raised by the sync engine (not on a wallet's first sync); a new
**Portfolio alerts** notification category; detail markers so the app shows everything and
Discord only what each person allows. Guide: [Alerts]({{ site.baseurl }}/guides/alerts).

## 12b: live windows and past prices (added by the owner)
- **Every window shows the newest data.** The server pushes a "this changed" signal (over the
  live connection notifications already use) to every signed-in session allowed to see it:
  wallets and balances, prices and new price candles, balance snapshots, alerts, trades, users
  and apps. Windows refresh themselves; nothing needs a reload, across tabs, devices and
  accounts.
- **The launcher follows permissions live.** When an admin changes someone's permissions or
  apps, their Windows menu changes at once, and a window they may no longer use closes (with a
  note why).
- **Admins open windows remotely** (`users.manage`): pick a signed-in account and a window; it
  opens on their desktop with a note saying who opened it. Only windows that account may use;
  each one is in the audit log.
- **Import past prices onto the charts:** years of daily prices (and recent hourly ones) from
  Coinbase's public history, per coin or for all, so price charts reach back before the
  install. Imported candles are marked as such and never overwrite recorded ones.
  *Built first (the owner's order):* Settings → Prices → Past prices (per currency, per coin or
  all; progress; Remove imported), Overview ranges up to **5y** and **All** with a note where
  Coinbase's history begins. Guide: [Prices and portfolio]({{ site.baseurl }}/guides/prices-and-portfolio#past-prices-before-the-install).
- Built: every API write is mapped to topics (a test checks every write route), background jobs
  announce theirs, the desktop merges bursts and reloads only windows that show them; access
  changes close what you lost; remote open from the Users window. Guide:
  [Using the desktop]({{ site.baseurl }}/guides/using-the-desktop#always-up-to-date).

## 12c: backtester
Replay a plan over real past prices and compare it with simply buying and holding:
- **DCA:** a fixed amount on a schedule (daily, weekly, monthly), one coin or several.
- **Rebalancing:** target percentages, rebalanced on a calendar or when off by more than N
  points.
- **Buy the dip:** extra buys when the price falls X% from its recent high.
- **Trend:** hold while the price is above its N-day moving average, sit in cash below it.

Settings: dates, starting cash and contributions, fee and slippage. Results: value over time
against buy-and-hold, total put in, final value, return, the worst drop (maximum drawdown),
number of trades and fees paid, the list of trades (CSV). Saved runs can be compared side by
side.

## 12d: paper trading
- A **bot** is one plan with its own paper account (a paper wallet holding cash and coins). It
  runs on its schedule against live prices, with the same fee and slippage model as the
  backtester.
- **Orders and profit/loss:** every simulated order and fill is kept; realised and unrealised
  profit/loss, compared with buy-and-hold over the same time.
- **Risk limits, enforced in code:** largest single order, most spent per day, a per-trade loss
  limit and a daily loss limit. Hitting a limit pauses the bot and tells you.
- **Kill switch:** **Stop all bots** in the app and `crypto-helper bot stop --all` on the VM.
  Also trips by itself on a loss limit or when prices go stale. It stays tripped until a person
  re-arms it, and every trip and re-arm is in the audit log.
- New permissions (in the permission catalog): see bots, run bots, and stop bots (which is
  given to more people than running).
- Notifications for orders, limits and kill switch trips (with the 12a Discord switches).

## 12e: readiness, review, release
- **Readiness tracker:** the rule before any live trading (phase 4), checked by the app: a bot
  has run cleanly on paper for at least 2 weeks, the kill switch has been tested (a recorded
  drill), and loss limits are enforced (by tests). Shown per bot; phase 4 can't be planned
  until it's green.
- **Phase 3 review** (security and quality, like the phase 1 review), then **v1.2.0** (pull
  request into `main`, tag, release).

## Not in phase 3
Real orders of any kind, trade-enabled keys, withdrawals or transfers (phase 4, with
hardware-wallet approval), leverage, margin, futures or shorting, and strategies beyond the four
above (they can follow the same strategy interface later).
