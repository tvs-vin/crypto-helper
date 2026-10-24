---
title: Features by milestone
---

# Features by milestone

What each milestone added, in the order it was built. For what's in each *release*, see
`CHANGELOG.md`; for what's planned next, the [Roadmap]({{ site.baseurl }}/project/roadmap).
Every finished milestone adds its section here in the same commit.

## Phase 1 (released as v1.0.0)

### Milestone 1: skeleton and sign-in (2026-10-14)
- The server itself, with settings from environment variables.
- First launch: a one-time setup token creates the `super` account.
- Passwords stored with argon2id; 5 wrong passwords lock an account for 15 minutes.
- Sessions (signed out after 12 hours), sign out, change your password.
- Protection against forged requests, strict security headers, no API docs exposed.
- The permission catalog that every later feature adds to.
- This wiki.

### Milestone 2: users, permissions, audit log (2026-10-14)
- Create, change, deactivate and delete users; reset their passwords.
- Permission presets; nobody can grant a permission they don't hold or manage someone with
  more than they have; `super` can't be changed.
- The audit log: every change, who made it and from where; never a secret.
- The end-to-end tester (`crypto-helper test`).

### Milestone 3: two-factor login and the CLI (2026-10-14)
- Two-factor login with an authenticator app; 10 one-time recovery codes.
- 2FA secrets encrypted at rest with the secret key.
- Database migrations, so upgrades keep your data.
- The `crypto-helper` command (noun first, asks for sudo when needed).

### Milestone 3b: install it as a service (2026-10-14)
- `install.sh`: a sandboxed systemd service with its own system user.
- `crypto-helper service …`, `update` (backs up, rolls back by itself if it fails), `doctor`.
- Daily automatic backups.
- Listens on this machine only unless you choose an address; never on every interface.

### Milestone 4: wallets and practice transfers (2026-10-14)
- Wallets of three kinds: exchange, on-chain (with a network and public address), paper.
- Nicknames, two colors, tags, archive, your own order.
- Exact balances (never rounded), per coin.
- Simulated transfers that follow real network rules (no BTC to an Ethereum address).
- Safe deleting: move the coins first, archive instead, or type the exact name.
- A guard that refuses anything that looks like a recovery phrase or private key.

### Milestone 5: prices and portfolio (2026-10-14)
- Live prices from CoinGecko (one shared snapshot a minute), in 6 currencies.
- What everything is worth: per coin, per wallet, in total.
- Price history recorded in the background (detailed for a day, hourly candles forever).
- Extra coins by CoinGecko id, with a warning about look-alike scam tokens.
- Your preferences: currency, watchlist, columns.

### Milestone 6a: the web desktop (2026-10-14)
- A desktop in the browser: windows you can drag, resize, snap, maximize and tile.
- Sign-in screen, themes (dark, light, terminal), keyboard shortcuts.
- Your layout is saved and comes back when you sign in.
- Reaching it over NetBird (several listen addresses, allowed client networks).

### Milestone 6b: the data windows (2026-10-15)
- Wallets as cards: grouping, filters, sorting, drag to reorder, edit, set balances.
- Overview: portfolio total, prices, 24-hour change, watchlist, price charts.
- Transfers: the practice transfer form and history.
- Audit log: search and paging.

### Milestone 6c: settings, users, themes (2026-10-15)
- Settings: change password, 2FA with a QR code, recovery codes, where you're signed in.
- Upload, preview, share and delete your own themes.
- Users window; system status for `super`.

### Milestone 6d: embeds (2026-10-15)
- Share a read-only view of your portfolio, wallets or prices: a link for Discord (with a
  preview picture) or a frame for a website.
- A separate embed server, off by default, with a switch for every item shown.

### Milestone 7a: apps and the App manager (2026-10-16)
- Each window is an app; choose which apps each account can use, or switch one off for
  everyone (on top of permissions).

### Milestone 7b: services and the agent (2026-10-16)
- The Services window: switch services and features on and off from the browser.
- The agent: a small root helper with a fixed list of jobs.
- Choose services when installing; practice prices; the self-test.
- Several windows of the same app (for example two Overviews), each with its own settings.

### Milestone 7c: Console and Terminal (2026-10-16)
- Console: run a fixed list of `crypto-helper` commands from the browser.
- Terminal: the VM's own login prompt in a window (2FA, password and a code to open; off by
  default; only `super` can grant it).

