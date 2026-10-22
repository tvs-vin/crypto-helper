---
title: Remote access
---

# Remote access

The service only listens on the VM itself (`127.0.0.1`). That's deliberate: a login page
on an open port gets scanned and attacked within hours. Pick one of these ways in.

## SSH tunnel (works now, nothing to install)
From your computer:
```bash
ssh -L 8000:127.0.0.1:8000 root@192.168.50.251       # on your home network
ssh -L 8000:127.0.0.1:8000 root@100.64.39.116        # over NetBird, from anywhere
```
Leave it open and browse to `http://localhost:8000`. Traffic is encrypted by SSH.

## NetBird directly (you already run it)
NetBird gives the VM a private address (`100.64.39.116`, network `100.64.0.0/16`) that only
your NetBird peers can reach, and encrypts traffic with WireGuard.

**From the browser** (with the agent on): Settings → System → Network, or the walkthrough's
"Where it listens" step: tick the NetBird address, add its network, Apply
([details]({{ site.baseurl }}/guides/first-steps#changing-where-it-listens)). **By hand**, in
`/etc/crypto-helper/config.env`:
```bash
BOT_HOST=127.0.0.1,100.64.39.116
BOT_ALLOW_REMOTE_BIND=true
BOT_ALLOWED_NETWORKS=127.0.0.0/8,100.64.0.0/16
```
then `sudo crypto-helper service restart` and browse to `http://100.64.39.116:8000` from any
of your NetBird devices.

Two layers: `BOT_HOST` decides which addresses accept connections; `BOT_ALLOWED_NETWORKS`
refuses any client that isn't from this machine or NetBird. The second matters because Linux
accepts traffic for the NetBird address even if it arrives on the home-network card.

Things to know:
- Every peer on your NetBird network can reach the login page (2FA and the lockout protect
  it). If some peers aren't yours, add a NetBird access policy so only your devices can reach
  port 8000.
- The connection is plain HTTP inside the WireGuard tunnel, so keep
  `BOT_COOKIE_SECURE=false`, and browsers won't allow passkeys (WebAuthn) this way.
- `crypto-helper serve` refuses `0.0.0.0` (every interface) no matter what.

## HTTPS (needed later for passkeys)
Two free options that keep the port closed:
- **Tailscale:** `tailscale serve --bg 8000` publishes it with a real certificate on your
  tailnet only.
- **Cloudflare Tunnel + Access:** puts a login wall (e.g. your Google account) in front of it.

With either, set `BOT_COOKIE_SECURE=true` and restart. Requests from these proxies come
from `127.0.0.1`, and the service trusts their `X-Forwarded-For` header, so the audit log
shows the real visitor address.

## Never
Don't open port 8000 on your router or bind to `0.0.0.0`. `sudo crypto-helper doctor` fails
if the port is open on every interface.
