---
title: Backups
---

# Backups

## Automatic
The service installs a daily timer (`crypto-helper-backup.timer`). Once a day, at a random
time within 30 minutes of midnight, it writes `/var/lib/crypto-helper/backups/bot-<time>.db`
and keeps the newest 14. If the VM was off at that time, it runs at the next boot.

`sudo crypto-helper service status` shows the last backup and the next run;
`sudo crypto-helper doctor` warns if the newest one is more than 2 days old.

## By hand
```bash
sudo crypto-helper db backup                       # into the backups folder
sudo crypto-helper db backup /root/before-change.db  # somewhere specific
```
Backups are consistent snapshots (SQLite's online backup), safe to take while the service
runs. They're created private (mode 0600) and never overwrite an existing file.

## What a backup contains, and what it doesn't
It's the whole database: accounts, password hashes, encrypted 2FA secrets, hashed recovery
codes, audit log. It does **not** contain the encryption key, on purpose: someone with a
stolen backup alone can't read the 2FA secrets.

So keep **two** things safe, in different places:
1. Database backups (copy `/var/lib/crypto-helper/backups/` off the VM regularly).
2. The key, `/etc/crypto-helper/secret.key` (once, e.g. in a password manager).

## Restoring
```bash
sudo crypto-helper service stop
sudo cp /var/lib/crypto-helper/backups/bot-YYYYMMDD-HHMMSS.db /var/lib/crypto-helper/bot.db
sudo chown crypto-helper: /var/lib/crypto-helper/bot.db
sudo chmod 600 /var/lib/crypto-helper/bot.db
sudo crypto-helper service start      # applies any migrations the backup is missing
sudo crypto-helper doctor
```
A backup from an older version is fine: migrations bring it up to date on start.
