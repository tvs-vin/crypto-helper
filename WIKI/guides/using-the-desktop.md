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
Open one from **Windows** in the taskbar. You only see the windows your permissions allow.

| To… | Do this |
|---|---|
| Move | Drag the title bar |
| Resize | Drag any edge or corner |
| Snap to half the screen | Drag to the left or right edge |
| Snap to a quarter | Drag into a corner |
| Maximize / restore | Drag to the top edge, or double-click the title bar |
| Minimize | The `_` button; bring it back from the taskbar |
| Arrange everything in a grid | **Tile** in the taskbar |

While dragging, an outline shows where the window will land.

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

## The windows
| Window | What it's for | Needs |
|---|---|---|
| Wallets | Your wallets as cards (nickname big, then name, then tags, in the wallet's two colors), with balances and values. Group by wallet or by coin; filter by kind or tag; sort by your own order (drag the cards), name, newest or value. Create, edit, set balances, archive, delete. | `wallets.view` (changes: `wallets.edit`; values: `prices.view`) |
| Overview | Portfolio total, prices, 24h change, your holdings and their value. Star coins for your watchlist, pick the currency and columns, click a column to sort, click a coin for its price chart (hover for exact prices). | `prices.view` (holdings: `wallets.view`) |
| Transfers | Practise moving coins between wallets, with the same network rules as real life, and the history. Always labelled "Simulated, no real funds move". | `wallets.view` (sending: `transfers.create`) |
| Audit log | Everything that changed, who did it and from where; search and load more. | `audit.view` |
| Settings | Theme and layout (the rest arrives in part 6c). | nothing |

Windows keep each other up to date: send a transfer and the Wallets and Overview windows
refresh by themselves. Prices refresh every minute.

## Themes
Settings → Theme: **Dark** (default), **Light**, **Terminal**, or **Template** (the starting
point for your own). The change applies at once and is remembered for your account.
Uploading your own `.ctheme` arrives in part 6c; the format is in
[Themes]({{ site.baseurl }}/reference/themes).

## On a phone
Windows stack down the page as cards; scroll to move between them. Dragging and tiling are
for larger screens.
