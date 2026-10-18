"""Realistic demo data for a spawned server: five wallets across networks, a transfer, a
watchlist and a day of BTC price history (used by the browser tests and screenshots)."""

import json
import math
import random
import sqlite3
import urllib.request
from datetime import UTC, datetime, timedelta

# A well-known test phrase (it holds nothing); used to check the guard in the browser.
SEED_PHRASE_FREE = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


def call(base, method, path, body=None, cookie=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Requested-With": "fetch",
            **({"Cookie": cookie} if cookie else {}),
        },
    )
    with urllib.request.urlopen(req) as r:
        return r.headers, json.loads(r.read() or b"null")


def seed(srv):
    base = srv.base_url
    h, _ = call(base, "POST", "/api/auth/login", {"username": "super", "password": srv.password})
    ck = h["set-cookie"].split(";")[0]
    W = {}
    for body, holds in [
        (
            {
                "name": "Coinbase main",
                "nickname": "Coinbase",
                "kind": "exchange",
                "provider": "Coinbase",
                "tags": ["trading"],
                "color_primary": "#2f6bff",
            },
            {"BTC": "0.4215", "ETH": "3.1", "USDC": "1250"},
        ),
        (
            {
                "name": "Ledger BTC",
                "nickname": "Cold storage",
                "kind": "onchain",
                "network": "bitcoin",
                "provider": "Ledger",
                "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
                "tags": ["long-term", "hardware"],
                "color_primary": "#e8a33b",
                "color_scheme": "shade",
            },
            {"BTC": "1.05"},
        ),
        (
            {
                "name": "MetaMask",
                "nickname": "Everyday ETH",
                "kind": "onchain",
                "network": "ethereum",
                "provider": "MetaMask",
                "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
                "tags": ["defi"],
            },
            {"ETH": "0.85", "USDC": "320.5", "LINK": "44"},
        ),
        (
            {
                "name": "Phantom",
                "kind": "onchain",
                "network": "solana",
                "provider": "Phantom",
                "color_primary": "#9c5cff",
                "color_scheme": "complementary",
            },
            {"SOL": "12.5", "USDC": "75"},
        ),
        (
            {
                "name": "Practice",
                "nickname": "Paper portfolio",
                "kind": "paper",
                "tags": ["testing"],
            },
            {"DOGE": "5000", "ADA": "800"},
        ),
    ]:
        _, w = call(base, "POST", "/api/wallets", body, ck)
        W[w["name"]] = w["id"]
        for sym, amt in holds.items():
            call(base, "PUT", f"/api/wallets/{w['id']}/holdings/{sym}", {"amount": amt}, ck)
    call(
        base,
        "POST",
        "/api/transfers",
        {
            "from_wallet_id": W["Coinbase main"],
            "to_wallet_id": W["Ledger BTC"],
            "symbol": "BTC",
            "amount": "0.05",
            "note": "Move to cold storage",
        },
        ck,
    )
    call(base, "PATCH", "/api/me/preferences", {"watchlist": ["BTC", "ETH", "SOL", "DOGE"]}, ck)
    db = sqlite3.connect(f"{srv.tmp.name}/tester.db")
    now = datetime.now(UTC).replace(tzinfo=None)
    price = 81000.0
    random.seed(7)
    for i in range(144, -1, -1):
        price *= 1 + random.gauss(0, 0.004) + 0.0002 * math.sin(i / 9)
        db.execute(
            "insert into price_points (coingecko_id, fiat, at, price, change_24h)"
            " values (?,?,?,?,?)",
            (
                "bitcoin",
                "usd",
                (now - timedelta(minutes=10 * i)).isoformat(sep=" "),
                f"{price:.2f}",
                "-1.2",
            ),
        )
    db.commit()
    db.close()
    return ck, W
