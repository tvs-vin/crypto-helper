---
title: Exchange connections
---

# Exchange connections

Let an exchange wallet keep its balances up to date by itself: Crypto Helper reads them from
the exchange with a **read-only API key**. Nothing it holds can trade, withdraw or move funds.

> **Coming in milestone 11b:** Coinbase, Kraken, Gemini and Binance.US, each with its own
> step-by-step key guide below. Until then, only the pretend **Demo exchange** exists, and only
> when `BOT_SYNC_DEMO=true` (for trying the screens out).

## What an API key is (and isn't)
- An **API key** lets a program use your exchange account in the ways you allow when you make
  it. Made with **view** permission only, it can read balances and trades, and nothing else.
- It is **not** a wallet's recovery phrase or private key. Crypto Helper still never asks for
  one of those.
- Treat it like a password anyway: anyone who has it can see your balances. Crypto Helper stores
  it encrypted, shows only its last few characters, and never logs it.
- **Never tick trading, withdrawal or transfer permissions.** Crypto Helper refuses a key that
  can do any of that whenever the exchange lets it check, and checks again at every sync.

## 1. Make a view-only key on the exchange
Follow your exchange's guide (milestone 11b). If the exchange offers it, also limit the key to
your server's IP address.

## 2. Add the connection
Needs the `wallets.connect` permission (part of the admin preset).
1. **Settings → Connections → Add a connection.**
2. Choose the exchange, give it a name (e.g. "My Kraken"), and paste the key's parts.
3. **Check and save.** The server asks the exchange what the key may do:
   - **view only:** saved;
   - **can trade or move funds:** refused. Delete that key on the exchange and make a new one;
   - **the exchange can't say:** you're shown which permissions to check on the exchange, and
     confirm before it's saved.
4. The fields are cleared from the screen once it's saved.

## 3. Link a wallet to it
1. In **Wallets**, open an *exchange* wallet's menu (create one first if needed) → **Sync from…**.
2. Pick the connection and **Save**. It syncs straight away.

From then on:
- Balances update by themselves (every 15 minutes by default; change it under **Settings →
  Connections → How often**), and with **Sync now** in the wallet's menu.
- A synced wallet's balances **mirror the real account**: you can't type them in or use the
  wallet in practice transfers. To go back, **Sync from… → Typed in** (the balances stay).
- Coins the app doesn't track are listed under **Not tracked** instead of being added (exchanges
  and wallets often hold tiny amounts of scam or promotional tokens). To track one, add the coin
  under **Settings → Prices**.
- Deleting a synced wallet only deletes its copy here: the coins on the exchange aren't touched.

## When syncing fails
The card shows **sync problem** with the reason, and the balances stay as they were. After 3
failures in a row (or at once if the key was deleted or refused), super and anyone with
`wallets.connect` get a [notification]({{ site.baseurl }}/guides/notifications), and another
when it works again.

If a key ever gains trading or withdrawal permission on the exchange, the next sync refuses it
and stops. Delete that key on the exchange and add a new view-only one.

## Removing a connection
Switch its wallets back to **Typed in** first, then **Remove** it under Settings → Connections.
Also delete the key on the exchange's website: removing it here only forgets it.
