---
title: Console and Terminal
---

# Console and Terminal

Two windows for looking after the VM from the browser:

| | Console | Terminal |
|---|---|---|
| What it is | A fixed set of `crypto-helper` commands, one click each | The VM's own **login prompt**: a real shell |
| You can run | status, doctor, logs, version, update check, prices check, embed status, agent status, config, backup | Anything your Linux account can (including `sudo`) |
| Permission | `console.use` | `terminal.use`, which **only super can grant** |
| Also needs | 2FA on your account | 2FA, plus your password and a code **every time** you open one, then a Linux password |
| Off by default | Yes: switch on in Services | Yes: switch on in Services |

Both need the [agent]({{ site.baseurl }}/guides/services). Everything they do is in the audit
log (which command, when a terminal opened and closed); what you type in a terminal is never
recorded.

## Why the Terminal is guarded so tightly
A terminal is full control of the VM. If someone ever got hold of your signed-in browser (a
stolen laptop, a malicious extension), a terminal would hand them the encryption key, the 2FA
secrets and, later, exchange keys. So:
- It's off until someone with the Services permission switches it on.
- Only `super` can give anyone the Terminal permission.
- Opening one asks for your Crypto Helper password **and** a code from your authenticator app
  (recovery codes don't work here), at most 10 times an hour.
- Then it's the VM's own `login:` prompt: you still need a **Linux** account's password, checked
  by the system itself (PAM), not by Crypto Helper. A stolen session alone gets only that prompt.
- It closes when you sign out, close the window, lose the permission, or the app is switched off
  for you (checked every 30 seconds).

## 1. Switch them on
**Services → System services → Console / Terminal**. (Or, on the VM:
`sudo crypto-helper agent status` shows whether they're on.)

## 2. Give people access
- **Console**: tick `console.use` in the Users window (like any permission).
- **Terminal**: only `super` can tick `terminal.use`.
- Both also show up in the [App manager]({{ site.baseurl }}/guides/app-manager), where you can
  switch them off per account.
- The account needs [2FA]({{ site.baseurl }}/guides/set-up-2fa) turned on.

## 3. Use the Console
**Windows → Console**, then click a command. The output shows with its result (**ok** or the
exit code) and a Copy button. For `logs`, pick how many lines first.

## 4. Use the Terminal
1. **Windows → Terminal** (up to 3 at once).
2. Enter your Crypto Helper password and a code from your authenticator app → **Open terminal**.
3. At `login:`, sign in with a Linux account on the VM (for example `vin`). After 5 wrong
   passwords the prompt closes; open a new one to try again.
4. Use it like an SSH session. `exit` (or closing the window) ends it; **New session** starts
   another (and asks again).

Copy and paste: select text to copy it (Ctrl+Shift+C / Ctrl+Shift+V in most browsers, or the
right-click menu).
