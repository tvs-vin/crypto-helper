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
- **Slippage and fees**: the real price differs from the quote; both eat profit.

## Security terms
- **2FA (two-factor authentication)**: logging in needs something you know (password) and something you have (your phone).
- **TOTP**: the 6-digit codes an authenticator app shows. They change every 30 seconds and are worked out from a shared secret and the time, with no network needed.
- **Recovery code**: a one-time backup code that stands in for a TOTP code if you lose your phone.
- **Hash**: a one-way fingerprint of a secret. The server can check a password against it but can't turn it back into the password.
- **Encryption at rest**: data is scrambled in the database and can only be read with a key kept somewhere else.
