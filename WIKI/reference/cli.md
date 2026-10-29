---
title: CLI
---

# CLI: `crypto-helper`

One command to install, run and administer the server. Commands go **noun first**, then the
thing, then the action: `crypto-helper account super password`.

## Who can run what
Commands that need root **ask for it themselves**: run them as your normal user and they
re-run through `sudo` with the same arguments, so you only type your password at sudo's
prompt. (Running them as root, or with `sudo` in front, works too.)

| Needs root | Commands |
|---|---|
| Always | `service …` (all actions, including `status` and `logs`), `update`, `embed …`, `agent …` |
| When the service is installed | `account`, `setup`, `db`, `prices`, `config`, `doctor`, `bot`, `live`: they read the root-owned config, key and database |
| Never | `serve` (systemd runs it as the unprivileged service user; it's never elevated), `test`, `version`, `theme`, `--help` |

- Running from a checkout (not installed), the data commands use your own files and don't ask.
- As root, `account`, `setup`, `db`, `bot` and `live` switch to the `crypto-helper` service user before
  touching anything (see [Service]({{ site.baseurl }}/reference/service#the-service-user)).
- Without sudo installed, it tells you to run the command as root instead.
- This shell access is the root of trust: the CLI is the **only** way to change `super`.
- Every account change is written to the audit log with the actor `<cli>`.
- Everything the CLI creates is private (it runs with umask 077).

## Service
| Command | Does |
|---|---|
| `service install [--port N] [--services LIST]` | Create the service user, folders, config, key and units; migrate; start; wait until healthy. Normally run for you by `install.sh`. Never overwrites config or key. Optional services (`backups`, `agent`, `embed`, or `none`): a new install asks, a reinstall keeps what's on. |
| `service uninstall [--yes]` | Stop and remove the systemd units. Keeps data, config, key and code. |
| `service uninstall --purge [--yes]` | Also delete data, config, key, code, the command's link and the service account. Saves a final copy of the database, key and config to `/root/crypto-helper-purged-<time>/`. Deletes the link only if it points into the install and the account only if the installer made it. Stays on purpose: that copy, your own git clone, `git`/`python3-venv`, old journal lines, and `~/.config/crypto-helper/` (a development key from running a checkout). |
| `service uninstall [--purge] --dry-run` | List exactly what uninstalling would remove (each unit, folder, link and account) and what it keeps. Changes nothing. |
| `service start` / `stop` / `restart` | Control it; start and restart wait until it answers |
| `service status` | Running? At boot? Answering? Setup done? Last and next backup |
| `service logs [-f] [-n N]` | The journal for the service and the backup job |

## Updating and checking
| Command | Does |
|---|---|
| `update [--check] [--yes]` | Pull, back up, install, migrate, restart, health-check; **rolls back automatically** on failure. [Guide]({{ site.baseurl }}/guides/updating) |
| `doctor` | About 20 checks with fixes; exit code 1 if any problem. See below. |
| `prices check [--fiat usd]` | Live prices for the built-in coins straight from the price source (bypasses the cache); exit 1 if it fails |
| `version` | Package version, branch and commit |
| `config show` | Effective settings (secrets hidden) |
| `serve` | Run the web server in the foreground. The service runs this; refuses to listen on every interface. |
| `serve --embed` | Run the embed server in the foreground (what `crypto-helper-embed.service` runs). Refuses while embeds are off. |

## Embeds
Walkthrough: [Embeds]({{ site.baseurl }}/guides/embeds).

| Command | Does |
|---|---|
| `embed enable [--host H\|main] [--port N] [--public-url URL] [--allow-public]` | Check the settings, write them to the config, start `crypto-helper-embed.service` and wait until it answers. A refused setting changes nothing. |
| `embed disable` | Stop the embed server and set `BOT_EMBED_ENABLED=false`. Every link stops working; embeds themselves are kept. |
| `embed status` | On or off, the unit's state, where it listens and the address links use |

## Agent
The root helper behind the Services window. Walkthrough: [Services]({{ site.baseurl }}/guides/services).

| Command | Does |
|---|---|
| `agent enable` | Write and start `crypto-helper-agent.service`, wait until it answers |
| `agent disable` | Stop it; the Services window can then only change features |
| `agent status` | Running? And the state of each service as the agent sees it |
| `agent run` | The agent itself (what systemd runs) |
| `agent terminal-bridge --socket …` | One Terminal session (the agent starts it as its own unit; only takes a fresh session socket in the agent's folder) |

## Themes
Make and check theme bundles; no root and no server needed. Format: [Themes]({{ site.baseurl }}/reference/themes#bundles).

| Command | Does |
|---|---|
| `theme check <file or folder>` | Every check the server does, wallpapers converted; exit 1 with the problems |
| `theme pack <folder> [-o file]` | Zip a `.ctheme.d` folder into a `.ctheme` bundle (only allowed files; links refused) |
| `theme unpack <file> [folder]` | Unzip a bundle into a folder to edit (refuses a non-empty folder) |

## Accounts
| Command | Does |
|---|---|
| `account list` | Every account: active, 2FA, locked, permissions |
| `account <name> password [--stdin]` | Set a new password. Clears a lockout and signs the account out everywhere. |
| `account <name> unlock` | Clear a login lockout |
| `account <name> 2fa reset` | Turn off 2FA and delete recovery codes (lost phone). Signs the account out. |
| `account <name> sessions revoke` | Sign the account out everywhere |
| `account <name> new-password on\|off` | Require a new password at the account's next request (not super) |
| `account <name> require-2fa on\|off` | Require two-factor login for the account (super always needs it) |

**Passwords are never command arguments.** On the command line they'd be saved in your shell
history and visible to other users in `ps`. You're asked twice with hidden typing, or for
scripts it's read from a pipe:
```bash
printf '%s' "$NEW_PASSWORD" | sudo crypto-helper account bob password --stdin
```

## Bot
Paper-trading bots and the kill switch. Walkthrough: [Paper trading]({{ site.baseurl }}/guides/paper-trading).

| Command | Does |
|---|---|
| `bot list` | The kill switch (armed or tripped, when, by whom, why) and every bot with its status |
| `bot status` | The kill switch and how many bots are running |
| `bot stop --all [--reason TEXT]` | **The kill switch**: pause every bot and cancel every waiting order, now. Works without the web UI. (`--all` is required: there's no stopping one bot from here.) |
| `bot drill [--reason TEXT]` | A kill switch drill: trips it for real, then checks every bot stopped, every order was cancelled and the bot check refuses to trade; exit 1 if not. Re-arm to complete it. |
| `bot selfcheck` | The limits self-check (the real risk code on a throwaway database); exit 1 if any check fails |
| `bot readiness` | Ready for live trading? The drill, the self-check and each bot's clean days |
| `bot rearm [--yes]` | Re-arm it (asks you to type `REARM` unless `--yes`). Bots stay paused until each is started again. |

Both changes are in the audit log with the actor `<cli>`, and everyone who can see bots gets a
notification.

## Live
Live trading (real money, phase 4). Walkthrough: [Live trading]({{ site.baseurl }}/guides/live-trading).

| Command | Does |
|---|---|
| `live status` | Which exchanges may trade live, how many trading keys, and whether readiness is green |
| `live off` | Switch live trading off on every exchange at once (audited, actor `<cli>`). Works without the web UI; only super can switch an exchange on again (Services) |

## Setup and database
| Command | Does |
|---|---|
| `setup token` | Show the one-time token for creating `super`. Fails once setup is done. |
| `db migrate` | Apply pending [migrations]({{ site.baseurl }}/reference/database-migrations). The service does this on start too. |
| `db backup [path] [--prune N]` | Consistent private copy, safe while running; never overwrites. Default folder: `<state_dir>/backups/`. `--prune N` then keeps the newest N there. [Guide]({{ site.baseurl }}/guides/backups) |

## Testing
| Command | Does |
|---|---|
| `test [--suite S] [--target spawn\|live] [--config FILE]` | The [end-to-end tester]({{ site.baseurl }}/tools/tester) |

## What `doctor` checks
Python version · clock sync (2FA depends on it) · service running, enabled, not crash-looping ·
backup timer · bind address and open ports · web server answers with security headers ·
encryption key valid and private · config and database not readable by others · database
owner · free disk space · schema current · setup done · `super` has 2FA · users low on
recovery codes · locked accounts · leftover setup token · price history still recording ·
age of newest backup · price source answers · systemd sandbox score · embeds (server running
when on, listening beyond this machine, links without a public address) · agent (answering when enabled, socket not open to others) · ffmpeg (video wallpapers).

## Which config it uses
1. The file in `$CRYPTO_HELPER_CONFIG`, if set.
2. Otherwise `/etc/crypto-helper/config.env`, if the service is installed.
3. Otherwise `.env` in the current folder, plus environment variables.

## Exit codes
`0` done · `1` refused or failed (the message says why) · `2` typed wrong ·
`3` (`service status`) not running · `130` cancelled with Ctrl+C.
