---
title: Prices
---

# Prices

## Sources
| `BOT_PRICE_PROVIDER` | What |
|---|---|
| `coingecko` (default) | Real prices from CoinGecko's free API, `/simple/price`. Optional free "Demo" key: `BOT_COINGECKO_API_KEY` (sent as a header, never in the URL or logs). |
| `mock` | Fixed practice prices (the same coin always has the same price). For tests and offline use; labelled "Mock (not real prices)". |

Prices are read straight into `Decimal` (never `float`) and returned as plain text with no
exponents (`0.00000508`, not `5.08e-06`).

## One shared snapshot
- The server fetches **every coin in every currency in one request**, at most once per
  `BOT_PRICE_CACHE_SECONDS` (60). Every user and page reads that same snapshot.
- A failed fetch is also remembered for that time, so an outage doesn't make each page wait
  for a timeout.
- On failure, the last good snapshot is served with `stale: true` and `error`. After a restart
  with no snapshot in memory, the newest recorded history is used (also stale). With neither,
  `503`.
- Responses carry `source`, `as_of`, `attribution`, `stale`, `error`.

## Supported coins
18 built in (BTC, ETH, SOL, ADA, XRP, DOGE, LTC, DOT, AVAX, LINK, USDT, USDC, BNB, BCH, XLM,
ATOM, TRX, SHIB), mapped to CoinGecko ids in `app/prices/catalog.py`. Up to 100 extra coins can
be added by CoinGecko id (`prices.manage`): the id must exist on CoinGecko, built-in symbols
can't be taken, and a symbol shared with other CoinGecko coins needs `"confirm": true`.

## Currencies
`usd` (default) `eur gbp jpy cad aud`. Values round half-up to 2 decimals, JPY to 0.

## History
A background job inside the server (every 30 s it checks if anything is due):
1. **Records** a detailed point for each coin in each history currency every
   `fine_interval_minutes`. Stale prices are never recorded.
2. **Compacts** points older than `fine_keep_hours` into candles of `coarse_interval_minutes`
   (open, high, low, close, number of points), only once a candle's whole time span has
   passed, then deletes those points.
3. **Prunes** recorded candles older than `coarse_keep_days` (0 = never). Imported ones stay
   until removed.

`GET /api/prices/history?symbol=&fiat=&hours=` (hours up to 30 years) returns, oldest first:
imported daily candles (before the first imported hourly one), imported hourly candles (before
the first recorded price), then recorded candles and points. Each row has `source`
(`recorded` or `coinbase`) and, for candles, `interval_minutes`. More than 5000 rows are thinned
evenly over the whole range (the first and last kept).

### Past prices (imported)
Coinbase's public price history (no key), per coin and per currency Coinbase trades it in
(USD for 16 of the 18 built-in coins, EUR 16, GBP 13, CAD and AUD 1 each, JPY none, as of
2026-10-20):
- **daily** candles as far back as Coinbase has them (`daily_candles`, `quote` = the currency;
  USD ones are also downloaded by themselves for trend alerts);
- **hourly** candles for the last 90 days (`price_candles`, `source` = `coinbase`), only for the
  time before this server recorded anything for that coin and currency.

A recorded candle always replaces an imported one in the same hour. `GET /api/prices/import`
(prices.manage) → `{progress: {running, done, total, current}, last: {days, hours, skipped,
errors, by, finished_at}, coverage: {SYMBOL: {currency: {first_day, days, first_hour, hours}}},
hourly_days}`; `POST /api/prices/import {symbols: [...] | null, fiats: [...]}` → `202` (runs on
the server, one at a time: `409` while one runs; audited `prices.import`); `DELETE
/api/prices/import` removes imported prices except the USD daily ones (audited
`prices.import.remove`).

### History settings
`GET` (prices.view) / `PUT` (prices.manage) `/api/prices/history/settings`. Stored in the
database; changes are audited and apply from the next tick.

| Setting | Default | Allowed |
|---|---|---|
| `enabled` | `true` | |
| `fine_interval_minutes` | `10` | 1-60 |
| `fine_keep_hours` | `24` | 1-720 |
| `coarse_interval_minutes` | `60` | 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440 (divide a day evenly), and a multiple of the fine interval |
| `coarse_keep_days` | `0` (forever) | 0-36500 |
| `fiats` | `["usd"]` | any of the 6 currencies |

Size, roughly: with the defaults, 18 coins → about 2,600 points held for the last day and
430 candles a day, a few MB a year. Each extra history currency multiplies that.

## Attribution
CoinGecko's free terms ask for credit; answers include
`"attribution": "Price data by CoinGecko (coingecko.com)"`, which the UI shows.
