---
title: Embeds
---

# Embeds

An embed is a link that shows one chosen view outside the app: your portfolio, your wallet
cards, or a price table. Paste it in Discord and the message shows a picture of it, or put
it in a frame on your website and visitors see the live page.

Embeds are **off until you turn them on**. They're served by a second, separate server on
its own port, which can show nothing except embed pages and their pictures. It has no
login, no API and no way to change anything, so publishing it never publishes the app.

## What anyone with the link can see
Whoever has an embed's link sees exactly what you switched on for it, and nothing else.
The link is a long random code (192 bits), so it can't be guessed, but anyone you give it
to can pass it on.

- **Amounts held** and **values and totals** are off on every new embed. Leave them off
  unless you're happy for strangers to know how much you hold. People who know you hold
  crypto, and roughly how much, are more likely to target you with phishing or worse.
- Everything else (wallet names, network, tags, colours, coin names, shares as a
  percentage, prices, 24-hour change, the update time) has its own switch too.
- Wallet **addresses are never shown**, whatever you switch on.
- An embed stops working at once if you turn it off, delete it, make a new link for it, let
  it expire, or if your account is deactivated or loses the `embeds.create` permission.

## 1. Turn the embed server on
On the VM:
```bash
crypto-helper embed enable          # asks for sudo
crypto-helper embed status
```
It listens on port 8001 **on the same addresses as the web UI** (`BOT_HOST`). If you reach
the app over NetBird at `http://100.64.39.116:8000`, embeds are at `http://100.64.39.116:8001`
and the links it gives you use that address. Change the port with `--port 8100`.

To give it addresses of its own instead, use `--host`; anything but this machine then also
needs `--allow-public`. `--host main` goes back to following the web UI.

## 2. Make it reachable
Discord's servers fetch the picture themselves, and your website's visitors load the page
from their own browsers. Both need an address on the internet, but **don't open a port on
your router**. Use a tunnel that connects out from the VM to port 8001 only (never 8000,
which is the app):

**Cloudflare Tunnel** (free; works best with a domain you own on Cloudflare):
```bash
# quick try-out: prints a random https://….trycloudflare.com address (changes each run)
cloudflared tunnel --url http://127.0.0.1:8001
```
For a lasting address, make a named tunnel for a hostname like `embed.example.com` that
points at `http://127.0.0.1:8001` (see Cloudflare's "Create a tunnel" guide).

**Tailscale Funnel** also works (`tailscale funnel 8001`), if you use Tailscale.

Then tell Crypto Helper the public address, so the links it gives you use it:
```bash
crypto-helper embed enable --public-url https://embed.example.com
```

Inside your NetBird network no tunnel is needed: your devices already reach the NetBird
address. Discord's servers can't, though, so Discord needs the tunnel.

## 3. Make an embed
In the app: **Settings → Embeds → New embed**.

| Setting | What it does |
|---|---|
| Name | Only you see it. |
| Heading | The title shown on the embed (defaults to the name). |
| Show | **Portfolio** (coins as shares of the total), **Wallets** (one card per wallet with its coins), **Prices** (a price table). |
| What it shows | One switch per item. Amounts and values warn you when they're on. |
| Wallets | Which wallets to include; none ticked means all active wallets. |
| Coins | Only these coins (e.g. `BTC, ETH`); empty means all. |
| Currency, Theme | Any built-in theme, or a custom theme of yours or one an admin published. |
| Refreshes every | How often a framed page reloads itself (1 minute to 1 hour). |
| Websites that may show it in a frame | Exact origins like `https://myblog.example.com`, one per line. Empty means no website can frame it. Discord doesn't need this. |
| Stops working on | Optional end date. |

Each embed card shows a preview of the Discord picture, how often it's been viewed, its
link, and the frame code once you've listed a website.

## 4. Use it
- **Discord, chat apps:** paste the link. Discord shows the picture (1200×630) with the
  heading and a short summary. Discord caches pictures for a while, so a fresh post shows
  newer numbers sooner than an old one.
- **A website:** paste the frame code (`<iframe …>`) into the page. The page must be on one
  of the websites you listed, or the browser will refuse to show it.
- **A browser:** open the link; the page refreshes itself.

## Turning it off
- One embed: **Turn off** (keeps it, link stops working) or **Delete**.
- A leaked link: **New link**. The old link stops working immediately.
- Everything: `crypto-helper embed disable` stops the embed server; every link stops working
  until you turn it back on.

## How it's kept safe
- A separate process and port, off by default. It answers only `GET`/`HEAD` for embed pages,
  their stylesheets and pictures; everything else is a plain 404.
- The page has no JavaScript at all and builds every value as escaped text. Its
  Content-Security-Policy is `default-src 'none'`, and `frame-ancestors` allows only the
  websites you listed (`X-Frame-Options: DENY` when there are none).
- Links are stored hashed (for lookup) and encrypted (so you can copy them again), never in
  plain text.
- Requests are limited per address (`BOT_EMBED_RATE_PER_MINUTE`, default 120) and can be
  restricted to networks (`BOT_EMBED_ALLOWED_NETWORKS`).
- By default it listens only where the web UI already does, under the web UI's own rules
  (`BOT_ALLOW_REMOTE_BIND`; `0.0.0.0` never). Addresses of its own beyond this machine need
  `--allow-public`.
- Creating, changing and deleting embeds is in the audit log, including which sensitive
  items an embed shows.

Details: [Configuration]({{ site.baseurl }}/reference/configuration#embeds),
[CLI]({{ site.baseurl }}/reference/cli#embeds), [API]({{ site.baseurl }}/reference/api#embeds),
[Security]({{ site.baseurl }}/reference/security#embeds).
