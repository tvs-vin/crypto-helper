---
title: Getting started
---

# Getting started

> An installable service (`install.sh`, systemd, `crypto-helper service …`) is coming in
> milestone 3b. Until then, run it from the repository as below.

## 1. Install
Needs Python 3.12+.
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .          # puts the crypto-helper command in .venv/bin
```

## 2. Run
```bash
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```
On start the server applies any pending [database migrations]({{ site.baseurl }}/reference/database-migrations)
and, the first time, creates an encryption key at `~/.config/crypto-helper/secret.key`.
**Back that key up**: without it, 2FA secrets can't be read
(see [Configuration]({{ site.baseurl }}/reference/configuration#secret-key)).

The server only listens on `127.0.0.1`. To use it from another computer, tunnel it:
```bash
ssh -L 8000:127.0.0.1:8000 <user>@<vm>     # then open http://localhost:8000
```
Never expose the port directly to the internet.

## 3. Create the `super` account
On first launch the server makes a one-time setup token. Show it with:
```bash
.venv/bin/crypto-helper setup token
```
Then send it with a password of 12 or more characters:
```bash
curl -X POST localhost:8000/api/setup -H 'X-Requested-With: fetch' \
  -H 'content-type: application/json' -d '{"token":"<token>","password":"<password>"}'
```
The token stops working once `super` exists.

## 4. Turn on 2FA
Strongly recommended for `super`: [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa).

## 5. Check it works
```bash
.venv/bin/pytest                 # unit tests
.venv/bin/crypto-helper test     # end-to-end tests against a throwaway server
```
