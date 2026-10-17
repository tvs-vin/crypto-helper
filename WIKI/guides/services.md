---
title: Services
---

# Services

The **Services** window turns Crypto Helper's services and features on and off, and runs the
self-test. It needs the `services.manage` permission (only `super` has it at first; it isn't
in any preset).

| Section | What's in it | Needs the agent |
|---|---|---|
| System services | Web UI (restart), embed server (on/off, restart), daily backups (on/off, back up now), [Console and Terminal]({{ site.baseurl }}/guides/console-and-terminal) (on/off), the agent's own status | Yes |
| Features | Paper wallets, practice transfers, price history recording | No |
| Test tools | Practice prices, the self-test | No |

## 1. Turn on the agent (once, on the VM)
The app itself runs as a locked-down user that can't start or stop system services. A small
helper, the **agent**, does that for it:
```bash
crypto-helper agent enable       # asks for sudo
crypto-helper agent status
```
New installs ask whether to turn it on (`service install` / `install.sh`), so you may already
have it. Without it, the Services window shows this command and greys out the system switches;
features and the self-test still work.

What the agent can and can't do:
- It only does a fixed list of jobs: report the state of Crypto Helper's services, switch the
  embed server, daily backups, Console and Terminal on or off, restart the web UI or the embed
  server, start a backup, run one of the Console's fixed commands, open a Terminal login
  prompt, check whether an update is waiting (`crypto-helper update --check`, which never
  installs anything; for [notifications]({{ site.baseurl }}/guides/notifications#automatic-notifications)).
  It never runs a command it's sent.
- Only the web app's user (and root) can talk to it: its socket is in a folder only that
  group can open, and it checks the caller's user on every connection.
- It runs as root but boxed in: no network at all, no special privileges, everything
  read-only except `/etc` (to edit the config) and its own socket folder.
- For a Console command, an update check or a Terminal session it asks systemd to start a separate one-off
  unit. A Terminal's unit runs a real login session, which has full root powers (logging in
  as another user and `sudo` need them): that's why the Terminal is off by default, only super
  can grant it, and it asks for your password, a code and then a Linux password.
- Who may use it is decided by the web app (`services.manage`); the agent logs who asked
  (`sudo crypto-helper service logs`). Everything is in the audit log too.
- Turning the agent itself off is CLI only: `sudo crypto-helper agent disable`.

## 2. System services
- **Web UI → Restart**: the page reconnects by itself after a few seconds.
- **Embed server**: the same as `crypto-helper embed enable/disable` (see [Embeds]({{ site.baseurl }}/guides/embeds)).
- **Daily backups**: switch the daily backup off or on; **Back up now** makes one straight
  away (see [Backups]({{ site.baseurl }}/guides/backups)).

## 3. Features
These apply to everyone on this install, `super` included (unlike the
[App manager]({{ site.baseurl }}/guides/app-manager), which decides who may open which window).

| Feature | Off means |
|---|---|
| Paper wallets | No new paper (practice) wallets; existing ones stay and still work |
| Practice transfers | No new simulated transfers; the history stays visible |
| Price history recording | Prices aren't saved for the charts (same switch as Settings → Prices) |

## 4. Test tools
- **Practice prices**: every price in the app (and in embeds) becomes a made-up one, so you can
  try things without real market data. Price history recording pauses while it's on, so
  made-up prices never end up in your charts. Switch it off to go back to CoinGecko.
- **Self-test**: runs every end-to-end check (the [tester]({{ site.baseurl }}/tools/tester))
  against a **throwaway copy** of the server on a temporary database. It never touches your
  data, your settings or the real services. Takes about a minute; the result, any failures and
  the output stay on the page until the next run.

## Choosing services when installing
```bash
sudo ./install.sh                                 # asks about each one
sudo ./install.sh --services agent,backups        # or say it up front
sudo crypto-helper service install --services none
```
Optional services: `backups` (on by default), `agent` (on by default), `embed` (off by
default). Re-running the install without `--services` keeps whatever is on now.
