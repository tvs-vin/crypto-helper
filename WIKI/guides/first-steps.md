---
title: First steps
---

# First steps: the walkthrough and Getting started

The first time an account signs in, Crypto Helper walks it through getting set up. super's
walkthrough also covers the **server**; everyone else only sees the steps their permissions
allow. Anything can be skipped and done later, except what the account is required to do.

## 1. Create the super account (first launch)
1. On the server, run `sudo crypto-helper setup token`. The token proves you own the server
   (someone else who reaches the page first would need it too). It works once.
2. Open the web page, paste the token, choose a password (12+ characters; the strength hint
   under it says "Strong" for a long one, like a few random words).
3. Sign in as `super`.

## 2. Turn on two-factor login (required for super)
super can do everything, so it must turn on **two-factor login** (a 6-digit code from an app on
your phone) before anything else. Nothing else works until it's on: the server refuses every
other request from that session. Scan the QR code, type the code and your password, then save
the 10 recovery codes somewhere away from your phone. See [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa).

## 3. The server (super only)
| Step | What it's about |
|---|---|
| Back up the encryption key | The key file (`/etc/crypto-helper/secret.key`) decrypts the server's secrets: 2FA, exchange keys, xpubs, Discord webhooks. Backups leave it out on purpose, so copy it off the machine once (`sudo cat /etc/crypto-helper/secret.key`, into a password manager). Tick the box when it's done |
| Where it listens, who may connect | Which of this machine's addresses the web UI listens on, and which networks may connect. See [below](#changing-where-it-listens) |
| Services and features | The Services window: backups, the embed server, Console and Terminal, feature switches ([Services]({{ site.baseurl }}/guides/services)) |
| Prices, history and syncing | How often wallets sync, price and balance history, extra coins |
| Invite people | The Users window: an account per person, with only what they need |

## 4. Getting to know it (every account)
| Step | Shown when | Done when |
|---|---|---|
| What Crypto Helper does, and never does | always | you've read it |
| Choose your own password | an admin required it | you chose one |
| Turn on two-factor login | always (required if an admin asked) | 2FA is on |
| Currency, theme and size | always | you've looked |
| Coins to watch | `prices.view` | your watchlist has a coin |
| Add your first wallet | `wallets.edit` | a wallet exists (guided setup, exchange, address, or a paper wallet made right there) |
| Sync a wallet | `wallets.connect` | a wallet syncs from an exchange or addresses |
| Set an alert | `prices.view` | you have a price alert |
| Notifications and Discord | always | you've looked, or saved a Discord webhook |
| A tour of the desktop | always | you finished the tour |

Buttons like **Open Wallets** shrink the walkthrough to a bar at the bottom of the screen while
you work in that window; **Continue** brings it back. Closing the bar (×) ends the walkthrough;
it doesn't open by itself again.

## 5. Getting started (any time)
**Windows → Getting started** lists every step with a tick for what's done. It ticks itself
from what's really set up (2FA on, a wallet synced, a webhook saved). **Do it** opens the
walkthrough at that step; **Walk me through it** starts at the first one left.

## Account rules
An admin (`users.manage`) can set two rules per account, in the Users window (or with
`crypto-helper account <name> new-password on` / `require-2fa on`):
- **Must choose a new password:** offered (ticked by default) when creating an account or
  resetting a password, and **Require a new password at next sign-in** for anyone. The password
  the admin typed then works only to choose a new one.
- **Two-factor login required:** the account must turn on 2FA, and can't turn it off.

Until the rule is met, that account's sessions can only do that (and sign out, or see where
they're signed in): the server refuses everything else with `403`. super always needs 2FA.

## Changing where it listens
In the walkthrough, or later in **Settings → System → Network** (super only):
1. Tick the addresses to listen on. The list is this machine's own addresses, labelled
   (this machine only, NetBird, Tailscale, local network, public internet). `127.0.0.1` always
   stays, and so does the address you're using right now.
2. Add the networks allowed to connect (a suggestion appears for each address you tick, e.g.
   `100.64.0.0/10` for NetBird or Tailscale). `127.0.0.0/8` always stays; the network your browser
   is on must stay too.
3. **Apply.** The server restarts on the new settings; the page waits for it and confirms.

It can't lock you out: the main server never listens on every interface (`0.0.0.0`); if the
restarted server doesn't answer the page within 2 minutes, the agent puts the old settings
back and restarts it again. This needs the agent; without it, the page shows the lines to put
in `/etc/crypto-helper/config.env` and the command to run. Details:
[Remote access]({{ site.baseurl }}/guides/remote-access).
