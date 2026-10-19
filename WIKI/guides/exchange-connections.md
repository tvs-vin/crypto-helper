---
title: Exchange connections
---

# Exchange connections

Let an exchange wallet keep its balances up to date by itself: Crypto Helper reads them from
the exchange with a **read-only API key**. Nothing it holds can trade, withdraw or move funds.

Supported: [Coinbase](#coinbase), [Kraken](#kraken), [Gemini](#gemini),
[Binance.US](#binanceus). (A pretend **Demo exchange** also exists when `BOT_SYNC_DEMO=true`,
for trying the screens out.)

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
Follow your exchange's steps below. Exchanges change their screens now and then, so a label may
differ slightly; the rule doesn't: **view / read permission only**.

**Limiting the key to an IP address** (offered by every one of these exchanges) means the key
only works from your server. It's worth doing if your home internet has a fixed address; if the
address changes, the key stops working until you update it on the exchange (you'll get a "can't
sync" notification). Your server's public address: run `curl -4 ifconfig.me` on the VM.

How the app checks your key:

| Exchange | Checked by the app | You confirm |
|---|---|---|
| Coinbase | View, trade and transfer permissions (Coinbase reports them) | nothing |
| Gemini | The key's role (only Auditor is accepted) | nothing |
| Kraken | Whether it can withdraw (refused if it can) | that it can't trade |
| Binance.US | Its restrictions, if Binance.US answers that question; otherwise only that it can read | that it can't trade or withdraw |

The check runs again before every sync, so a key changed later on the exchange stops syncing.

### Coinbase
1. Sign in to the **Coinbase Developer Platform** (portal.cdp.coinbase.com) with your Coinbase
   account.
2. **API Keys → Secret API Keys → Create API key**. Give it a name ("Crypto Helper").
3. Open **API restrictions**: permissions **View** only (leave **Trade** and **Transfer** off).
   Portfolio: the one you want to see (usually Default). Optionally add your server's IP.
4. Open **Advanced settings** and change the **signature algorithm to ECDSA**. (Ed25519 keys
   don't work with Coinbase's trading API, which is where balances come from; the app tells you
   if you paste one.)
5. **Create API key**. Copy the **API key name** (it looks like
   `organizations/…/apiKeys/…`) and the **private key** (it starts with
   `-----BEGIN EC PRIVATE KEY-----`; copy all of it). They're shown once; **Download API key**
   saves them in a file if you prefer (`name` and `privateKey`).
6. In Crypto Helper: Exchange **Coinbase**, paste the two, **Check and save**.

One Coinbase key sees one portfolio. For another portfolio, make another key and wallet.

### Kraken
1. Sign in to Kraken (kraken.com), then **Settings → Connections & API** (sometimes just
   **API**) → **Create API key** (in the Spot trading API section).
2. Name it ("Crypto Helper"). Permissions: tick **only**
   - Funds: **Query**
   - Orders and trades: **Query closed orders & trades** (for the trade log, milestone 11d)

   Leave everything else off: Deposit, **Withdraw**, Create & modify orders, Cancel/close
   orders, Earn, Export.
3. Optionally restrict it to your server's IP. Leave the nonce window as it is.
4. **Generate key**. Copy the **API key** and the **private key** (shown once).
5. In Crypto Helper: Exchange **Kraken**, paste them, **Check and save**. Kraken can't tell the
   app whether a key may trade, so you'll be asked to confirm what you ticked. If the key can
   withdraw, the app finds out and refuses it.

### Gemini
1. Sign in to Gemini (exchange.gemini.com) → **Settings → API → Create API key**.
2. If asked for a scope, choose your **Primary** account (the key starts with `account-`; a
   `master-` key covers several accounts and isn't what you want here).
3. Role: untick **Trader** (it's ticked by default) and tick **Auditor** only. Gemini doesn't
   let Auditor be combined with other roles, which is exactly what we want.
4. Optionally add your server's IP as a trusted IP. Create it and confirm by email if asked.
5. Copy the **API key** and the **API secret** (the secret is shown once).
6. In Crypto Helper: Exchange **Gemini**, paste them, **Check and save**.

### Binance.US
1. Sign in to Binance.US **in a browser** (the app can't manage keys) → profile menu → **API
   Management**. You need Basic Verification done first.
2. Name the key ("Crypto Helper") and create it; confirm with 2FA and the email Binance.US sends.
3. Under API restrictions keep **Enable Reading** only. Make sure **Enable Spot Trading** and
   **Enable Withdrawals** (and anything else) stay **off**.
4. Optionally choose **Restrict access to trusted IPs only** and add your server's IP.
5. Copy the **API key** and the **secret key** (shown once).
6. In Crypto Helper: Exchange **Binance.US**, paste them, **Check and save**. If Binance.US
   doesn't tell the app what the key may do, you'll be asked to confirm.

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
