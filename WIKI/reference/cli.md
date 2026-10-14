---
title: CLI
---

# CLI: `crypto-helper`

One command for running and administering the server. Commands go **noun first**, then the
thing, then the action: `crypto-helper account super password`.

Account commands work directly on the database, so they must run on the VM with access to
the config and data files. That access is the root of trust: the CLI is the **only** way to
change the `super` account. Every account change is written to the audit log with the actor
`<cli>` and source `local-cli`.

## Accounts
| Command | Does |
|---|---|
| `account list` | Every account: active, 2FA, locked, permissions |
| `account <name> password [--stdin]` | Set a new password. Clears a lockout and signs the account out everywhere. |
| `account <name> unlock` | Clear a login lockout |
| `account <name> 2fa reset` | Turn off 2FA and delete recovery codes (lost phone). Signs the account out. |
| `account <name> sessions revoke` | Sign the account out everywhere |

**Passwords are never command arguments.** On the command line they would be saved in your
shell history and visible to other users in `ps`. You're asked for it twice with hidden typing,
or for scripts it's read from a pipe:
```bash
printf '%s' "$NEW_PASSWORD" | crypto-helper account bob password --stdin
```

## Setup
| Command | Does |
|---|---|
| `setup token` | Show the one-time token for creating `super`. Fails once setup is done. |

## Database
| Command | Does |
|---|---|
| `db migrate` | Apply pending [migrations]({{ site.baseurl }}/reference/database-migrations). The server also does this on start. |
| `db backup [path]` | Consistent copy of the SQLite database, safe while the server runs. File mode 0600, never overwrites. Default: `<state_dir>/backups/bot-<time>.db`. |

A backup includes 2FA secrets encrypted with the [secret key]({{ site.baseurl }}/reference/configuration#secret-key).
Back up the key too, separately from the database.

## Testing
| Command | Does |
|---|---|
| `test [--suite S] [--target spawn\|live] [--config FILE]` | Run the [end-to-end tester]({{ site.baseurl }}/tools/tester) |

## Coming in milestone 3b
`service install|uninstall|start|stop|restart|status|logs`, `update`, `doctor`, and
`install.sh`.

## Which config it uses
1. The file in `$CRYPTO_HELPER_CONFIG`, if set.
2. Otherwise `/etc/crypto-helper/config.env`, if it exists (the installed service).
3. Otherwise `.env` in the current folder, plus environment variables.

See [Configuration]({{ site.baseurl }}/reference/configuration).

## Exit codes
`0` done · `1` refused or failed (message explains why) · `2` command typed wrong · `130` cancelled with Ctrl+C.
