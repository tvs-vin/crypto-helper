---
title: Install as a service
---

# Install as a service

This installs Crypto Helper the way NetBird is installed: a background service that starts
at boot, plus a `crypto-helper` command to manage it.

You need: a Linux machine running systemd, Python 3.12+ with `venv`, and git
(on Debian/Ubuntu: `sudo apt install python3 python3-venv git`). Optional: `ffmpeg`, for video
wallpapers (`sudo apt install ffmpeg`).

## 1. Get the code
```bash
git clone https://github.com/tvs-vin/crypto-helper.git
cd crypto-helper
git checkout dev      # or main, once there's a release
```

## 2. Install
```bash
sudo ./install.sh
```
It copies the code to `/opt/crypto-helper`, creates a `crypto-helper` system user,
writes the config and a new encryption key to `/etc/crypto-helper`, and starts the service.
It ends by telling you what to do next. It's safe to run again.

Port 8000 taken? `sudo ./install.sh --port 8001`.

## 3. Back up the encryption key
Copy `/etc/crypto-helper/secret.key` somewhere **off this machine** (a password manager is
ideal). Without it, 2FA codes can't be checked. See
[Configuration]({{ site.baseurl }}/reference/configuration#secret-key).

## 4. Create the `super` account
```bash
sudo crypto-helper setup token
```
Then send the token with a password, as in [Getting started]({{ site.baseurl }}/guides/getting-started#create-the-super-account).

## 5. Check everything
```bash
sudo crypto-helper doctor
```
Every line should be a ✓ or an `i`. Anything else comes with the command that fixes it.

## 6. Reach it from your computer
It only listens on the VM itself. See [Remote access]({{ site.baseurl }}/guides/remote-access).

## Day to day
| To… | Run |
|---|---|
| See if it's healthy | `sudo crypto-helper service status` |
| Read the log | `sudo crypto-helper service logs -f` |
| Apply a config change | `sudo crypto-helper service restart` |
| Upgrade | `sudo crypto-helper update` ([Updating]({{ site.baseurl }}/guides/updating)) |
| Back up now | `sudo crypto-helper db backup` ([Backups]({{ site.baseurl }}/guides/backups)) |

## Removing it
```bash
sudo crypto-helper service uninstall           # stops it; keeps data, config, key and code
sudo crypto-helper service uninstall --purge   # deletes everything (keeps one last copy in /root)
```
