---
title: Prices and portfolio
---

# Prices and portfolio

Prices come from [CoinGecko](https://www.coingecko.com)'s free service. The server asks
at most once a minute and everyone shares that one answer, so every screen shows the same
numbers. Every answer says where the prices came from and when (`source`, `as_of`).

**In the web app** it's all in the **Overview** window: the total at the top, the price table
(star coins for your watchlist, pick currency and columns, click headers to sort) and a chart
for whichever coin you click.

The examples assume a logged-in cookie jar and `H='X-Requested-With: fetch'; J='content-type: application/json'`.

## See prices
```bash
curl -b jar 'localhost:8000/api/prices'                      # every supported coin, USD
curl -b jar 'localhost:8000/api/prices?symbols=BTC,ETH&fiat=eur'
```
Currencies: USD, EUR, GBP, JPY, CAD, AUD. Coins the app can't price come back in `unpriced`
instead of causing an error.

**If CoinGecko is down**, you get the last good prices with `"stale": true` and the reason
in `error`. If there have never been any prices, the answer is a `503` that says why.
Treat stale prices as "roughly, a while ago".

## See what everything is worth
```bash
curl -b jar 'localhost:8000/api/portfolio'          # in your preferred currency
```
Total, per coin and per wallet. Values are rounded to cents (whole yen for JPY). Needs both
`wallets.view` and `prices.view`. The wallet list can also be sorted by value:
`GET /api/wallets?sort=value`.

## See what it was worth
**Overview → Portfolio over time** charts your portfolio's value, and each wallet card has its
own trend. How it's recorded and kept: [Balance history]({{ site.baseurl }}/guides/balance-history).

## Pick your settings
Your settings are yours alone and need no permission:
```bash
curl -b jar -X PATCH localhost:8000/api/me/preferences -H "$H" -H "$J" \
  -d '{"fiat":"usd","theme":"dark","watchlist":["BTC","ETH","SOL"]}'
```
`PATCH` changes only what you send. Everything you can set is in
[API: Preferences]({{ site.baseurl }}/reference/api#preferences).

## Add a coin that isn't built in
Needs `prices.manage`.
1. Find the coin on coingecko.com. Its id is the end of the page address:
   `coingecko.com/en/coins/`**`pepe`**.
2. Add it:
   ```bash
   curl -b jar -X POST localhost:8000/api/coins -H "$H" -H "$J" -d '{"coingecko_id":"pepe"}'
   ```
3. The app checks CoinGecko has it and uses CoinGecko's name and symbol. If **other coins
   use the same symbol** (scam copies do this a lot), it shows them and stops. Look at the
   coin's page, make sure it's the right one, then send it again with `"confirm": true`.

The 18 built-in coins can't be replaced. Remove an extra coin with
`DELETE /api/coins/<SYMBOL>`; holdings of it simply become unpriced.

## Price history
The server records history in the background, whether or not anyone is logged in:
- a detailed point every **10 minutes**, kept for **24 hours**,
- after that, every hour is compacted into one **candle** (open, high, low, close), kept
  **forever**,
- in **USD** only by default (to keep the database small).

See it: `GET /api/prices/history?symbol=BTC&hours=168`. Change any of those numbers with
`prices.manage`; see [Prices]({{ site.baseurl }}/reference/prices#history-settings).

## Price alerts
Get a [notification]({{ site.baseurl }}/guides/notifications) when a coin's price does
something. Needs `prices.view`.

1. Open **Overview** and scroll to **Price alerts** (under the table and chart). Clicking a
   coin in the table picks it for the form too.
2. Choose the coin, then **goes above**, **goes below** or **moves 24h by**, and type a price
   (in the window's currency) or a percent (0.1 to 1000).
3. **Add alert**. Coins with alerts get a small bell in the table.

How they behave:
- The server checks them whenever prices update (about every minute), whether or not
  anyone's signed in.
- Each one **fires once**, then waits until the price has crossed back by 0.5 % (for a move:
  until the 24-hour move is under 80 % of yours) before it can fire again. A price hovering
  right at your line can't flood you.
- If it's already true when you add it (BTC is above your price right now), it doesn't fire
  straight away: it shows **waits to cross back** and fires the next time it happens.
- States: **watching** (armed), **fired** (with when), **waits to cross back**.
- **Never on made-up or old numbers:** nothing is checked while practice prices are on, or
  while prices are stale because the price source is failing.
- Choose where they arrive (in the app, Discord) under **Settings → Notifications → Price
  alerts**. They say the coin, the price and the 24-hour change: never your holdings.
- Up to 50 each. Delete one with the **×** on its row. They're deleted with the account.

## Check the connection from the VM
```bash
sudo crypto-helper prices check            # live prices straight from CoinGecko
sudo crypto-helper doctor                  # includes "Price source answers" and history checks
```
