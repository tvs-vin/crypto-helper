---
title: Notifications
---

# Notifications

The app can tell you about things: a message from an admin, and (from milestone 9c and 9d)
security events, system problems and your price alerts. You get them in the app and, if you
want, in a Discord channel.

## 1. Read them
- The **bell** in the taskbar shows how many are unread. Click it to open the
  **Notifications** window (also under **Windows**).
- New ones also pop up in the corner for a few seconds while you're signed in, without
  reloading anything. If the connection drops, the app reconnects by itself.
- In the window: **Unread** shows only unread ones; **Open …** jumps to the window a
  notification is about; **Mark read**, **Delete**, **Mark all read**, **Clear read**.
- They're kept 90 days, and at most 500 per person (the oldest go first).

## 2. Choose what you get
**Settings → Notifications** has a row per kind and a column per place:

| Kind | What it's about |
|---|---|
| Security | Your account: new sign-ins, password or 2FA changes, lockouts |
| System | Backups, updates, services, the self-test (admins only) |
| Price alerts | Your own price alerts |
| Messages | Notifications sent by admins |

Tick **In the app** and/or **Discord** for each. It saves at once. Admins (super, or anyone
with `users.manage`) always get Security in the app: that box can't be unticked.

## 3. Get them on Discord (optional)
A Discord *webhook* is an address that lets something post into one channel of a server.

1. In Discord, open the channel's settings → **Integrations** → **Webhooks** →
   **New Webhook**. Give it a name and, ideally, use a private channel only you can see.
2. **Copy Webhook URL**.
3. In **Settings → Notifications → Discord**, paste it and press **Save webhook**.
4. Press **Send a test**. A message titled "Crypto Helper is connected" should appear in the
   channel. If it doesn't, the reason shows under the webhook.
5. Tick **Discord** for the kinds you want there.

Good to know:
- **The webhook address is a password.** Anyone who has it can post into that channel. The
  app stores it encrypted and only ever shows its last few characters. Don't paste it in chat.
  If it leaks, delete the webhook in Discord and add a new one.
- Only real Discord webhook addresses are accepted.
- Nothing posted on Discord ever pings anyone (`@everyone` in a title stays plain text).
- Discord gets the title and the short text, never your balances or wallet values.
- If Discord is down or busy, the app tries again for a while (6 tries, waiting longer each
  time) and respects Discord's rate limits. If the webhook was deleted in Discord, it stops
  at once and shows **problem** in Settings.
- **Remove** forgets the webhook here. It doesn't delete it in Discord.

## 4. Quiet hours (optional)
Under **Quiet hours**, pick **From** and **To** (for example 22:00 to 07:00). During those
hours, Discord messages wait and go out when quiet hours end. Critical ones still go out
straight away. In-app notifications aren't held back (they're silent anyway).

Times are in the time zone of the browser you set them from. If you travel, set them again.

## 5. Send one (admins)
Needs the `notifications.send` permission (part of the admin preset).

1. Open the **Notifications** window. Below your list is **Send a notification**.
2. **To**: one person, or **Everyone**.
3. **Level**: Info, Warning or Critical. **Title** (up to 120 characters), an optional
   **Message**, and an optional **Button** that opens a window (for example Services).
4. **Send**. The pop-up says how many people got it: anyone who turned Messages off doesn't.

Every send is in the audit log. Text that looks like a recovery phrase or private key is refused.

Not yet: notifications from the browser or the operating system when the app isn't open.
Browsers only allow those over HTTPS. That's parked with passkeys until HTTPS is set up.
