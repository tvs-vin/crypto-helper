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
  item toggled individually (amounts and values start off); off until enabled. By default it
  listens on the same addresses as the web UI (owner's request, 2026-10-16).

## Milestone 8 decisions
- **Scale:** an account default that follows you, overridable per device.
- **Wallpapers:** still images, animated GIF/WebP and short videos (MP4/WebM), every upload
  re-encoded on the server (ffmpeg installed for video). Private, publishable by admins.
- **Theme icons:** both vector path data and PNG.
- **Guided wallet creation:** hardware wallets, phone apps, desktop apps and exchange accounts.

## Milestone 9 decisions
- **Notifications:** in-app centre plus Discord webhooks; `notifications.send` to send by hand;
  automatic security, system-health and price alerts; each person chooses per category and
  channel. Browser/OS pop-ups wait for HTTPS.

## Real transfers (2026-10-28)
Planned at the end of phase 4 (project rule 9: the app never holds a key that can sign).
- **Approval:** by default the app **prepares** the transfer (allow-listed address, network,
  amount, memo) and shows it as text and a QR code; you send it from your own wallet app or
  hardware wallet, and the app watches the blockchain until it arrives. **WalletConnect** as an
  option (your wallet app approves a request; needs a Reown project ID and its relay).
  A hardware wallet in the browser was left out: browsers only allow it over HTTPS.
- **Kinds:** from your own wallets; exchange withdrawals, guided (you make them on the
  exchange's site; the app gives the address and network and watches them arrive); deposits
  to an exchange.
- **Allow-list:** a new address needs a 2FA code and its network confirmed; usable at once
  (no waiting period: owner's choice). The first transfer to any new address is a small test.
- **Who:** a new permission, in no preset, given by admins on purpose; 2FA required.
- **Open:** the owner wants to talk over allowing keys that can withdraw (project rule 2).
  Not decided; nothing is built for it.

## Phase 4 decisions (2026-10-27)
- **Exchanges:** all four can trade live; super switches each on in Services; people choose
  among those switched on.
- **Caps:** per person, $150 by default; admins set each person's cap and a ceiling; `live.cap`
  lets a person change their own within it. No maximum in the code (owner's choice; advised to
  start small).
- **Unattended within caps** once live trading is switched on (no per-order approval).
- **Keys:** each person's own trading keys, plus shared ones for those with the permission.
- **Going live:** install-wide readiness (any bot's 14 clean days, a drill, the self-check) is
  enough; a new live bot needn't have run on paper first (advised: caps and limits carry it).
- **Who:** new permissions given by admins on purpose; 2FA required.
- **Orders:** limit with price protection (default) or market, per bot.
- **Real transfers:** planned at the end of phase 4 (see [Real transfers](#real-transfers-2026-10-28)).
- Plan: [Milestone 13 plan]({{ site.baseurl }}/project/milestone-13).

## The 14 days, and where the gate sits (2026-10-23)
The owner asked for a toggle to skip the 14 days while developing and testing. Shortening the
real requirement was advised against (it's project rule 10, and a switch left on would quietly
skip a safety gate). Chosen instead:
- **The gate moves to switching live trading on.** Phase 4 can be planned and built now; its
  "go live" switch must require `live_allowed` from the readiness report (all three checks
  green, on the real clock). Before, the plan said phase 4 couldn't even be planned until green.
- **A test clock for development and test servers** (`BOT_READINESS_TEST_CLOCK`): a day is a
  minute, so the whole readiness flow can be tried in minutes. The server refuses to start
  with it on an install's own database or as the service account, and anything reported on it
  is marked TEST and never allows live trading. The owner's install always uses the real 14
  days.

## Phase 3 decisions (2026-10-19)
- **Order:** smarter alerts first (the first bot job is still track and alert), then the
  backtester, then paper trading. All of phase 3 is on paper.
- **Strategies:** DCA, rebalancing, buy the dip and trend (moving average), all four.
- **Holdings in Discord:** allowed, configurable in full like embeds: a switch per detail
  (amounts, values, wallet names, percentages), the ones revealing holdings off by default.
  Secrets never go to Discord. (Until now, notifications never carried holdings at all.)
- **Past prices:** Coinbase's public daily candles (free, no key, years of history), stored
  locally. CoinGecko's free plan only reaches back 365 days.
- **Onboarding (added to 12a):** super's first-time setup covers the server (listen
  addresses, allowed networks, services and other backend settings); every account gets the
  walkthrough for using the app; a step-by-step wizard plus a Getting started checklist.
- **2FA:** required for super; for other accounts an admin chooses per account.
- **Passwords:** "must change at first sign-in" is an option when creating an account, and an
  admin can require a new password at next sign-in for any account from the Users window.
- **Live windows (12b, added):** every window shows the newest data (server-pushed change
  signals, across tabs, devices and accounts), the launcher follows permissions live, and admins
  (`users.manage`) can open a window on a signed-in account's desktop (audited, only windows
  that account may use).
- **Importing old data (12b):** past prices from Coinbase onto the charts. (Rebuilding past
  portfolio values and file imports were offered and not chosen.)
- Plan: [Milestone 12 plan]({{ site.baseurl }}/project/milestone-12).

## Phase 2 decisions (2026-10-18)
- **Exchanges:** Coinbase, Kraken, Gemini, Binance.US, with read-only keys only. A key that can
  trade or withdraw is refused wherever the exchange lets the app see it; elsewhere the guide
  and a confirmation cover it.
- **Networks first:** Bitcoin, and Ethereum with Base, Arbitrum, Optimism and Polygon (native
  coin plus a fixed list of well-known tokens; unknown tokens ignored).
- **Bitcoin xpub:** supported for hardware and phone wallets (watch-only); the `embit` library is
  approved for the key maths. xpubs are stored encrypted.
- **Trade log in phase 2:** trade history imported read-only from the exchanges, exported as
  CSV for tax software. Cost basis is left to that software.
- **No SDKs:** exchange and chain access with plain HTTPS; public data sources by default, the
  owner's own endpoints or API keys optional.

## Milestone 10 decisions (2026-10-17)
- **Docs:** readable in the app (a Help window built from the installed `WIKI/`) and on GitHub
  Pages, which needs the repo public or a plan that allows Pages for private repos.
- **Releases:** after the phase 1 review, merge `dev` into `main` and tag v1.0.0. Work carries
  on on `dev`; the live install keeps following `dev`.
- **CI:** lint and unit tests on every push (browser tests stay local).
- **Review:** full: automated checks kept as tests, plus a read-through of every endpoint.

## Generating wallet keys in the app (parked, 2026-10-16)
The owner would like Crypto Helper to generate wallet keys later. Today that's ruled out by the
project's hard rules (never create, ask for or store a seed phrase or private key; the app never
holds a key that can sign). Why the rules exist:
- This server is online and reachable over the network. Anything that ever held a key here (the
  database, backups, logs, memory, a compromised page) could leak it, and crypto theft can't be
  reversed.
- Hardware wallets and good phone wallets generate keys on a device built to keep them, and
  show the seed phrase only on their own screen.

What's being built instead: a guided setup (create the wallet in a hardware or phone wallet,
then track its public address). If key generation is wanted later, it needs an explicit
decision to change the rules first; the least risky shapes to discuss then are **testnet-only
keys for learning** (worthless coins) or generation on a **separate offline device**.
