---
title: Trade log
---

# Trade log

Your trades on connected exchanges, imported read-only, kept here, and exported as CSV for tax
software. Needs `wallets.view` and the Trade log app (**Windows → Trade log**).

## Where trades come from
Each exchange wallet that syncs from a connection ([Exchange connections]({{ site.baseurl }}/guides/exchange-connections))
also imports its trades:
- the first time, as far back as the exchange allows (long histories take a few imports);
- then new ones on every **Sync now**, and every hour in the background.

Each trade is kept once, even if it's imported again. One exchange account should be linked to
one wallet only (the app refuses a second), or its trades would be counted twice.

What's imported per exchange:

| Exchange | Imported | Not imported |
|---|---|---|
| Coinbase | Spot trades (fills) | Corrections and reversals Coinbase adds later; futures |
| Kraken | Spot trades | Margin trades. The key needs **Query closed orders & trades** |
| Gemini | Trades in every market of a coin the app tracks or the account holds | Trades in a coin that's neither tracked nor held any more |
| Binance.US | Same as Gemini | Same as Gemini |

Gemini and Binance.US can only list trades market by market, so the app asks about the markets
of coins it knows about. To include a coin you no longer hold, add it under **Settings →
Prices** first, then **Sync now**.

Deposits, withdrawals, staking rewards and transfers between your own wallets aren't in the trade
log: your tax software can import those directly from the exchange, or you can add them there.

Trades stay in the log when you delete a wallet (tax records need to outlive wallets); the
**Account** column keeps its name.

## Looking at them
Newest first. Filter by account, coin (`BTC` finds BTC-USD and ETH-BTC alike) and dates (UTC).
**Load more** pages further back.

## Exporting for taxes
Pick the format and **Download CSV**. The current filters apply, so for one tax year set **From**
January 1 and **to** December 31. Every download is written in the audit log.

| Format | For | Notes |
|---|---|---|
| Generic CSV | Spreadsheets, or any tool | Every detail: time (UTC, ISO 8601), exchange, account, buy/sell, base and quote coins, exact amount, price, total, fee, trade and order IDs |
| TurboTax | TurboTax's crypto CSV upload | Intuit's universal template: fiat purchases are **Buy**, sales to fiat **Sale**, coin-for-coin **Convert**; market value filled in for fiat trades (fee included for buys, taken off for sales). Amounts are rounded to 8 decimals, as TurboTax requires |
| CoinLedger | CoinLedger's Universal Manual Import | Type **Trade**; the exchange as Platform |
| CoinTracker | CoinTracker's CSV import | For a buy, the coin is Received and the currency paid is Sent |
| Koinly | Koinly's Universal format | Net worth left empty: Koinly values each trade itself |

All times are UTC. Amounts are exact (except TurboTax's 8-decimal rounding). Totals are before
the fee; the fee has its own columns.

Good to know:
- **Check the import** in your tax software (a few trades by hand against the exchange's own
  history), especially the first year. Tax tools change their templates now and then; these
  were checked against each tool's official template on 2026-10-19.
- **Cost basis and gains** are worked out by the tax software from these trades (and your
  deposits). Crypto Helper doesn't calculate taxes and isn't tax advice.
- TurboTax: Intuit's help says to upload the CSV in TurboTax's crypto section. Its availability
  varies by product and year; if the upload isn't offered, use a tax tool that can produce
  TurboTax's files from this CSV.
- Text that a spreadsheet could run as a formula (starting with `=`, `+`, `-`, `@`) is written
  with a leading `'`, so opening the file in Excel is safe.
