---
title: Balance history
---

# Balance history

What your wallets, and your whole portfolio, were worth over time. Needs `wallets.view` and
`prices.view` (values show prices too).

## Where to see it
- **Overview → Portfolio over time**: the combined value of your wallets, with the change over
  the range (for example **+$435.00 (+29.00%) since Sep 19**). Ranges: 7 days, 30 days, 90
  days, 1 year, or everything. Hover the chart for the exact value at any point.
- **Wallets**: each card's footer has a small line showing its last 30 days (green going up,
  red going down). Click it for that wallet's **history**: the chart, the change, and how each
  coin's amount changed between the first and the last day shown.

The charts use the currency you picked (Overview's currency menu, or your default).

## How it's recorded
The server takes a **snapshot** of every wallet in the background, whether or not anyone is
signed in:
- every **hour**,
- and about **5 minutes** after balances change (a sync, or a balance you typed in), so changes
  show up soon without a snapshot for every keystroke.

Each snapshot keeps, per wallet and coin, the amount and what it was worth then in every
currency. Values are fixed when they're recorded: the chart shows what your portfolio was
worth at the time, not today's prices applied to old balances.

Nothing is recorded:
- while prices are **stale** (CoinGecko not answering): it tries again a minute later;
- while **practice prices** are on (made-up values would mix with real ones);
- if there are no wallets.

History starts when this feature is installed: there's nothing from before. A new wallet's
history starts at its first snapshot. A coin the app has no price for is listed under the
chart ("Not in the value") rather than counted as zero.

## How long it's kept
| Age | Kept |
|---|---|
| Up to **14 days** | Every snapshot |
| Older | **One a day** (the day's last), **forever** |

That's about 340 snapshots for the first two weeks, then one a day: a few thousand rows a year
for a handful of wallets.

**Archived** wallets are still recorded; the portfolio chart leaves them out unless you ask the
API for them (`include_archived=true`). **Deleting** a wallet deletes its history too, and it
leaves the portfolio chart (the chart shows the wallets you have now). To keep a wallet's
history, archive it instead.

## Settings
**Settings → Prices → Balance history** (needs `prices.manage`):

| Setting | Default | Range |
|---|---|---|
| Record balance history | on | Also in the Services window |
| A snapshot every (minutes) | 60 | 5 to 1440 |
| Keep every snapshot for (days) | 14 | 1 to 365 |
| Then one a day, kept for (days, 0 = forever) | 0 (forever) | 0 to 36500 |

Changes are written in the audit log (`balances.history_settings`). **Settings → System** shows
how many snapshots there are and when the newest was taken.

## With the API
```bash
curl -b jar 'localhost:8000/api/balance-history/portfolio?days=90&fiat=usd'
curl -b jar 'localhost:8000/api/balance-history/wallets/3?days=30'
```
Every field: [API: Balance history]({{ site.baseurl }}/reference/api#balance-history).
