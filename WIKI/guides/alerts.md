---
title: Alerts
---

# Alerts

Be told when something happens: a price, your portfolio, a wallet, the split of your coins, a
coin's trend. **Windows → Alerts** has them all (needs `prices.view`; alerts about your holdings
also need `wallets.view`). Each person's alerts are their own.

Alerts arrive as [notifications]({{ site.baseurl }}/guides/notifications): in the app, and on
Discord if you tick it for that kind (Settings → Notifications: **Price alerts** for prices and
trends, **Portfolio alerts** for the rest).

## The kinds
| Kind | Fires when | Needs |
|---|---|---|
| Price | a coin goes above or below a price, or moves N % in 24 hours (also in Overview) | `prices.view` |
| Portfolio value | your wallets' total goes above or below an amount, or moves N % in 24 hours or 7 days | `wallets.view`, `prices.view` |
| Wallet balance changes | a synced wallet's balance goes up or down (all changes, only up, or only down; optionally only above a value) | `wallets.view` |
| Drift from targets | a coin's share of your portfolio is off your target by more than N points | `wallets.view`, `prices.view` |
| Trend signal | a coin crosses its N-day average (either way, or only up / down), or falls N % from its N-day high | `prices.view` |

1. **New alert**, pick the kind.
2. Fill in the line (e.g. "When my portfolio goes below 10,000 USD"), **Add alert**.
3. It shows as **watching**; after it fires, **fired** until it re-arms.

## How they behave
- **Once, then re-arm.** An alert fires once, and again only after things are back on the other
  side (a level by 0.5 %, a move or a drop back under 80 % of your threshold, the drift back
  within your points). A **moving-average cross** fires every time the price changes sides
  (the first check only notes the side).
- **Never on made-up or old numbers:** nothing is checked while practice prices are on or the
  prices are stale.
- **Wallet changes** are noticed as the sync applies them (every 15 minutes by default, or Sync
  now). The wallet's first sync isn't news (everything "arrives"), so it starts with the second.
  An unexpected withdrawal says "If you didn't expect this, check the account now."
- **Portfolio moves** compare with [balance history]({{ site.baseurl }}/guides/balance-history):
  they need it to reach back 24 hours or 7 days first.
- **Drift**: targets are percents of your portfolio's value (all non-archived wallets). Targets
  that add up to less than 100 % leave the rest to "other coins" together.
- If you lose a permission an alert needs, it waits silently.
- At most 50 of these alerts each (and 50 price alerts).

## Trend signals and daily prices
Trend signals use **daily prices** the server downloads from Coinbase's public price history (no
account or key; years back the first time, then topped up hourly). They exist for every coin with
a Coinbase USD market: 16 of the 18 built-in coins (not TRX or USDC), and extra coins whose symbol
Coinbase lists. In the trend form, coins without daily prices are greyed out.

- **Moving average:** the average closing price of the last N finished days (today, still
  changing, isn't one of them). Common choices: 20 days (short term), 50, 100, 200 (long term).
  A price crossing above it is often read as a trend turning up; it's a signal, not a forecast.
- **Drop from the high:** the highest price of the last N days (including now) against now.

## What Discord may show
Alerts about your portfolio and wallets can reveal what you own, and anyone in your Discord channel
(and Discord itself) sees what's posted. So in **Settings → Notifications → What Discord may
show**, each detail is off until you turn it on:

| Detail | On | Off |
|---|---|---|
| Coin amounts | "ETH went down by 1 ETH" | "ETH went down" |
| Values of what you hold | "Now 12,400 USD", "(about 300 USD)" | left out |
| Wallet and account names | "Coinbase main: balance changed" | "A synced wallet: balance changed" |
| How your portfolio is split | "BTC 68 % (target 60 %)" | "BTC is above its target" |

The app always shows everything. Prices and trend signals aren't about your holdings and always
show in full.