### Milestone 8a: display scale and wallpapers (2026-10-17)
- Display scale 75-150 %, for your account and per device.
- Wallpapers: built-in ones, and your own pictures, animations and videos (all converted on
  the server).

### Milestones 8b and 8c: theme bundles, guided wallets (2026-10-17)
- Theme bundles: a theme packaged with its wallpapers and icons.
- Guided wallet setup for hardware, phone, desktop and exchange wallets, with the safety
  steps (the app never sees a key).

### Milestone 9a: notifications (2026-10-17)
- The bell, the Notifications window, pop-ups that arrive live.
- Admins can send a notification to one person or everyone.

### Milestone 9b: Discord (2026-10-17)
- Notifications on Discord through your own webhook (stored encrypted); quiet hours.

### Milestone 9c: automatic notifications (2026-10-17)
- Security: new device, password and 2FA changes, lockouts, recovery codes used, a Terminal
  opened.
- System health: backups, updates, crashes, services, disk space, prices, the self-test.

### Milestone 9d: price alerts (2026-10-17)
- Alerts when a coin goes above or below a price or moves a set percent in 24 hours; each
  fires once and re-arms after the price crosses back.

### Milestone 10a: getting started and Help (2026-10-17)
- `README.md` and `.env.example` (every setting).
- Help: this wiki inside the app, with search, and a "?" on every window.

### Milestone 10b: phase 1 review (2026-10-17)
- Checks on every route (sign-in required, changes audited), no secrets in the logs, a size
  limit on requests. Nine findings fixed. See [Phase 1 review]({{ site.baseurl }}/project/phase-1-review).

### Milestone 10c: release (2026-10-17)
- Every dependency pinned to its tested version; tests on GitHub for every change;
  `CHANGELOG.md`; version 1.0.0.

## Phase 2 (released as v1.1.0)
The plan: [Milestone 11]({{ site.baseurl }}/project/milestone-11). Sections are added here as
each part is finished.

### Milestone 11a: sync foundation (2026-10-18)
- Exchange connections: add a read-only API key (stored encrypted, shown masked); keys that can
  trade or move funds are refused; where the exchange can't say, you confirm.
- Link an exchange wallet to a connection (**Sync from…**): its balances update by themselves
  (every 15 minutes, adjustable) and with **Sync now**; coins the app doesn't track are listed,
  not added.
- Synced balances mirror the real account: no hand edits or practice transfers on them.
- A notification when a wallet keeps failing to sync, and when it works again.
- New permission `wallets.connect`. A pretend Demo exchange for trying it out (until the real
  exchanges in 11b).

### Milestone 11b: exchanges (2026-10-18)
- Read-only connections to **Coinbase, Kraken, Gemini and Binance.US**, each with a
  step-by-step guide to making a view-only key.
- Coinbase and Gemini keys are checked with the exchange (trading or transfer rights refused);
  Kraken keys that can withdraw are refused; where an exchange can't say, you confirm.
- Balances include funds on hold and staked coins.

### Milestone 11c: on-chain wallets (2026-10-18)
- Bitcoin wallets sync from an **xpub** (the app finds every receive and change address in use,
  any address type) or from addresses; extended private keys are refused.
- Ethereum, Base, Arbitrum, Optimism and Polygon wallets sync from addresses: the network's coin
  plus USDC, USDT, LINK and SHIB from their official contracts; unknown tokens are ignored.
- Use public data servers (default) or your own node / RPC provider.

### Milestone 11d: trade log (2026-10-19)
- Trades imported read-only from Coinbase, Kraken, Gemini and Binance.US (on Sync now and every
  hour), kept once each, and kept when a wallet is deleted.
- A **Trade log** window: filter by account, coin and dates.
- **CSV export** for TurboTax, CoinLedger, CoinTracker and Koinly (each in its official format),
  or a generic CSV with every detail.

### Milestone 11e: balance history (2026-10-19)
- **Portfolio over time** in Overview: your wallets' combined value, with the change over 7
  days, 30 days, 90 days, a year or everything.
- Every wallet card shows its **last 30 days**; click it for the wallet's history and how each
  coin's amount changed.
- Recorded every hour and soon after balances change, never with stale or practice prices;
  detailed for 14 days, then one a day kept forever (adjustable in Settings → Prices).

