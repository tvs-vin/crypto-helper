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
| `BOT_PRICE_PROVIDER` | `coingecko` | `coingecko` or `mock` ([Prices]({{ site.baseurl }}/reference/prices)) |
| `BOT_COINGECKO_API_KEY` | *(unset)* | Optional free CoinGecko Demo key. Hidden by `config show`, never logged. |
| `BOT_COINGECKO_BASE_URL` | `https://api.coingecko.com/api/v3` | Only change for testing |
| `BOT_PRICE_CACHE_SECONDS` | `60` | How long one price snapshot is shared |
| `BOT_PRICE_TIMEOUT_SECONDS` | `10` | How long to wait for CoinGecko |
| `BOT_PRICE_BACKGROUND` | `true` | Run the price history job inside the server |
| `BOT_NOTIFY_BACKGROUND` | `true` | Send Discord notifications and watch system health from jobs inside the server (tests turn it off) |
| `BOT_HOST` | `127.0.0.1` | Address(es) to listen on, comma-separated (e.g. `127.0.0.1,100.64.39.116`). `0.0.0.0` / `::` are always refused. Addresses that aren't up yet (NetBird at boot) still work. |
| `BOT_ALLOWED_NETWORKS` | `127.0.0.0/8,::1/128` | Client addresses or networks allowed to connect, comma-separated. Everything else gets `403`. |
| `BOT_PORT` | `8000` | Port to listen on |
| `BOT_ALLOW_REMOTE_BIND` | `false` | Allow non-loopback addresses in `BOT_HOST`, e.g. a NetBird IP ([Remote access]({{ site.baseurl }}/guides/remote-access)) |
| `BOT_EMBED_*` | | The embed server: see [Embeds](#embeds) below |
| `BOT_CONSOLE_ENABLED` | `false` | The Console window (switched in Services; the agent refuses while off) |
| `BOT_TERMINAL_ENABLED` | `false` | The Terminal window (same) |
| `BOT_AGENT_SOCKET` | `/run/crypto-helper-agent/agent.sock` | The agent's socket ([Services]({{ site.baseurl }}/guides/services)). Throwaway test servers always get a path of their own. |
| `CRYPTO_HELPER_CONFIG` | *(unset)* | Env file for the `crypto-helper` CLI |
| `CRYPTO_HELPER_ROOT` | `/` | Pretend the filesystem starts here (tests use it to install into a temp folder) |

The installed service reads `/etc/crypto-helper/config.env`, where the paths point at
`/var/lib/crypto-helper` and `/etc/crypto-helper/secret.key`. After editing it:
`sudo crypto-helper service restart`.

## Embeds
The embed server (`crypto-helper serve --embed`, unit `crypto-helper-embed.service`) reads
the same file. `crypto-helper embed enable` sets these for you and checks them before writing.
Walkthrough: [Embeds]({{ site.baseurl }}/guides/embeds).

| Variable | Default | Meaning |
|---|---|---|
| `BOT_EMBED_ENABLED` | `false` | Run the embed server. Off: it refuses to start and every link answers nothing. |
| `BOT_EMBED_HOST` | `main` | `main`: the same address(es) as the web UI (`BOT_HOST`), under its rules (`BOT_ALLOW_REMOTE_BIND`, never `0.0.0.0`). Or its own comma-separated list; anything but this machine then needs `BOT_EMBED_ALLOW_PUBLIC`. Links use the first address other devices can reach (e.g. the NetBird one) unless `BOT_EMBED_PUBLIC_URL` is set. |
| `BOT_EMBED_PORT` | `8001` | Its port. Must differ from `BOT_PORT`. |
| `BOT_EMBED_ALLOW_PUBLIC` | `false` | Allow non-loopback addresses of its own in `BOT_EMBED_HOST` (including `0.0.0.0`). Not needed for `main`. |
| `BOT_EMBED_PUBLIC_URL` | *(unset)* | The address people reach it at, e.g. a tunnel's `https://embed.example.com`. Links and preview images use it. |
| `BOT_EMBED_ALLOWED_NETWORKS` | `*` (anyone) | Client networks allowed to load embeds, like `BOT_ALLOWED_NETWORKS`. |
| `BOT_EMBED_RATE_PER_MINUTE` | `120` | Requests per minute from one address before it gets `429`. |

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
