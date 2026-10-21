---
title: Backtester
---

# Backtester

Try a plan on years of real past prices, and see how it compares with simply buying and holding
the same coins with the same money. **Windows → Backtester** (needs `prices.view`).

Nothing here touches your wallets or any money: it's arithmetic on past prices.

## 1. Pick a plan
| Plan | What it does |
|---|---|
| Regular buys (DCA) | Put in a fixed amount on a schedule, split between coins, whatever the price |
| Rebalancing | Keep a set split (e.g. BTC 60 %, ETH 40 %, the rest in cash): every month, quarter or year, or when a coin drifts more than N points, sell some of what grew and buy what shrank |
| Buy the dip | Keep the money in cash; buy a set amount when the coin is N % below its high of the last D days (once per drop; again after it recovers half way) |
| Trend | Hold the coin while it closes above its average of the last N days (20, 50, 100, 200); sell into cash when it closes below |

## 2. Fill it in
- **Coins and shares** (one coin for Buy the dip and Trend). Only coins with daily prices in the
  chosen currency are offered: USD for 16 of the 18 built-in coins by itself; other currencies
  after importing them ([Past prices]({{ site.baseurl }}/guides/prices-and-portfolio#past-prices-before-the-install)).
- **Dates**: or 1y / 3y / 5y / Max. Trend and Buy the dip need N days of prices *before* the
  start (for the average or the high); the app says the earliest start that works.
- **Starting money**, and **Then add** an amount every week or month (or nothing).
- **Fees like** an exchange (or Custom), and **Slippage**.

## 3. Run it
**Run backtest**. You get:
- **This plan** and **Buy and hold** side by side (the better ending has a green border): final
  value, profit and return, the **yearly rate** (money-weighted: what yearly rate would turn the
  money as you put it in into the final value), the **worst drop** (the biggest fall from a
  peak, not counting money you added), fees and slippage paid, number of trades, and for some
  plans how often it was in the market and the cash left.
- A chart: the plan (solid) and buy and hold (dashed). Hover for the values on any day.
- The trades (the first 100 on screen; **Download trades (CSV)** for all).

**Save** a run with a name to keep it. Under **Saved runs**, tick two or more and **Compare
selected** for a side-by-side table; **Open** shows a saved run again; you keep up to 50.

## How it's worked out (so it can't flatter a plan)
- **No looking ahead.** Each day's decision uses that day's closing price (and earlier ones); the
  order is filled at the **next day's opening price**.
- **Fees and slippage on every trade**, the plan's and buy and hold's alike. A buy pays the open
  price plus slippage, and the fee on top; a sale gets the open price minus slippage, less the
  fee.
- **Buy and hold** gets the same money on the same days, puts it straight into the same coins
  (by their shares, ignoring any cash share) and never sells.
- Daily prices are Coinbase's (open, high, low, close per day). Days missing for any of the coins
  are skipped for all of them.

Fee presets are entry-tier fees for market orders, checked on 2026-10-21:

| Preset | Fee | Source |
|---|---|---|
| Coinbase Advanced | 0.90 % | Reports for US accounts (Coinbase's own page couldn't be read; another report says 0.60 %: the higher one, to stay cautious) |
| Kraken Pro | 0.80 % | Kraken's fee schedule, $0+ tier |
| Gemini ActiveTrader | 1.20 % | Gemini's schedule of 2026-09-01, $0+ tier |
| Binance.US | 0.02 % | Binance.US, from 2026-04-22, all users |

Your own fees depend on your tier: the exchange's order preview shows them. Use **Custom** to try
yours.

## Read the results with care
- **Past prices don't predict future ones.** A plan that did well over these years may not again.
- **Taxes aren't included.** Plans that sell often (Trend, Rebalancing) create taxable gains each
  time; buy and hold doesn't until you sell.
- Small differences (a percent or two) are noise; look for big, consistent ones across several
  date ranges and coins.
