---
title: Recovery codes
---

# Recovery codes

When you turn on [2FA]({{ site.baseurl }}/guides/set-up-2fa) you get 10 recovery codes like
`k7m2x-9pqrt`. Each one can stand in for an authenticator code **once**.

## Using one
Lost or broke your phone? Log in as usual and put a recovery code in the `totp` field:
```json
{"username": "super", "password": "…", "totp": "k7m2x-9pqrt"}
```
Capitals and the dash don't matter. The code is then used up. `GET /api/auth/me` shows how
many you have left in `recovery_codes_left`.

After using one, set up your new phone: turn 2FA off and on again (this gives you a new set
of codes too).

## Getting a new set
If you're running low, or think someone saw them:
```bash
curl -b jar -X POST localhost:8000/api/auth/totp/recovery-codes -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"password":"…"}'
```
All old codes stop working immediately.

## Lost the phone *and* the codes
Someone with shell access to the VM can turn 2FA off for any account, including `super`:
```bash
crypto-helper account <name> 2fa reset
```
See [CLI]({{ site.baseurl }}/reference/cli). The reset is written to the audit log.

## Keeping them safe
- Store them away from your phone: printed, or in a password manager.
- They're stored on the server only as hashes, so the server can't show them to you again.
- They keep working even if the server's encryption key is lost, which makes them your
  fallback in that case too.
