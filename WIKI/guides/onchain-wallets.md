---
title: On-chain wallets
---

# On-chain wallets

Let a self-custody wallet (hardware, phone or desktop) keep its balance up to date by itself.
Crypto Helper only needs **public** information: an address, or for Bitcoin an **extended public
key** (xpub). Neither can spend anything, and the app never asks for a recovery phrase or a
private key.

Supported: **Bitcoin**, and **Ethereum, Base, Arbitrum, Optimism, Polygon** (the network's coin
plus well-known tokens). Other networks keep typed-in balances for now.

## Which to use
| Wallet | Use | Why |
|---|---|---|
| Bitcoin on a hardware or phone wallet (Ledger, Trezor, BlueWallet, Sparrow…) | its **xpub** | These wallets use a new address for every payment and for change. One address misses most of the balance; the xpub lets the app find every address. |
| Bitcoin, one address you reuse (or a paper wallet) | the **address** | Simple. |
| Ethereum and the other EVM networks | the **address** (0x…) | One address holds everything on each network. The same address on several networks: make one wallet per network. |

## An xpub, in plain words
- It's the wallet's **extended public key**: from it, every receiving and change address of
  that wallet account can be worked out. It **can't spend**.
- It is **private information** anyway: anyone with it can see every address, every payment and
  the full balance of that wallet. Crypto Helper stores it encrypted and only ever shows its
  first and last 4 characters.
- It starts with **xpub**, **ypub** or **zpub**. If what you have starts with **xprv**, **yprv**
  or **zprv**, stop: that's the extended *private* key, which can spend everything. The app
  refuses it. If you ever pasted one anywhere, move the funds to a new wallet.

## 1. Find the xpub (Bitcoin)
Wallet apps change their menus; these are the usual places:
- **Ledger Live:** Accounts → the Bitcoin account → **⋯ / wrench (Edit account)** → **Advanced**
  → the long key starting with xpub (Ledger shows "xpub" for every address type).
- **Trezor Suite:** the Bitcoin account → **Details** → **Show public key** (confirm on the
  Trezor) → zpub/xpub.
- **Sparrow:** **Settings** (of the wallet) → **Keystores** → the xpub/zpub field.
- **BlueWallet:** the wallet → **⋯** → **Show wallet XPUB**.
- **Electrum:** **Wallet → Information** → **Master Public Key**.

One xpub covers one account of the wallet. If your wallet has several Bitcoin accounts, add one
Crypto Helper wallet per account.

## 2. Link the wallet
Needs `wallets.connect` and `wallets.edit`.
1. In **Wallets**, create an **On-chain** wallet on the right network (or use an existing one).
   For an address, putting it in the wallet's address field is enough.
2. Its menu → **Sync from…**:
   - **Sync from addresses**: one public address per line (up to 50). Empty means the wallet's
     own address.
   - **Sync from an extended public key** (Bitcoin): paste the xpub. **Address type**:
     *Find out automatically* works for almost everyone (a zpub is Native SegWit, a ypub Nested
     SegWit; a plain xpub is tried as every type and the ones in use are kept). Pick the type if
     you know it, to sync faster.
3. **Save.** It syncs straight away; the card shows how many addresses were found in use.

Like exchange wallets, synced balances can't be typed in or used in practice transfers, and they
update every 15 minutes and with **Sync now**.

## What's counted
- **Bitcoin:** confirmed and unconfirmed (on the way) amounts. With an xpub, the app checks
  receive and change addresses until it finds 20 unused ones in a row (the usual "gap limit").
  A wallet that skipped more than 20 addresses would need those addresses listed by hand.
- **EVM networks:** the network's own coin, plus only these tokens (official contracts, checked
  on-chain and with the issuer): see [Networks]({{ site.baseurl }}/reference/networks#tokens-read-on-chain).
  Anything else sent to your address is ignored: unknown tokens are very often scams.
- **Polygon's coin, POL,** isn't one of the built-in coins, so it shows as *Not tracked* until you
  add it under **Settings → Prices** (CoinGecko id `polygon-ecosystem-token`).

## Privacy, and using your own servers
To read a balance, the app asks a public data server about your addresses: **mempool.space**
for Bitcoin, and **publicnode.com** RPC endpoints for the EVM networks. They learn that someone
at your server's address is interested in those addresses (normal for any wallet app that isn't
running its own node).

To keep that to yourself, point the app at your own servers under **Settings → Connections →
Blockchain data servers**: your own mempool/Esplora (e.g. on an Umbrel or Start9 node), or an
RPC provider account (Alchemy, Infura…). Plain `http://` is allowed only for servers on your own
network.
