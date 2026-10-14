---
title: Decisions
---

# Decisions

Answers from the owner at project start:

1. **Funds:** support both exchanges and self-custody wallets; everything should be customizable.
2. **Experience:** comfortable with Python. Wants good documentation in `WIKI/`, published with GitHub Pages.
3. **First bot job:** track and alert (not automated buying or active trading).
4. **Location:** US-based. Keep a trade log (timestamp, pair, side, quantity, price, fee) for tax reporting, and prefer US-available exchanges.

## Milestone 3 decisions
- **2FA methods:** TOTP from any free authenticator app, plus recovery codes. All offline;
  nothing to pay for or host. SMS, email and push were ruled out (cost money, need a
  provider, or are weak against SIM swaps).
- **Encrypt 2FA secrets now** rather than in phase 2.
- **Alembic migrations** from milestone 3 on, so data survives upgrades.
- **Lost phone:** recovery codes for users, and `crypto-helper account <name> 2fa reset` on
  the VM (the only recovery path for `super`).
- **One CLI**, `crypto-helper`, with noun-first commands. Passwords are prompted for or
  piped in, never passed as arguments.
- **Installable service** like NetBird (systemd + CLI): milestone 3b.
- **Wiki** split into guides / reference / project / tools sections. `tools/` is only for
  testing tools.

## Milestone 3b decisions
- **NetBird-style install:** `install.sh` + `crypto-helper service …`; code in `/opt`, config
  and key in `/etc`, data in `/var/lib`, dedicated no-login service user.
- **Updates follow a git branch** and roll back code and database automatically on failure.
- **Daily automatic backups** (14 kept); the key is deliberately not in them.
- **Setup token is not written to the journal** under systemd (the spec said "print to the
  console"; the journal keeps it for weeks). `crypto-helper setup token` shows it instead.
- **Binding:** loopback by default; a private-network address such as the NetBird IP needs
  `BOT_ALLOW_REMOTE_BIND=true`; every-interface binds are refused outright.
- **Root drops to the service user** for account and database commands.
