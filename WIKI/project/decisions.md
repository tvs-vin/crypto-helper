---
title: Decisions
---

# Decisions

Answers from the owner at project start:

1. **Funds:** support both exchanges and self-custody wallets; everything should be customizable.
2. **Experience:** comfortable with Python. Wants good documentation in `WIKI/`, published with GitHub Pages.
3. **First bot job:** track and alert (not automated buying or active trading).
4. **Location:** US-based. Keep a trade log (timestamp, pair, side, quantity, price, fee) for tax reporting, and prefer US-available exchanges.

## Milestone 3 decisions
- **2FA methods:** TOTP from any free authenticator app, plus recovery codes. All offline;
  nothing to pay for or host. SMS, email and push were ruled out (cost money, need a
  provider, or are weak against SIM swaps).
- **Encrypt 2FA secrets now** rather than in phase 2.
- **Alembic migrations** from milestone 3 on, so data survives upgrades.
- **Lost phone:** recovery codes for users, and `crypto-helper account <name> 2fa reset` on
  the VM (the only recovery path for `super`).
- **One CLI**, `crypto-helper`, with noun-first commands. Passwords are prompted for or
  piped in, never passed as arguments.
- **Installable service** like NetBird (systemd + CLI): milestone 3b.
- **Wiki** split into guides / reference / project / tools sections. `tools/` is only for
  testing tools.

## Milestone 3b decisions
- **NetBird-style install:** `install.sh` + `crypto-helper service …`; code in `/opt`, config
  and key in `/etc`, data in `/var/lib`, dedicated no-login service user.
- **Updates follow a git branch** and roll back code and database automatically on failure.
- **Daily automatic backups** (14 kept); the key is deliberately not in them.
- **Setup token is not written to the journal** under systemd (the spec said "print to the
  console"; the journal keeps it for weeks). `crypto-helper setup token` shows it instead.
- **Binding:** loopback by default; a private-network address such as the NetBird IP needs
  `BOT_ALLOW_REMOTE_BIND=true`; every-interface binds are refused outright.
- **Root drops to the service user** for account and database commands.

## Milestone 4 decisions
- **Networks are enforced** in simulated transfers, like reality: different networks need a
  bridge (refused); a coin must exist on the destination's network (BTC on Ethereum is WBTC).
- **Deleting a wallet with coins** is refused, with two ways forward: move everything
  elsewhere first (all or nothing), or force it by typing the exact wallet name. Archiving is
  offered as the safe alternative.
- **Display:** a nickname is the wallet's largest title, then its name, then tags (smaller).
  The milestone 6 UI follows this order.
- **Two colors** per wallet: the main one picked or derived from the name; the second
  picked or derived by a scheme (analogous, complementary, triadic, shade).
- **Tags:** up to 20 user tags, plus built-in read-only tags (`kind:`, `network:`,
  `provider:`, `coin:`, `address:`, `status:`).
- **Wallet order is personal** (each user arranges their own list); colors, tags and archive
  are shared wallet properties.
- **Seed phrase / private key guard** on every free-text field.

## Milestone 5 decisions
- **Price history:** a point every 10 minutes for the last day, then compacted into hourly
  open/high/low/close candles kept forever; USD only by default. Every one of those values is
  adjustable (`prices.manage`).
- **Extra coins** can be added by CoinGecko id, with checks: the coin must exist, built-in
  symbols are protected, and shared symbols (common with scams) need confirming.
- **New permission `prices.manage`**, included in the admin preset.
- **Wallet values** are only shown to people who can see prices (the spec's permission split).
- **No float:** CoinGecko's numbers are parsed straight into `Decimal`.

## Milestone 6 decisions
- **Look:** modelled on the SaaSLauncher theme's design language (near-black `#0C0C13`, violet
  `#7545FC`, hairline indigo borders, Inter + Mona Sans, 6px corners, edge glows used
  sparingly), deliberately avoiding the generic "AI" look.
- **Desktop:** windows with both floating (snap to edges and corners, Tile) and automatic tiling
  (main + stack or grid), switchable and remembered per user.
- **Sign-in** on the same page: a box over the desktop; afterwards the saved layout returns.
- **Themes:** Dark, Light, Terminal and a Template; users upload their own `.ctheme` (JSON,
  data only); uploads are private and admins can publish one for everyone.
- **NetBird access:** listen on `127.0.0.1` and the NetBird address, and refuse clients outside
  `127.0.0.0/8` and `100.64.0.0/16`.
- **Embeds:** a separate embed-only service on its own configurable port and address(es); every
  item toggled individually (amounts and values start off); off until enabled.
