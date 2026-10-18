# Changelog

Each release, newest first. Versions follow `MAJOR.MINOR.PATCH`: a database migration or a
change you have to act on bumps MINOR at least; fixes only bump PATCH. Install a release with
`sudo crypto-helper update` (it backs up first and rolls back by itself if the new version
fails). Details of every part: the [wiki](WIKI/index.md) (or **Help** in the app).

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
- [Phase 1 review](WIKI/project/phase-1-review.md): 8 findings fixed, among them embed links
  in the server log, 2FA enrolment without the password, and database locks held during price
  fetches. Checks that now run with every test run: every route needs a session, every change
  is audited, no secret reaches the logs.
- Exact, pinned dependency versions (`requirements.txt`), used by installs and updates.
- CI on every push: lint, about 900 unit tests, the window-maths tests and the end-to-end
  tester. Browser tests (Playwright) run before each release.
- `README.md`, `.env.example` (every setting, kept in step by a test).

### Upgrading from an earlier development build
`sudo crypto-helper update`. Nothing to do by hand. If you made embed links before this
release, press **New link** on them once (Settings → Embeds): older server logs may hold
their addresses.
