---
title: Service
---

# Service

What `install.sh` and `crypto-helper service install` put on the machine.

## Files
| Path | Owner, mode | What |
|---|---|---|
| `/opt/crypto-helper/src` | root, 755 | Git clone the install follows; `update` pulls into it |
| `/opt/crypto-helper/venv` | root, 755 | Python environment with the installed code |
| `/usr/local/bin/crypto-helper` | symlink | The command |
| `/etc/crypto-helper/` | root:crypto-helper, 750 | Config folder |
| `/etc/crypto-helper/config.env` | root:crypto-helper, 640 | [Settings]({{ site.baseurl }}/reference/configuration) |
| `/etc/crypto-helper/secret.key` | root:crypto-helper, 640 | Encryption key |
| `/var/lib/crypto-helper/` | crypto-helper, 700 | Data: `bot.db`, `setup-token`, `backups/` |
| `/etc/systemd/system/crypto-helper.service` | root, 644 | The service |
| `/etc/systemd/system/crypto-helper-backup.{service,timer}` | root, 644 | Daily backup |
| `/etc/systemd/system/crypto-helper-agent.service` | root, 644 | The [agent]({{ site.baseurl }}/guides/services) (root helper for the Services window); enabled when chosen at install or by `crypto-helper agent enable` |
| `crypto-helper-console-*.service`, `crypto-helper-terminal-*.service` | transient | One-off units the agent starts for a Console command or a Terminal session; removed when they end |
| `/run/crypto-helper-agent/agent.sock` | root:crypto-helper, 660 (folder 750) | The agent's socket |
| `/etc/systemd/system/crypto-helper-embed.service` | root, 644 | The [embed server]({{ site.baseurl }}/guides/embeds); enabled only by `crypto-helper embed enable` |

The service can read its config and key but not change them (root owns them). Only the
service user can read the data folder. Re-running the install never overwrites the config
or the key; it does rewrite the unit files (put local changes in
`sudo systemctl edit crypto-helper`).

## The service user
`crypto-helper` is a system account with no password, no shell (`/usr/sbin/nologin`) and no
home folder. Running `sudo crypto-helper account|setup|db …` switches to it before touching
the database, so files it creates belong to the service, and those commands can't do more
than the service itself could.

## Sandbox
The unit turns off everything the app doesn't need. `systemd-analyze security
crypto-helper` scores it **1.2 (OK)** on a 0 (locked down) to 10 (wide open) scale;
`crypto-helper doctor` shows the live score.

| Setting | Effect |
|---|---|
| `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes` | Whole filesystem read-only except its data folder; can't see /home or /root; own /tmp |
| `NoNewPrivileges`, `CapabilityBoundingSet=` (empty), `RestrictSUIDSGID` | Can never gain privileges, even through a setuid program |
| `SystemCallFilter=@system-service`, minus `@privileged @resources` | Only ordinary system calls |
| `MemoryDenyWriteExecute=yes` | No memory that's both writable and executable (blocks most code injection) |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` | Only normal network sockets |
| `PrivateDevices`, `ProtectKernel*`, `ProtectClock`, `ProtectHostname`, `ProtectProc=invisible` | Can't touch devices, the kernel, the clock, or other processes |
| `UMask=0077` | Every file it creates is private |
| `Restart=on-failure` | Restarts after a crash; `doctor` warns if that keeps happening |

The backup job and the embed server use the same sandbox. `service stop` stops the embed
server too; `start` and `restart` include it when embeds are on; `update` stops it before
migrating, rewrites the unit files, and starts it again afterwards.

### The agent's sandbox
The agent runs as root (it starts and stops units and edits the config) with
`Group=crypto-helper`, so its socket belongs to the service user's group. It's boxed in
differently: `PrivateNetwork=yes` and `RestrictAddressFamilies=AF_UNIX` (no network at all),
`CapabilityBoundingSet=` (no capabilities: it works only as the owner of what it touches),
`ProtectSystem=true` (`/usr` read-only; `/etc` writable for the config), `ProtectHome`,
`NoNewPrivileges`, `MemoryDenyWriteExecute`, `@system-service` system calls. Score 1.4.

## Logs
Everything goes to the systemd journal: `sudo crypto-helper service logs [-f] [-n N]`
(the service, the backup job, the embed server and the agent).
The first-launch setup token is **not** written there (journals are kept for weeks): the log
says to run `sudo crypto-helper setup token` instead.

## Health
`service install`, `start`, `restart` and `update` wait for `GET /api/setup/status` to answer
before reporting success.
