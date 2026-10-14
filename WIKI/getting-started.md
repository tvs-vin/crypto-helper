---
title: Getting started
---

# Getting started

## Requirements
Python 3.12+ (Node 20 is only used later to syntax-check the frontend).

## Install
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run
```bash
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```
The server binds to `127.0.0.1` on purpose. To use it from another computer, tunnel it:
```bash
ssh -L 8000:127.0.0.1:8000 <vm>     # then open http://localhost:8000
```
Never expose the port directly to the internet.

## First launch
With an empty database the server prints a **one-time setup token** to its console.
Send it with a chosen password (12+ characters) to `POST /api/setup` to create the
`super` user. There is no default password. Setup is impossible once any user exists.

## Configuration
Environment variables (prefix `BOT_`), or a `.env` file that is never committed:

| Variable | Default | Meaning |
|---|---|---|
| `BOT_DATABASE_URL` | `sqlite:///data/bot.db` | Database location |
| `BOT_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `BOT_SESSION_HOURS` | `12` | Session lifetime |
| `BOT_MAX_FAILED_LOGINS` | `5` | Failures before lockout |
| `BOT_LOCKOUT_MINUTES` | `15` | Lockout length |
| `BOT_PRICE_PROVIDER` | `coingecko` | `coingecko` or `mock` |

## Test and lint
```bash
.venv/bin/pytest
.venv/bin/ruff check .
```
