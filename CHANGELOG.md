# Changelog

Each release, newest first. Versions follow `MAJOR.MINOR.PATCH`: a database migration or a
change you have to act on bumps MINOR at least; fixes only bump PATCH. Install a release with
`sudo crypto-helper update` (it backs up first and rolls back by itself if the new version
fails). Details of every part: the [wiki](WIKI/index.md) (or **Help** in the app).

## 1.3.0 (2026-10-28): phase 4, live trading, small and capped

Bots can now trade **real money**, within limits you set: trade-only keys (never withdraw), a
cap per person ($150 unless an admin sets another), every paper-trading safety rule, and live
trading only once **Ready for live trading?** is green. Nothing can move coins off an exchange
(no withdraw keys, no withdraw code).

### Trading keys and caps (milestone 13a)
- **Live trading** window: your cap and your trading keys. Each key is checked with the
  exchange before it's saved; one that can withdraw is refused (and deleted if it gains the
  right later). Personal keys, or shared ones for those allowed.
- Super switches live trading on per exchange (Services); anyone managing services, or
  `crypto-helper live off`, switches it off.
- Admins set caps and ceilings (Users); with `live.cap` people change their own up to the
  ceiling. Raising needs a 2FA code.

### Placing orders (milestone 13b)
- Coinbase, Kraken, Gemini and Binance.US: every order immediate-or-cancel (nothing left
  waiting), price-protected, rounded to the exchange's steps, with Crypto Helper's own id so a
  lost answer is looked up, never resent. **Check an order (no trade)** per key.

### Live bots (milestone 13c)
- **Paper trading** is now **Bots**: paper and **LIVE** bots side by side, same plans, limits
  and kill switch. Before every real order: the kill switch, readiness, the exchange switch,
  the key, permissions and your cap; anything missing pauses the bot with the reason. Fills
  come from the exchange's record; balances are compared hourly.

### Safety in practice (milestone 13d)
- A **first tiny order** per key (at most $25, confirmed with a 2FA code) before bots use it.
- Every failure case handled and tested: exchange unreachable, answers lost, keys refused,
  restarts mid-order, day-old orders.

### Review and release (milestone 13e)
- Phase 4 review: 6 findings fixed (see `WIKI/project/phase-4-review.md`), including deleting
  an account that had a live bot, and the first tiny order being saved before it's sent.
- Real transfers planned (see `WIKI/project/decisions.md`): built next.

### Upgrading from 1.2.0
`sudo crypto-helper update`: migrations 0020-0021 run by themselves. **New permissions**
`live.trade`, `live.keys.shared`, `live.cap` are in no preset: give them in Users on purpose.
Live trading stays off until super switches an exchange on in Services, and needs 2FA.

## 1.2.0 (2026-10-22): end of phase 3, plans tested on paper

The app now **acts on prices, with paper money only**: test plans on years of real prices, run
them live with made-up money, with risk limits and a kill switch, and check whether you're ready
for live trading. Still nothing can place a real order or move real coins (no order endpoint
exists anywhere).

### Onboarding and smarter alerts (milestone 12a)
- First-time setup walks `super` through the server (2FA, key backup, where it listens and who
  may connect, services, data settings, inviting people); every account gets a walkthrough and
  a **Getting started** checklist. Admins can require a new password or 2FA per account.
- Changing where it listens from the browser can't lock you out: the old settings come back by
  themselves unless the restarted server is reached within 2 minutes.
- **Alerts** window: portfolio value, wallet changes, allocation drift and trend signals, on
  top of price alerts. What Discord may show about your holdings has a switch per detail.
- Daily prices from Coinbase's public data (free, no key).

### Live windows and past prices (milestone 12b)
- Every window shows the newest data without reloading; the launcher follows your permissions
  as they change; admins can open a window on a signed-in account's desktop.
- Import years of past prices from Coinbase onto the charts (Settings → Prices).

### Backtester (milestone 12c)
- DCA, rebalancing, buy the dip and trend, on real past prices, against buy and hold, with fees
  and slippage (exchange presets) and no looking ahead. Save, compare, export trades.

### Paper trading (milestone 12d)
- Run a plan live with made-up money next to a buy-and-hold twin; every order kept; profit
  taken and not taken; CSV.
