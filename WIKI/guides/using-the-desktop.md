---
title: Using the desktop
---

# Using the desktop

Open the dashboard in a browser (see [Remote access]({{ site.baseurl }}/guides/remote-access)).

## Signing in
1. The page loads and a sign-in box appears in the middle.
2. Enter your username and password. With [2FA]({{ site.baseurl }}/guides/set-up-2fa) on, the
   box then asks for the 6-digit code; **Use a recovery code** switches to a backup code.
3. The box closes and your desktop comes back exactly as you left it: the same windows, in the
   same places, in your theme.

On the very first launch the box asks for the setup token instead
(`sudo crypto-helper setup token` on the VM) to create `super`.

If your session ends while you're working (after 12 hours, or you signed out elsewhere), the
box comes back **over your open windows**. Sign in and carry on; nothing on screen is lost.
Sign out from your name at the right of the taskbar.

## Windows
Open one from **Windows** in the taskbar. You only see the windows your permissions (and the
[App manager]({{ site.baseurl }}/guides/app-manager)) allow.

| To… | Do this |
|---|---|
| Move | Drag the title bar |
| Resize | Drag any edge or corner |
| Snap to half the screen | Drag to the left or right edge |
| Snap to a quarter | Drag into a corner |
| Maximize / restore | Drag to the top edge, or double-click the title bar |
| Minimize | The `_` button; bring it back from the taskbar |
| Read about it | The `?` button opens [Help](#help) at that window's guide |
| Arrange everything in a grid | **Tile** in the taskbar |

While dragging, an outline shows where the window will land.

### Several windows of one app
Overview, Wallets, Transfers and Audit log can each be open up to **4 times**. Open another
with the **+** next to it in **Windows**, Ctrl+click (or middle-click) it there, or press
**Ctrl+Alt+N** in one of its windows. They're numbered ("Overview 2") and each has its own
taskbar button. Other windows (Settings, Users, App manager, Services) open once.

Each **Overview** window keeps its own **currency, charted coin and range**, so you can watch
BTC in dollars in one and ETH in euros in another. Columns, sort order and the watchlist are
shared by all of them (they're your preferences). Everything comes back after a reload, on any
browser.

### Two layout modes
Switch with the button next to **Tile**, or in Settings.
- **Floating:** windows go wherever you put them.
- **Tiled:** windows always share the screen without overlapping. Opening or closing one
  rearranges the rest. Drag a window onto another to swap them. Pick **Main + stack** (one big
  window on the left) or **Grid** in Settings.

Your layout, mode and window positions save automatically and follow you to any browser.

### Keyboard
| Keys | Does |
|---|---|
| Ctrl+Alt+← / → | Snap the active window left / right |
| Ctrl+Alt+↑ | Maximize it |
| Ctrl+Alt+↓ | Minimize it |
| Ctrl+Alt+T | Switch floating ↔ tiled |
| Ctrl+Alt+G | Tile |
| Ctrl+Alt+N | Another window of the active app (if it allows more) |

## The windows
| Window | What it's for | Needs |
|---|---|---|
| Wallets | Your wallets as cards (nickname big, then name, then tags, in the wallet's two colors), with balances and values. Group by wallet or by coin; filter by kind or tag; sort by your own order (drag the cards), name, newest or value. Create, edit, set balances, archive, delete. Each card shows its last 30 days; click it for the wallet's [history]({{ site.baseurl }}/guides/balance-history). | `wallets.view` (changes: `wallets.edit`; values: `prices.view`) |
| Overview | Portfolio total and its [value over time]({{ site.baseurl }}/guides/balance-history), prices, 24h change, your holdings and their value. Star coins for your watchlist, pick the currency and columns, click a column to sort, click a coin for its price chart (hover for exact prices). | `prices.view` (holdings: `wallets.view`) |
| Transfers | Practise moving coins between wallets, with the same network rules as real life, and the history. Always labelled "Simulated, no real funds move". | `wallets.view` (sending: `transfers.create`) |
| Trade log | Trades imported from your exchanges; filters; CSV for TurboTax, CoinLedger, CoinTracker, Koinly or a spreadsheet. See [Trade log]({{ site.baseurl }}/guides/trade-log). | `wallets.view` |
| Audit log | Everything that changed, who did it and from where; search and load more. | `audit.view` |
| Users | Create users from presets, change permissions, reset passwords, deactivate, delete. You can only grant what you hold. | `users.manage` |
| App manager | Which apps each account can open, and switching an app off for everyone. See [App manager]({{ site.baseurl }}/guides/app-manager). | `apps.manage` |
| Services | Turn services and features on and off, practice prices, the self-test. See [Services]({{ site.baseurl }}/guides/services). | `services.manage` |
| Notifications | Your notifications: read, open what they're about, mark read, clear; sending one with `notifications.send`. See [Notifications]({{ site.baseurl }}/guides/notifications). | nothing |
| Help | This wiki, inside the app. See [Help](#help). | nothing |
| Alerts | Every alert you have: price, portfolio value, wallet balance changes, drift from your targets, trend signals. See [Alerts]({{ site.baseurl }}/guides/alerts). | `prices.view` (holdings alerts: `wallets.view`) |
| Getting started | What's set up and what's left, ticked from what's really there; reopens the walkthrough at any step. See [First steps]({{ site.baseurl }}/guides/first-steps). | nothing |
| Settings | **Account**: password, two-factor login with a QR code, recovery codes, where you're signed in. **Appearance**: themes (upload your own), layout. **Display**: currency, columns, watchlist, reset the desktop. **Prices**: history settings, extra coins (`prices.manage`). **System**: version and health, and where it listens (`super`). | nothing |

Windows keep each other up to date: send a transfer and the Wallets and Overview windows
refresh by themselves. Prices refresh every minute.

## Help
**Windows → Help**, or the `?` in any window's title bar (it opens that window's guide). It
holds this wiki, read from the copy installed with the app, so it always describes the version
you're running and works without the internet.
- The contents on the left, by section; **← Back** returns to the page you came from.
- **Search help** looks through titles, headings and text; a result opens at the matching
  heading.
- Links to other wiki pages open inside Help. Outside links open in a new tab.

## Themes
Settings → Appearance: **Dark** (default), **Light**, **Terminal**, **Template**, and any
themes you've uploaded or an admin has published. The change applies at once and follows you.

To make your own: **Download the template**, change the colors, then **Upload .ctheme**. It's
checked and previewed before anything is saved (**Save to my themes** or **Discard**). A theme
can also be a **bundle** with its own wallpapers and icons (installed straight away; its card
shows what it brought). The format, and the `crypto-helper theme pack` command that makes
bundles, are in [Themes]({{ site.baseurl }}/reference/themes).

## Scale
Settings → Display → **Scale** makes everything bigger or smaller, from 75% to 150%.
- **Your account** sets the scale on every device you sign in on.
- Tick **Use a different scale on this device** to give one browser its own (kept in that
  browser only), e.g. 125% on a big monitor and 90% on a laptop.
- Keys: **Ctrl+Alt+=** / **Ctrl+Alt+-** change this device; **Ctrl+Alt+0** goes back to your
  account's scale.

Windows, snapping, tiling and menus work the same at any scale.

## Wallpaper
Settings → Appearance → **Wallpaper**.
- **Built in:** Aurora, Dusk, Midnight grid, Paper, and **Drift** (animated).
- **Theme's own:** whatever your theme brings (Dark: Aurora, Light: Paper, Terminal: Midnight
  grid, or a bundle's own); it changes with the theme.
- **Upload…** your own: pictures (PNG, JPEG, WebP), animations (GIF, animated WebP) or short
  videos (MP4, WebM). The server checks and converts every upload before it's shown:
  - pictures become WebP (at most 3840×2160), and things like where a photo was taken are removed;
  - animations become animated WebP (at most 1280 px and 300 frames);
  - videos become silent WebM (at most 1920×1080, 30 fps and 60 seconds; longer ones are cut);
  - files that aren't what they claim, or are built to crash or trick a decoder, are refused.

  Videos need ffmpeg on the server (`sudo apt install ffmpeg`; `doctor` says if it's missing).
  Up to 20 uploads each. They're private; an admin with `themes.publish` can **Share with
  everyone**.
- **Fill / Fit / Centre / Tile**, **Dim** (darkens it so windows stay readable) and **Blur**.
- **Animate / Still:** moving wallpapers stand still on "Still", when your device asks for reduced
  motion, and pause while the tab is in the background. Videos are always muted.

## On a phone
Windows stack down the page as cards; scroll to move between them. Dragging and tiling are
for larger screens.
