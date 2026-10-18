---
title: Wallets and transfers
---

# Wallets and transfers

In phase 1 every balance is typed in by you and every transfer is **simulated**: it moves
numbers between wallets in this app, nothing on a real exchange or blockchain. Every transfer
is labelled "Simulated, no real funds move". Real balances come in phase 2 (read-only).

**In the web app** everything below is in the **Wallets** and **Transfers** windows
([Using the desktop]({{ site.baseurl }}/guides/using-the-desktop#the-windows)): **New wallet**,
and each card's menu for *Set a balance*, *Edit*, *Archive* and *Delete…*. Deleting a wallet
that still holds coins walks you through moving them, archiving, or typing its name to force it.

The examples use `curl` with a logged-in cookie jar (see [Getting started]({{ site.baseurl }}/guides/getting-started)).
Set these once:
```bash
H='X-Requested-With: fetch'; J='content-type: application/json'
```

## 1. Pick the right kind of wallet
| Kind | Use it for | Network |
|---|---|---|
| `exchange` | Coins on Coinbase, Kraken… The exchange holds them. | None: you pick one only when depositing or withdrawing |
| `onchain` | A wallet you control (MetaMask, Ledger, Phantom…) | Exactly one, e.g. `ethereum`, `bitcoin`, `solana` |
| `paper` | Practice money | Optional |

The network matters: a coin only exists on certain networks, and sending it to a different
one usually loses it. See [Networks]({{ site.baseurl }}/reference/networks).

## New to this? Guided setup
**Wallets → Guided setup** walks you through getting a real wallet safely and then adding it
here. Pick one of four kinds:

| Kind | Best for | Who holds the keys |
|---|---|---|
| Hardware wallet | Savings you won't touch often | You (on the device) |
| Phone wallet app | Smaller everyday amounts | You (in the app) |
| Desktop wallet app | More control; pairs with a hardware wallet | You (in the app) |
| Exchange account | Buying and selling | The exchange |

Then, step by step:
1. **Get it safely**: buy hardware from the maker, install apps only from official sources,
   2FA and withdrawal protection on an exchange.
2. **Your recovery phrase** (not for exchanges): on paper, in order; never a photo, never typed
   anywhere, any website included (this one too). Anyone who sees it can take your coins.
3. **Test it**: check the receive address (on the device's screen for hardware), send a small
   amount first, same network on both sides.
4. **Add it here**: a name, the maker or app, and the wallet's **public** receive address and its
   network (exchanges need neither).

You tick each safety point before moving on. Crypto Helper never sees a key or a recovery
phrase: it only tracks the public address, can't move coins, and refuses a phrase or key if
one is pasted into any field. Wallets made this way get the tag `guided`.

**Why the app doesn't create wallets itself:** a key that ever existed on this server (in its
memory, database, backups or logs) could leak, and stolen crypto can't be recovered. Devices and
apps made for keys generate them where they stay. See [Decisions]({{ site.baseurl }}/project/decisions).

## 2. Create a wallet
```bash
curl -b jar -X POST localhost:8000/api/wallets -H "$H" -H "$J" -d '{
  "name": "Ledger ETH",
  "nickname": "🦊 Long-term ETH",
  "kind": "onchain",
  "network": "ethereum",
  "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "provider": "Ledger",
  "tags": ["long-term", "cold storage"]
}'
```
- **name** is the wallet's unique identifier. **nickname** is its big display title (optional).
- **address** is the *public* address from your wallet's Receive screen. It's safe to share.
  It's checked against the network's format, so a typo or a wrong-network address is caught.
- **Never** paste a recovery (seed) phrase or a private key, anywhere. The app refuses
  anything that looks like one, in every field, and doesn't repeat it back. If you ever
  did share one, move the coins to a new wallet.

## 3. Make it yours
| What | How |
|---|---|
| Nickname | `"nickname": "Rainy day fund"`; shown largest, then the name, then tags |
| Main color | `"color_primary": "#3b82f6"`; leave it out for a stable color picked from the name |
| Second color | Either your own (`"color_secondary": "#f59e0b"`) or worked out from the main one: `"color_secondary_mode": "auto"` with `"color_scheme"` = `analogous` (neighbouring hue, the default), `complementary` (opposite), `triadic` (a third of the way round), or `shade` (same hue, lighter or darker) |
| Tags | Up to 20 of your own, like `long-term` or `testing` (1-24 characters) |
| Built-in tags | Added automatically and can't be edited: `kind:…`, `network:…`, `provider:…`, `coin:…` for each coin it holds, `address:yes`, `status:archived`, `status:empty` |
| Your own order | `PUT /api/me/wallet-order` with `{"wallet_ids": [3, 1, 2]}`; only changes your view |
| Archive | `PATCH {"archived": true}` hides it and freezes its balances; history is kept |

Change any of them with `PATCH /api/wallets/<id>`, sending only what changes (`null` clears).
Filter the list by any tag, yours or built-in: `GET /api/wallets?tag=coin:btc`.

## 4. Set balances
```bash
curl -b jar -X PUT localhost:8000/api/wallets/1/holdings/ETH -H "$H" -H "$J" -d '{"amount":"1.25"}'
```
Amounts are **text** (`"1.25"`), up to 18 decimal places, never negative. A JSON number like
`1.25` is refused because computers store those approximately; money must be exact.
Setting `"0"` removes the coin. A coin that can't exist on the wallet's network is refused
(BTC on an Ethereum wallet would really be WBTC, a different token).

## 5. Transfer
```bash
curl -b jar -X POST localhost:8000/api/transfers -H "$H" -H "$J" -d '{
  "from_wallet_id": 2, "to_wallet_id": 1, "symbol": "ETH", "amount": "0.5",
  "note": "practice withdrawal"
}'
```
It's refused, with the reason, when:
- the source doesn't have enough,
- it's the same wallet, or either wallet is archived,
- both wallets have networks and they differ (that needs a bridge in real life),
- the coin doesn't exist on the destination's network.

When an exchange is involved, the answer includes a reminder: for real, pick the matching
network on the exchange's deposit or withdrawal page.

History, newest first: `GET /api/transfers` (`?wallet_id=`, `?limit=`, `?before_id=`).
It keeps the wallet names even after a wallet is renamed or deleted.

## 6. Delete a wallet
- **Empty:** `DELETE /api/wallets/<id>` deletes it.
- **Still holds coins:** refused, with a list of what it holds and three options:
  1. **Move everything first:** `DELETE /api/wallets/<id>?move_to=<other id>`. All or
     nothing: if any coin can't go there (network rules), nothing moves.
  2. **Archive it instead:** `PATCH {"archived": true}`; nothing is lost.
  3. **Delete it anyway:** `DELETE /api/wallets/<id>?force=true&confirm_name=<exact name>`.
     The holdings are gone for good; the audit log records exactly what was destroyed.

## Who can do what
`wallets.view` sees wallets, totals and history. `wallets.edit` creates, edits, deletes and
sets balances. `transfers.create` makes transfers. Your own wallet order needs no permission.
