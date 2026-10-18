---
title: Set up 2FA
---

# Set up 2FA (two-factor login)

With 2FA on, logging in needs your password **and** a 6-digit code from an app on your
phone. Someone who learns your password still can't get in.

It costs nothing and needs no outside service: your phone and the server each work out
the code from a shared secret and the current time.

## In the web app (easiest)
1. Install an authenticator app (list below).
2. **Settings → Account → Turn on two-factor login.**
3. Scan the QR code with the app (or type the setup key shown next to it).
4. Type the 6-digit code the app shows and your password (asked again to make sure it's you),
   and press **Confirm**.
5. **Save the 10 recovery codes** it shows (Copy all or Download .txt). They're shown once.

The rest of this page does the same with `curl`.

## 1. Install an authenticator app
Any of these work: **Aegis** (Android, open source), **Ente Auth** (iOS/Android/desktop,
open source), **2FAS**, **Bitwarden Authenticator**, **Google** or **Microsoft
Authenticator**, or **KeePassXC** on a computer.

## 2. Start setup
While logged in:
```bash
curl -b jar -X POST localhost:8000/api/auth/totp/setup -H 'X-Requested-With: fetch'
```
You get back a `secret` (32 letters and digits) and an `otpauth_uri`. In the app, choose
**add account → enter a setup key**, give it a name, and paste the `secret`. (Scanning a QR
code comes with the web UI in milestone 6.)

2FA is **not on yet**: the next step proves your app has the right secret.

## 3. Confirm with a code
```bash
curl -b jar -X POST localhost:8000/api/auth/totp/enable -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"code":"123456","password":"<your password>"}'
```
Use the code currently shown in the app. If it's refused, check your phone's time is set
automatically and try the newest code.

## 4. Save your recovery codes
The answer contains **10 recovery codes**. They are shown **only this once**. Print them or
put them in a password manager, somewhere other than your phone. See
[Recovery codes]({{ site.baseurl }}/guides/recovery-codes).

Turning 2FA on signs out your other sessions.

## Logging in from now on
Send the code as `totp` with your username and password:
```bash
curl -c jar -X POST localhost:8000/api/auth/login -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' \
  -d '{"username":"super","password":"…","totp":"123456"}'
```
- Without a code you get `401 {"detail": "2FA code required", "totp_required": true}`.
- Each code works **once**. If you just used one, wait for the next.
- Wrong codes count toward the 5-strike lockout.

## Turning 2FA off
```bash
curl -b jar -X POST localhost:8000/api/auth/totp/disable -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"password":"…"}'
```
This also deletes your recovery codes.
