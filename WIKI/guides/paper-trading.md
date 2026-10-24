---
title: Paper trading
---

# Paper trading

Run one of the [Backtester]({{ site.baseurl }}/guides/backtester)'s plans **from today on**, with
made-up money at real, live prices, next to a buy-and-hold twin. **Windows → Paper trading**
(needs `bots.view`; making and running bots needs `bots.run`).

Nothing here can reach an exchange: a bot's money and coins live in its own paper account in
this app's database. They never mix with your wallets, their history, alerts or the trade log
(so they can't end up in a tax export).

## 1. Make a bot
**New bot**, or in the Backtester, after a run, **Run it on paper…** (same plan, from today).
- **Name**, then the plan: the Backtester's form without dates (regular buys, rebalancing, buy the
  dip, trend; coins, starting money, then add, fees like, slippage).
- **Limits** (see [below](#risk-limits)).

**Start bot**. Its first decision uses **yesterday's** close (just after midnight UTC, before that
day's prices are in, it waits for them), and the orders fill within a minute.

## 2. How a bot trades
- **Once a day**, after a UTC day closes and its daily prices are in, the bot adds any money
  that was due and decides on that day's close, with exactly the Backtester's code.
- The orders **wait** and are filled at the next check (every minute) at the **live** price: a
  buy pays the price plus slippage and the fee on top; a sale gets the price minus slippage, less
  the fee. Sales go first, so their cash can be used.
- **Buy and hold** (its twin) gets the same money at the same moments, puts it straight into the
  same coins at the same prices and fees, and never sells.
- Nothing is filled while **practice prices** are on, or while prices are **stale** (and if
  they stay stale for 15 minutes, the kill switch trips).

## 3. Read the results
Each bot's card shows its value, profit and return, and its twin's. **Open** for:
- **This bot** and **Buy and hold** side by side (the better one has a green border). **Gains
  taken** is profit from sales (after fees); **gains not taken** is what the coins it holds are
  worth above what it paid.
- A chart: the bot (solid) and buy and hold (dashed), a point every hour.
- Every order: when it was decided, filled or cancelled and why, and any limit that cut it.
  **Download orders (CSV)** for all of them.

**Pause** stops a bot and cancels its waiting orders; **Start** carries on from its next
decision. **Delete bot…** removes it with its orders and chart.

## Risk limits
Each bot has its own, checked in code at every fill and every minute:

| Limit | Default | What happens |
|---|---|---|
| Largest order | none | A bigger buy is cut down to it (noted on the order) |
| Most spent in a day | none | Buys past it that day are cut (noted); the rest stays in cash |
| Pause if a coin is N % below what it paid | 30 % | The bot pauses, its waiting orders are cancelled, and you're told |
| Kill switch if the bot loses N % in a day | 15 % | **Every** bot stops (the kill switch trips) |

## The kill switch
The banner at the top of the window. **Stop all bots** (needs `bots.stop`, which can be given to
more people than `bots.run`), or on the VM:

```bash
sudo crypto-helper bot stop --all --reason "why"
```

It pauses every running bot and cancels every waiting order at once, and stays **tripped** until
someone with `bots.run` **re-arms** it (typing `REARM`, or `sudo crypto-helper bot rearm`).
Re-arming doesn't start anything: each bot is started again by hand. It also trips by itself
when a bot loses its daily limit or prices stay stale for 15 minutes. Every trip and re-arm is
in the audit log (`bots.kill`, `bots.rearm`) and sent to everyone who can see bots, as a
critical notification.

`crypto-helper bot list` and `crypto-helper bot status` show the bots and the switch from the VM
(see [CLI]({{ site.baseurl }}/reference/cli#bot)).

## Ready for live trading?
The **Ready for live trading?** panel in the window (and `crypto-helper bot readiness` on the VM)
checks project rule 10 for you. Live trading (phase 4) isn't built yet; when it is, it can only
be switched on while all three are green:

| Check | Green when |
|---|---|
| A bot ran cleanly on paper for 14 days | A bot has been **running for 14 days in a row** with both loss limits set (a coin's loss and a day's loss), and nothing went wrong |
| The kill switch was tested | A **drill** in the last 90 days stopped every bot, cancelled every waiting order, made the bot check refuse to trade, and was completed by re-arming |
| The loss limits work in this version | The **limits self-check** passed with the risk code the install runs now |

**What starts a bot's 14 days again:** its loss limit pausing it, the kill switch tripping for
real (for any reason), a person pausing it, or the bot check not running for 6 hours (the
service was down, or prices were stale or practice ones). Each bot shows how many clean days it
has, when it would be ready, and why it last started counting again. A drill doesn't count
against it: start the bots again after re-arming and their days carry on.

**Run a drill…** (needs `bots.stop`; or `sudo crypto-helper bot drill`): the kill switch trips
for real, and the app checks on the spot that no bot is still running, no order is still
waiting, and the bot check refuses to trade. **Re-arm** to complete it, then start the bots
again. Drills are in the audit log (`bots.kill`, "drill: …").

**Run the self-check** (needs `bots.run`; or `sudo crypto-helper bot selfcheck`): runs the real
risk code against a throwaway in-memory database, never this install's, and checks six things:
a bigger buy is cut to the largest order; buys past the day's limit are cut; a coin falling past
its limit pauses the bot; the day's loss limit trips the kill switch; a tripped switch cancels
orders and stops the check trading; stale prices stop trading and trip the switch after 15
minutes. An update that changes the risk code needs a new self-check (the panel says so).

**Trying it quickly (development only).** On a development or throwaway test server, start
it with `BOT_READINESS_TEST_CLOCK=true`: a day becomes a minute (and the 6-hour gap 5 minutes),
so a bot is "ready" after 14 minutes. The panel says **TEST CLOCK** and "ready (test)", and
nothing on that clock can ever allow live trading. Your installed server refuses to start with
it, so the real install always needs the real 14 days.

## Notifications
Category **Trading** (Settings → Notifications): orders filled (to the bot's owner; amounts and
values only if your Discord details allow them), a bot paused by its limit, and the kill switch
(to everyone who can see bots).

## Read the results with care
- Paper fills are kinder than real ones: a real order can fill at a worse price than the quote
  plus your slippage when the market moves fast, and a real exchange may refuse tiny orders.
- Past results, paper ones included, don't predict future ones. Taxes aren't included.
- Live trading (phase 4) needs at least two weeks of clean paper running, a tested kill switch
  and enforced loss limits first (project rule 10).
