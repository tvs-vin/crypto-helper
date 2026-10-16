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
| Always | `service …` (all actions, including `status` and `logs`), `update`, `embed …` |
| When the service is installed | `account`, `setup`, `db`, `prices`, `config`, `doctor`: they read the root-owned config, key and database |
| Never | `serve` (systemd runs it as the unprivileged service user; it's never elevated), `test`, `version`, `--help` |

- Running from a checkout (not installed), the data commands use your own files and don't ask.
- As root, `account`, `setup` and `db` switch to the `crypto-helper` service user before
  touching anything (see [Service]({{ site.baseurl }}/reference/service#the-service-user)).
- Without sudo installed, it tells you to run the command as root instead.
- This shell access is the root of trust: the CLI is the **only** way to change `super`.
- Every account change is written to the audit log with the actor `<cli>`.
- Everything the CLI creates is private (it runs with umask 077).

## Service
| Command | Does |
|---|---|
| `service install [--port N]` | Create the service user, folders, config, key and units; migrate; start; wait until healthy. Normally run for you by `install.sh`. Never overwrites config or key. |
| `service uninstall [--yes]` | Stop and remove the systemd units. Keeps data, config, key and code. |
| `service uninstall --purge [--yes]` | Also delete data, config, key, code and the service user. Saves a final copy of the database, key and config to `/root/crypto-helper-purged-<time>/`. |
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
| `embed enable [--host H] [--port N] [--public-url URL] [--allow-public]` | Check the settings, write them to the config, start `crypto-helper-embed.service` and wait until it answers. A refused setting changes nothing. |
| `embed disable` | Stop the embed server and set `BOT_EMBED_ENABLED=false`. Every link stops working; embeds themselves are kept. |
| `embed status` | On or off, the unit's state, where it listens and the address links use |

## Accounts
| Command | Does |
|---|---|
| `account list` | Every account: active, 2FA, locked, permissions |
| `account <name> password [--stdin]` | Set a new password. Clears a lockout and signs the account out everywhere. |
| `account <name> unlock` | Clear a login lockout |
| `account <name> 2fa reset` | Turn off 2FA and delete recovery codes (lost phone). Signs the account out. |
| `account <name> sessions revoke` | Sign the account out everywhere |

**Passwords are never command arguments.** On the command line they'd be saved in your shell
history and visible to other users in `ps`. You're asked twice with hidden typing, or for
scripts it's read from a pipe:
```bash
printf '%s' "$NEW_PASSWORD" | sudo crypto-helper account bob password --stdin
```

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
when on, listening beyond this machine, links without a public address).

## Which config it uses
1. The file in `$CRYPTO_HELPER_CONFIG`, if set.
2. Otherwise `/etc/crypto-helper/config.env`, if the service is installed.
3. Otherwise `.env` in the current folder, plus environment variables.

## Exit codes
`0` done · `1` refused or failed (the message says why) · `2` typed wrong ·
`3` (`service status`) not running · `130` cancelled with Ctrl+C.
