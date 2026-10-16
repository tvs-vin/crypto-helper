---
title: App manager
---

# App manager

Each window on the desktop is an *app*: Wallets, Overview, Transfers, Audit log, Users and the
App manager itself. Settings is always there (your password, 2FA and sessions live in it).
The App manager decides which apps each account can open.

## What an account needs to open an app
All three:
1. **The app switched on for the account.** New accounts get every app, including apps
   added in later updates.
2. **The app not switched off for everyone.**
3. **The permissions the app needs** (for example Wallets needs `wallets.view`). Permissions
   are given in the Users window, as before.

`super` can always open every app, whatever the switches say.

The server checks the switches on every request, not just the menu. Turn Wallets off for
someone and they can no longer create or edit wallets, even by calling the API directly.
Other apps keep working: Transfers can still list the wallets it needs.

## 1. Open it
Needs the `apps.manage` permission (part of the admin preset). **Windows → App manager**.

## 2. Switch apps per account
The **Accounts** grid has a row per account and a column per app. Tick or untick a box; it
saves at once.

- A shield next to a ticked box means the app is on but the account still can't open it.
  Hover to see why (usually a missing permission, or the app is off for everyone).
- **Allow all** gives the account every app, including ones added later.
- Greyed-out boxes are ones you can't change:
  - `super`'s row (always everything) and your own row;
  - accounts that hold permissions you don't;
  - apps you can't open yourself (you can't hand out what you can't use).

## 3. Switch an app off for everyone
The **Switch an app off for everyone** table has an On/Off switch per app. Off hides the
app and blocks its requests for every account except `super`. Handy for "nobody uses
Transfers for now". Each app also shows how many active accounts can open it.

If you switch off the App manager itself, only `super` can open it to switch it back on.

## Good to know
- Every change is in the audit log (`apps.account`, `apps.switch`).
- An account that loses an app keeps its other windows; the lost one isn't reopened from
  their saved layout.
- Details: [API]({{ site.baseurl }}/reference/api#apps), [Security]({{ site.baseurl }}/reference/security#apps).