- Risk limits per bot (largest order, a day's spending, a coin's loss, a day's loss) and a
  **kill switch**: in the app or `sudo crypto-helper bot stop --all`, trips by itself on a bad
  day or stale prices, stays off until someone types `REARM`.

### Readiness, review and uninstall (milestone 12e)
- **Ready for live trading?** checks project rule 10: 14 clean days on paper, a kill switch
  **drill** in the last 90 days, and the **limits self-check** on the installed code.
- `service uninstall --dry-run` lists exactly what would be removed; uninstalling is now
  tested end to end. See the README's **Uninstall** section.
- Phase 3 review: 9 findings fixed (see `WIKI/project/phase-3-review.md`).

### Upgrading from 1.1.0
`sudo crypto-helper update`: migrations 0015-0019 run by themselves. **New permissions**
`bots.view`, `bots.run`, `bots.stop` (in the presets; existing accounts other than `super` don't
get them by themselves: add them in Users). **Pillow 13.0.0** (security fixes for uploaded
pictures). Daily prices start downloading after the update; past prices are imported only if
you ask.

## 1.1.0 (2026-10-19): end of phase 2, real balances read-only

Your real balances come in by themselves, **without anything that can move money**: exchange
keys must be view-only (checked on save and before every sync), and wallets are watched by
public address or xpub. Still no seed phrases or private keys, by design.

### Syncing (milestone 11a)
- Link a wallet to an exchange connection or to addresses; it syncs every 15 minutes (adjustable)
  and on **Sync now**. Last sync, errors and coins the app doesn't track are shown on the card.
- Keys are stored encrypted; you're told after 3 failed syncs in a row, at once if a key was
  revoked or gained trading rights. Synced balances can't be edited by hand.

### Exchanges (milestone 11b)
- Coinbase, Kraken, Gemini and Binance.US, each with a step-by-step guide to a view-only key.
  Keys that can trade or withdraw are refused where the exchange says so.
- Balances include funds on hold and staked coins.

### On-chain wallets (milestone 11c)
- Bitcoin by **xpub/ypub/zpub** (every used receive and change address found, any address type)
  or by addresses; extended private keys refused.
- Ethereum, Base, Arbitrum, Optimism and Polygon by address: the network's coin plus USDC, USDT,
  LINK and SHIB from their official contracts.
- Public data servers by default, or your own node / RPC provider.

### Trade log (milestone 11d)
- Trades imported read-only from each exchange (on Sync now and hourly), kept once each, kept when
  a wallet is deleted. A **Trade log** window with filters.
- CSV export for **TurboTax, CoinLedger, CoinTracker and Koinly** (each tool's official template)
  or a generic CSV; every export is audited; spreadsheet formulas are neutralised.

### Balance history (milestone 11e)
- **Portfolio over time** in Overview (7 days to everything, with the change); a 30-day trend on
  every wallet card and a history view per wallet.
- A snapshot every hour and soon after balances change; detailed for 14 days, then daily,
  forever (adjustable). Never recorded with stale or practice prices.

### Upgrading from 1.0.0
`sudo crypto-helper update`: migrations 0012-0014 run by themselves. New permission
`wallets.connect` (in the admin preset) for adding keys and linking wallets; give it to anyone
else who should. Balance history starts at the update: there's nothing from before. New
dependency: `embit` (Bitcoin xpub maths).

## 1.0.0 (2026-10-17): end of phase 1

The dashboard is complete: track wallets and exchange accounts with paper balances, see prices
and what everything is worth, practise transfers, and get notified. **No real funds, no seed
phrases or private keys, no exchange keys** (by design; see the
[security model](WIKI/reference/security.md)).

### Accounts and security (milestones 1-3)
- Setup token for the first `super` account; argon2id passwords; lockout after 5 failures;
  sessions with CSRF protection and strict security headers.
- Users with permissions and presets; nobody can grant what they don't hold; a full,
  append-only audit log.
- Two-factor login (authenticator codes, QR code, 10 recovery codes); secrets encrypted at rest.
- Database migrations; the `crypto-helper` command (noun first, asks for sudo when needed).

### Running it (milestone 3b)
- Installs as a sandboxed systemd service like NetBird (`install.sh`); daily backups;
  `crypto-helper update` with automatic rollback; `crypto-helper doctor`.
- Listens on `127.0.0.1` only unless told otherwise (NetBird/Tailscale/SSH tunnel); never
  `0.0.0.0`; client networks allow-listed.

### Wallets, prices, alerts (milestones 4, 5, 9d)
- Wallets (exchange, on-chain, paper) with exact amounts; simulated transfers that follow real
  network rules; a guard that refuses anything that looks like a recovery phrase or key.
- Prices from CoinGecko (one shared, cached snapshot), portfolio value in 6 currencies, price
  history with compaction, extra coins with a look-alike check, practice prices.
- Price alerts: above, below, or a 24-hour move; fire once, re-arm after crossing back; never on
  stale or practice prices.

### The web desktop (milestones 6-8, 10a)
- A desktop in the browser: floating and tiled windows, several windows per app, themes
  (`.ctheme`, bundles with wallpapers and icons), wallpapers (pictures, animations, video,
  re-encoded on the server), display scale.
- Windows: Wallets, Overview with charts and price alerts, Transfers, Audit log, Users, App
  manager, Services, Console, Terminal, Notifications, Help, Settings.
- Embeds: read-only views of your portfolio or prices for Discord and websites, from a separate
  server with per-item switches.
- Apps on top of permissions (the App manager); install-wide feature switches; the root agent
  for switching services from the browser; Console (fixed commands) and Terminal (2FA, password
  and code to open), both off by default.
- Guided wallet setup for hardware, phone, desktop and exchange wallets.
- Help: the whole wiki inside the app, with search and a "?" on every window.

### Notifications (milestone 9)
- In the app, live; on Discord through your own webhook (stored encrypted); quiet hours.
- Automatic: security events (new device, password and 2FA changes, lockouts, recovery codes,
  a Terminal opened) and system health (backups, updates, crashes, services, disk, prices,
  self-test).
- Admins can send one to a person or to everyone (`notifications.send`).

### Quality (milestone 10)
- [Phase 1 review](WIKI/project/phase-1-review.md): 9 findings fixed, among them embed links
  in the server log, the setup token in non-terminal output, 2FA enrolment without the
  password, and database locks held during price fetches. Checks that now run with every test run: every route needs a session, every change
  is audited, no secret reaches the logs.
- Exact, pinned dependency versions (`requirements.txt`), used by installs and updates.
- CI on every push: lint, about 900 unit tests, the window-maths tests and the end-to-end
  tester. Browser tests (Playwright) run before each release.
- `README.md`, `.env.example` (every setting, kept in step by a test).

### Upgrading from an earlier development build
`sudo crypto-helper update`. Nothing to do by hand. If you made embed links before this
release, press **New link** on them once (Settings → Embeds): older server logs may hold
their addresses.
