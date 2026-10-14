from fastapi.testclient import TestClient

from tests.conftest import H
from tests.test_users import as_user, create

ETH_ADDR = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
SEED12 = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
)


def wallet(client, name, kind="paper", **extra):
    r = client.post("/api/wallets", json={"name": name, "kind": kind, **extra}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def hold(client, wallet_id, symbol, amount):
    r = client.put(
        f"/api/wallets/{wallet_id}/holdings/{symbol}", json={"amount": amount}, headers=H
    )
    assert r.status_code == 200, r.text
    return r.json()


def send(client, src, dst, symbol, amount, **extra):
    return client.post(
        "/api/transfers",
        json={
            "from_wallet_id": src,
            "to_wallet_id": dst,
            "symbol": symbol,
            "amount": amount,
            **extra,
        },
        headers=H,
    )


def amounts(client, wallet_id) -> dict:
    w = client.get(f"/api/wallets/{wallet_id}").json()
    return {h["symbol"]: h["amount"] for h in w["holdings"]}


def user_with(app, admin, name, perms) -> TestClient:
    create(admin, name, perms)
    return as_user(app, name)
