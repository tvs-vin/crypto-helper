---
title: Configuration
---

# Configuration

Settings come from environment variables starting with `BOT_`, or from an env file (never
committed). See [CLI]({{ site.baseurl }}/reference/cli#which-config-it-uses) for which file
the command-line tool reads.

| Variable | Default | Meaning |
|---|---|---|
| `BOT_DATABASE_URL` | `sqlite:///data/bot.db` | Database location |
| `BOT_STATE_DIR` | `data` | Runtime files: setup token, default backup folder |
| `BOT_SECRET_KEY` | *(unset)* | Encryption key itself. Overrides the key file. |
| `BOT_SECRET_KEY_FILE` | `~/.config/crypto-helper/secret.key` | Key file, created on first start if missing |
| `BOT_COOKIE_SECURE` | `false` | Set `true` whenever it's served over HTTPS |
| `BOT_SESSION_HOURS` | `12` | Session lifetime |
| `BOT_MAX_FAILED_LOGINS` | `5` | Failed password or 2FA attempts before lockout |
| `BOT_LOCKOUT_MINUTES` | `15` | Lockout length |
| `BOT_PRICE_PROVIDER` | `coingecko` | `coingecko` or `mock` |
| `CRYPTO_HELPER_CONFIG` | *(unset)* | Env file for the `crypto-helper` CLI |

## Secret key
Secrets stored in the database (2FA secrets now, exchange API keys in phase 2) are encrypted
with this key using Fernet (from the `cryptography` package).

- If neither `BOT_SECRET_KEY` nor an existing key file is found, the server creates the file
  with mode 0600 inside a 0700 folder.
- The key is never logged or committed.
- **Back it up**, separately from database backups. Anyone holding both the database and the
  key can read the 2FA secrets.
- **If it's lost**, 2FA codes stop working for everyone. [Recovery codes]({{ site.baseurl }}/guides/recovery-codes)
  still work because they're hashed, not encrypted. Then each user turns 2FA off and on again,
  or an admin runs `crypto-helper account <name> 2fa reset`.
- To make a key yourself:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