## Phase 3 (released as v1.2.0)

### Milestone 12a: onboarding and smarter alerts (2026-10-19)
- **A walkthrough on first sign-in.** super sets up the server: two-factor login (now required
  for super), the key backup, where it listens and who may connect (with an automatic undo if
  the server can't be reached), services, data settings and people. Then every account gets
  to know the app, with only the steps its permissions allow.
- **Getting started** window: what's done and what's left, ticked from what's really set up.
- **Account rules:** "choose your own password at first sign-in" (on by default for new
  accounts) and "two-factor login required", per account, from the Users window or the
  command line. The server allows nothing else until they're met.
- A clearer first-launch screen (what the setup token is, a password strength hint), and the
  network settings in Settings → System.
- **Smarter alerts** in a new **Alerts** window: your portfolio's value (above, below, a big move
  in a day or a week), a synced wallet's balance changing (catch an unexpected withdrawal), drift
  from the split of coins you want, and trend signals (a coin crossing its 20/50/100/200-day
  average, or falling a set percent from its high). Price alerts are there too.
- **Daily prices** for 16 of the 18 built-in coins, years back, from Coinbase's public history.
- **What Discord may show:** amounts, values, wallet names and your portfolio's split are each off
  until you turn them on; the app always shows everything.

### Milestone 12b: live windows and past prices (2026-10-21)
- **Every window is always up to date:** a change anywhere (another tab, another device, another
  person, a sync, new prices or candles) reloads the windows that show it, for everyone allowed
  to see it.
- **Your Windows menu follows your access live;** a window you lose access to closes with a note.
- **Admins can open a window on a signed-in account's desktop** (Users window), with a note
  saying who; audited.
- **Past prices on the charts:** import years of daily prices (and 90 days of hourly ones) from
  Coinbase per currency; Overview's chart reaches back to **All**.
- A check runner with pacman-style progress bars for every test stage.

### Milestone 12c: backtester (2026-10-21)
- A **Backtester** window: try regular buys (DCA), rebalancing, buy the dip or a trend plan on
  years of real past prices, against simply buying and holding with the same money.
- Honest by design: decisions on each day's close, trades at the next day's open, fees and
  slippage on every trade (presets for Coinbase, Kraken, Gemini, Binance.US).
- Results: final value, profit, yearly rate, worst drop, fees, trades (CSV); save runs and
  compare them side by side.

### Milestone 12d: paper trading (2026-10-21)
- A **Paper trading** window: run any Backtester plan from today on with made-up money at live
  prices, next to a buy-and-hold twin that gets the same money. Or **Run it on paper…** straight
  from a Backtester result.
- Every order kept (decided, filled or cancelled, with fees, slippage and why), profit taken and
  not taken, a chart against buy and hold, orders as CSV.
- **Risk limits** per bot: largest order, most spent a day, pause when a coin falls too far,
  and a daily loss limit.
- **Kill switch**: **Stop all bots** in the app or `crypto-helper bot stop --all` on the VM;
  also trips by itself on a bad day or stale prices; stays off until someone types `REARM`.
- New permissions `bots.view`, `bots.run`, `bots.stop`; Trading notifications.

### Milestone 12e: readiness, review and release (2026-10-22)
- **Ready for live trading?** in Paper trading (and `crypto-helper bot readiness`): project
  rule 10 checked by the app. A bot must run cleanly on paper for 14 days with its loss limits
  set, the kill switch must have passed a **drill** in the last 90 days, and the **limits
  self-check** must pass on the code that's running. Live trading can only be switched on
  while all three are green.
- **Kill switch drill** (`Run a drill…`, `crypto-helper bot drill`): trips it for real and checks
  that everything stopped; re-arming completes it.
- **Limits self-check** (`crypto-helper bot selfcheck`): the real risk code tested on a
  throwaway database, safe on the live install.
- **Uninstalling, verified:** `service uninstall --dry-run` lists exactly what would go; the
  purge is tested end to end in a throwaway folder; a README section says what goes and what
  stays.
- **Phase 3 review**: 9 findings fixed, including Pillow 13 for uploaded pictures (with only
  the expected decoder allowed) and a seed-phrase guard on the kill switch's reason. See
  [Phase 3 review]({{ site.baseurl }}/project/phase-3-review).
- The checks run on every core: about 7 minutes instead of 19.
