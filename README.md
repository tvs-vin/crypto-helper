# Crypto Helper

A self-hosted crypto dashboard that runs on your own Linux machine and is used from a browser:
track wallets and exchange accounts (synced read-only from Coinbase, Kraken, Gemini, Binance.US,
Bitcoin and Ethereum-family addresses), see prices and what everything is worth over time,
keep a trade log for your taxes, practise transfers with paper money, and get notified (in the app or on Discord) about price moves,
portfolio and wallet changes, security events and the health of the server. Try a plan on years
of past prices in the **Backtester**, then run it from today on in the **Bots** window, on paper first and later with real money,
with risk limits, a kill switch and a check of whether you'd be ready for live trading.

**What it doesn't do (on purpose):** it never holds real funds or places a real order, never asks for or stores a seed
phrase or private key, and never accepts an exchange key that can trade or withdraw: exchange
keys are view-only and wallets are watched by public address or xpub. The reasons are in the
[security model](WIKI/reference/security.md) and [decisions](WIKI/project/decisions.md).

## Install

On a Linux machine with systemd, Python 3.12+ and git (Debian/Ubuntu:
`sudo apt install python3 python3-venv git`, plus `ffmpeg` if you want video wallpapers):

```bash
git clone https://github.com/tvs-vin/crypto-helper.git
cd crypto-helper
sudo ./install.sh                     # asks which optional services you want
```

It installs to `/opt/crypto-helper`, runs as its own system user in a systemd sandbox, keeps its
config in `/etc/crypto-helper` and its data in `/var/lib/crypto-helper`, and listens on
`127.0.0.1:8000` only. Then:

1. **Back up the encryption key** (`/etc/crypto-helper/secret.key`) somewhere off the machine.
2. **Create the `super` account:** `sudo crypto-helper setup token`, open the web page, paste
   the token and choose a password.
3. **Turn on two-factor login** (Settings → Account) and save the recovery codes.
4. **Check it:** `sudo crypto-helper doctor`.
5. **Reach it from your computer** with an SSH tunnel, NetBird or Tailscale. Never open the port
   to the internet. See [Remote access](WIKI/guides/remote-access.md).

Full steps: [Install as a service](WIKI/guides/install-as-a-service.md).

## Day to day

| To… | Run |
|---|---|
| See if it's healthy | `sudo crypto-helper service status`, `sudo crypto-helper doctor` |
| Upgrade (backs up first, rolls back by itself if the new version fails) | `sudo crypto-helper update` |
| Back up now (there's also a daily backup) | `sudo crypto-helper db backup` |
| Read the log | `sudo crypto-helper service logs -f` |
| Everything else | `crypto-helper --help` |

Settings: every `BOT_*` setting is listed with its default in [`.env.example`](.env.example);
an installed copy reads them from `/etc/crypto-helper/config.env`
([Configuration](WIKI/reference/configuration.md)).

## Uninstall
See first, change nothing: `--dry-run` lists every file, folder and account it would remove.

```bash
sudo crypto-helper service uninstall --purge --dry-run   # exactly what would go, and what stays
sudo crypto-helper service uninstall                     # remove the service; keep data, config, key, code
sudo crypto-helper service uninstall --purge             # remove everything
```

`--purge` stops and removes the systemd units (and any `systemctl edit` overrides), then deletes
`/var/lib/crypto-helper` (database and backups), `/etc/crypto-helper` (config and key),
`/opt/crypto-helper` (code), the `/usr/local/bin/crypto-helper` link and the `crypto-helper`
account. It only deletes the link if it points into the install, and the account only if the
installer made it.

What stays on purpose:
- **One last copy** of the database, key and config in `/root/crypto-helper-purged-<time>/`
  (root only), in case you change your mind. Delete it when you're sure.
- The folder you ran `install.sh` from (your own git clone), packages it needed (`git`,
  `python3-venv`), and old lines in the system journal (they age out).
- `~/.config/crypto-helper/` for anyone who ran the app from a checkout (a development key; the
  installer never makes it).

Before a purge, consider [exporting your trade log](WIKI/guides/trade-log.md) for taxes.
Verified by `tests/test_uninstall.py` (an install in a throwaway folder, purged, nothing left).

## Documentation

The [wiki](WIKI/index.md) has step-by-step guides, the full reference (API, CLI, settings,
security model) and the project's roadmap and decisions. The same pages are in the app:
**Windows → Help**, or the **?** on any window.

What changed in each release: [CHANGELOG.md](CHANGELOG.md). What each milestone added:
[Features by milestone](WIKI/project/features-by-milestone.md).

## Developing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/pip install -e .
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000   # run
.venv/bin/pytest                          # tests (browser tests: tests/ui, need Playwright)
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/crypto-helper test              # the end-to-end tester, against a throwaway server
```

How the project is run (conventions, rules, current status): [`CLAUDE.md`](CLAUDE.md) and
[Getting started](WIKI/guides/getting-started.md).
