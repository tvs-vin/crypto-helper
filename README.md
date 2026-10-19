# Crypto Helper

A self-hosted crypto dashboard that runs on your own Linux machine and is used from a browser:
track wallets and exchange accounts (synced read-only from Coinbase, Kraken, Gemini, Binance.US,
Bitcoin and Ethereum-family addresses), see prices and what everything is worth over time,
keep a trade log for your taxes, practise transfers with paper money, and get notified (in the app or on Discord) about price moves,
security events and the health of the server. It's growing into a track-and-alert bot.

**What it doesn't do (on purpose):** it never holds real funds, never asks for or stores a seed
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
