---
title: Live trading
---

# Live trading (real money)

Phase 4: bots that trade **real money** on an exchange, within a cap. **Windows → Live trading**
(needs `live.trade`, `live.keys.shared` or `live.cap`; an admin gives these on purpose, they're
in no preset). This part (13a) sets up trading keys and caps; placing orders comes next.

What it never does: hold a key that can **withdraw** or move money off the exchange, trade with
margin or borrowed money, or trade at all before **Ready for live trading?** is green (Paper
trading; project rule 10).

## 1. Super switches an exchange on
**Services → Live trading (real money)**: one switch per exchange, all off at first. Only
`super` can switch one on (with two-factor login turned on); anyone who manages services can
switch one off. On the VM: `sudo crypto-helper live off` switches every exchange off at once,
and `sudo crypto-helper live status` shows what's on.

## 2. Your cap
The most your live bots may control at once, in US dollars: **$150** unless an admin sets
another. An admin sets your cap and a **ceiling** (Users → the account's menu → **Live trading
cap…**); with `live.cap` you can change your own cap in the Live trading window, up to that
ceiling. Raising a cap or a ceiling needs a current 2FA code from whoever raises it; lowering
doesn't.

## 3. Make a trading key on the exchange
A trading key may **read and trade, never withdraw**. Lock it to the address of the machine
Crypto Helper runs on: on the VM, `curl -4 https://ifconfig.me` shows the address the exchange
will see. (If your internet provider changes it, the exchange refuses the key and you'll need
to update the allowed address.) Copy the secret straight into Crypto Helper: exchanges show it
once.

### Coinbase
1. Coinbase Developer Platform → **Access → API keys → Create API key**.
2. Portfolio: the one the bots should use. Permissions: **View** and **Trade**. Leave
   **Transfer off** (it can send your coins away).
3. **IP allowlist**: add this machine's address.
4. Copy the key name and private key. Crypto Helper asks Coinbase what the key may do and
   refuses it if it can transfer.

### Kraken
1. Kraken → **Settings → API → Create API key** (spot).
2. Tick **Funds: Query**, **Orders & trades: Query open orders & trades, Query closed orders &
   trades, Create & modify orders, Cancel & close orders**. Leave everything under **Withdraw**,
   **Deposit** and **Earn** unticked.
3. Under advanced settings, set **IP whitelisting** to this machine's address.
4. Kraken can't tell the app what a key may do: Crypto Helper checks that it **can't withdraw**,
   and the trading permission is checked with the first tiny order (13d).

### Gemini
1. Gemini → **Settings → API → Create API key** (an account-level key).
2. Role: **Trader** only (not **Fund Manager**, which moves funds, and not Auditor).
3. Add this machine's address to the key's **trusted IPs**.
4. Crypto Helper asks Gemini for the key's roles and refuses a Fund Manager key.

### Binance.US
1. Binance.US → **API Management → Create API**.
2. Tick **Enable Reading** and **Enable Spot Trading**. Leave **Enable Withdrawals** off.
3. Choose **Restrict access to trusted IPs only** and add this machine's address. (Binance.US
   also turns unused keys back to read-only after 90 days unless they're IP-locked.)
4. If Binance.US answers the app's permission question, Crypto Helper checks it; if not, you
   confirm what you ticked.

### Demo exchange
For tests only (`BOT_SYNC_DEMO=true`): no network, made-up behaviour by the key's first word.

## 4. Add it to Crypto Helper
**Live trading → Add a trading key**: the exchange (only those switched on), a name, the key's
fields, and who may use it:
- **Personal**: only your live bots (needs `live.trade`). Deleted with your account.
- **Shared**: people with `live.keys.shared` can see and use it (they also need `live.trade` to
  trade with it).

Crypto Helper asks the exchange what the key may do before saving it: a key that **can
withdraw** is refused (delete it on the exchange and make a new one), one that **can't trade**
is refused, and where the exchange can't say, you confirm what you ticked. It stores the key
encrypted and shows only its last characters. **Check again** asks the exchange again; a key
that has gained a withdrawal permission is deleted on the spot. Admins can delete anyone's key
they may manage (Users).

You need two-factor login turned on to add a key, and later to trade.

## 5. Check an order without trading
**Check an order (no trade)…** on a key: pick a coin, buy or sell, limit or market and an
amount (buys in US dollars, sells in coins). Crypto Helper builds the real order at today's price
(rounded to that market's steps, at most 1 % worse than the price for a limit order) and asks the
exchange whether it would take it, **without trading**:

| Exchange | How it checks | Also shows |
|---|---|---|
| Coinbase | Order preview | The total and the fee it would charge |
| Kraken | `validate` | That the key may trade (Kraken can't say otherwise) |
| Binance.US | A test order | |
| Gemini | Can't check without trading | (the first tiny order checks it, 13d) |

## How live orders are placed
For the next parts (live bots), every real order:
- is **immediate-or-cancel**: whatever doesn't fill at once is cancelled by the exchange, so
  nothing is ever left waiting on the exchange, even if the server stops;
- has **price protection**: a limit order is at most 1 % (adjustable) worse than the price the
  bot saw; a market order on Gemini (whose API has no market orders) is an immediate-or-cancel
  order 5 % away;
- is rounded **down** to the market's steps and refused if it's below the exchange's minimum;
- carries Crypto Helper's own order id, so if the answer is lost on the way back, the app finds
  the order again by that id instead of sending it twice.

## 6. Live bots
In the **Bots** window: **New bot → Live (real money)**, choose one of your trading keys, the
order kind (limit with price protection, or market) and the protection, then the plan and its
limits as for a paper bot. It needs `bots.run` and `live.trade` with two-factor login, a key
for an exchange that's switched on, US dollars, **Ready for live trading?** green, and starting
money within your cap. Live bots show **LIVE** with an orange border, and only you (and super)
see them.

A live bot decides exactly like a paper bot. Its orders then go to the exchange at the next
check (every minute), each time only if everything still allows it:

| Checked before every order | If not |
|---|---|
| The kill switch isn't tripped | Nothing is sent (the switch pauses every bot) |
| Ready for live trading? is green (the real clock) | The bot pauses with the reason |
| Live trading on the key's exchange is switched on | The bot pauses |
| The key still exists, and you may still trade with it (`live.trade`, 2FA, an active account, a key that can't withdraw) | The bot pauses |
| The bot's limits (largest order, a day's spending) | The order is cut down (noted) |
| **Your cap**: your live bots together are never given more than it; nothing buys while they're over it (if it was lowered) | Scheduled money is cut to fit; buys are cancelled |

Buys leave room for the fee (the plan's fee estimate), so a bot never spends more than its
cash. The fill (coins, value, fee) is the exchange's own record of the order. If the
exchange refuses an order (not enough money in the account, for example), the bot pauses with
the exchange's reason. If an answer is lost on the way back, the order shows **on its way** and
is looked up by Crypto Helper's id a couple of minutes later: never sent twice. Once an hour the
app compares each key's balances with what its live bots hold; if the exchange holds less of a
coin (sold or moved by hand), those bots pause.

The buy-and-hold twin stays on paper, for comparison. Live fills land in the trade log at the
next sync of a wallet linked to that exchange account (read-only key), for your taxes.

The kill switch stops live bots like paper ones. Live orders never wait on the exchange
(immediate-or-cancel), so there's nothing to cancel there: an order already on its way finishes
within seconds and is recorded.

