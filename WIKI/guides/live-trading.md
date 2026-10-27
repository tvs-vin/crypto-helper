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
