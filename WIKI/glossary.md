---
title: Glossary
---

# Glossary

## Crypto terms

- **Exchange account** (Coinbase, Kraken, ...): the exchange holds your coins; this app talks to it with an **API key**.
- **Self-custody wallet** (MetaMask, Ledger, ...): coins live on the blockchain, controlled by a **private key** (seed phrase). Whoever has the key has the coins; transfers are irreversible.
- **Public address**: safe to share; lets anyone *view* a wallet's balance.
- **API key permissions**: read-only (view), trade (buy/sell), withdraw (move coins out). This app never uses withdraw.
- **Network**: sending a coin on the wrong network (Ethereum vs Solana) loses it. Always confirm network and address.
- **Swap/trade vs transfer**: a transfer moves the same coin between wallets; converting one coin to another is a trade with fees and slippage.
- **Paper trading**: simulated trading with fake balances against real prices.
- **Kill switch**: one button (or command) that stops every bot at once and stays off until a person turns it back on.
- **Realized / unrealized gain**: profit from coins already sold, and the paper profit on coins still held (it can vanish before you sell).
- **Slippage and fees**: the real price differs from the quote; both eat profit.

## Price terms
- **Fiat**: government money like USD or EUR.
- **Stablecoin**: a coin meant to stay worth one unit of a fiat currency (USDT, USDC). It can still slip ("depeg").
- **24h change**: how much the price moved over the last 24 hours, in percent.
- **Candle (OHLC)**: one row summarising a time span: the open, high, low and close price. What price charts are drawn from.
- **Stale price**: an older price shown because the price source couldn't be reached. Fine for a rough idea, not for decisions.

## Wallet and network terms
- **Public address**: where coins can be sent to a wallet, like an account number. Safe to share; shown on the wallet's Receive screen.
- **Private key**: the secret that can spend a wallet's coins. Never share it or type it into an app.
- **Recovery (seed) phrase**: 12 or 24 words that recreate all of a wallet's private keys. Same rule: never share it, never type it anywhere but the wallet itself.
- **Bridge**: a separate service that moves a coin's value from one network to another, usually by locking it on one and issuing a copy on the other. Extra fees and risk.
- **Wrapped token**: such a copy, with its own symbol. BTC on Ethereum is WBTC, a different token from BTC.
- **Simulated transfer**: a practice transfer in this app. Only the numbers here change; nothing happens on an exchange or blockchain.

## Security terms
- **2FA (two-factor authentication)**: logging in needs something you know (password) and something you have (your phone).
- **TOTP**: the 6-digit codes an authenticator app shows. They change every 30 seconds and are worked out from a shared secret and the time, with no network needed.
- **Recovery code**: a one-time backup code that stands in for a TOTP code if you lose your phone.
- **Hash**: a one-way fingerprint of a secret. The server can check a password against it but can't turn it back into the password.
- **Encryption at rest**: data is scrambled in the database and can only be read with a key kept somewhere else.
