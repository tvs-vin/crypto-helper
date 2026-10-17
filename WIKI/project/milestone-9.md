---
title: Milestone 9 plan
---

# Milestone 9: notifications

Agreed with the owner on 2026-10-17. Four parts, reported one by one. The old wrap-up
milestone (README, `.env.example`) is now milestone 10.

| Part | Status |
|---|---|
| 9a. Notification centre, sending by hand, live delivery | Planned |
| 9b. Discord webhooks | Planned |
| 9c. Automatic: security events and system health | Planned |
| 9d. Price alerts (the start of the track-and-alert bot job) | Planned |

Owner's answers: channels **in-app + Discord webhook**; sending by hand needs a new permission
(`notifications.send`); automatic **security events, system health and price alerts**; each person
chooses **per category and channel**.

## 9a: the notification centre
- Stored per user (title, text, category, level, optional link to a window, read or not), kept
  for a while (e.g. 90 days / 500 each).
- A bell in the taskbar with the unread count; a Notifications window to read, mark read, clear.
- Live while signed in (a server-sent event stream with the same session checks as the API), so a
  notification shows as a toast within seconds.
- `notifications.send`: send to one user or everyone (in the admin preset). Audited.
- Each person's settings: per category (security, system, prices, messages) and per channel
  (in-app, Discord), plus quiet hours for outside channels. Security alerts to admins can't be
  switched off entirely.
- Not yet: pop-up notifications from the browser or the OS. Browsers only allow them over HTTPS
  (and NetBird access here is plain HTTP); parked with passkeys until HTTPS.

## 9b: Discord
- Each person can add their own Discord webhook (Settings). The webhook address is a secret
  (anyone who has it can post there): stored encrypted, never shown again in full, never logged.
- Only Discord's own webhook addresses are accepted. Sent in the background with retries and
  Discord's rate limits respected; a Test button.
- What goes out is the title and short text: no balances or amounts unless the person turns that
  on (like embeds).

## 9c: automatic notifications
- Security: a sign-in from a new device or address, password changed, 2FA turned off, account
  locked, recovery code used. To the account itself, and the important ones to admins.
- System health: backup failed or overdue, an update is available, a service stopped or keeps
  restarting, the self-test failed, disk getting full, prices not updating. To admins.

## 9d: price alerts
- Your own rules: a coin goes above or below a price, or moves more than N% in 24 hours, in your
  currency. Checked whenever prices update. Each rule fires once and then re-arms when the price
  crosses back (no floods); practice prices never fire real alerts.
- Shown and edited from the Overview window.
