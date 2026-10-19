"""11d: the trade log. Importing (Demo exchange), listing, the five CSV formats, the rules."""

import csv
import io

import pytest
from sqlalchemy import select

from app import tax_csv
from app.models import Trade
from app.sync import demo
from tests.conftest import H
from tests.test_sync import synced_wallet
from tests.wallet_helpers import user_with


@pytest.fixture(autouse=True)
def fresh_demo(monkeypatch):
    monkeypatch.setattr(demo, "BALANCES", dict(demo.BALANCES))
    monkeypatch.setattr(demo, "TRADES", list(demo.TRADES))


def synced(c, name="Demo account"):
    w, conn = synced_wallet(c, name)
    out = c.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert out["ok"], out
    return w, conn


def export(c, fmt, **q):
    r = c.get("/api/trades/export", params={"format": fmt, **q})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert f"trades-{fmt}-" in r.headers["content-disposition"]
    return list(csv.reader(io.StringIO(r.text)))


# ---- importing -------------------------------------------------------------------------------


def test_sync_imports_trades_once(logged_in, app):
    w, _ = synced(logged_in)
    trades = logged_in.get("/api/trades").json()
    assert trades["total"] == 3
    newest = trades["trades"][0]
    assert (newest["side"], newest["base"], newest["quote"], newest["amount"]) == (
        "sell",
        "ETH",
        "USD",
        "0.75",
    )
    oldest = trades["trades"][-1]
    assert oldest["base"] == "BTC" and oldest["total"] == "20000"  # XBT -> BTC, exact total
    assert (
        logged_in.get("/api/audit?q=trades.import").json()[0]["detail"].endswith("3 new trade(s)")
    )
    # The exchange sending everything again (a reset position, overlapping pages): kept once.
    from app.models import WalletSource

    with app.state.session_factory() as db:
        src = db.get(WalletSource, w["id"])
        src.options = {**src.options, "trades": {}}
        db.commit()
    assert logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()["ok"]
    assert logged_in.get("/api/trades").json()["total"] == 3
    # Again: nothing new; and a new trade on the exchange arrives once.
    logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H)
    demo.TRADES.append(("d4", "2026-04-01T00:00:00Z", "XBT", "USD", "sell", "0.1", "50000", "5"))
    out = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert out["sync"]["trades_at"] and out["sync"]["trades_error"] is None
    assert logged_in.get("/api/trades").json()["total"] == 4


def test_a_trade_problem_doesnt_stop_balances(logged_in, app):
    from tests.test_sync import connect

    w = logged_in.post(
        "/api/wallets", json={"name": "No trades", "kind": "exchange"}, headers=H
    ).json()
    conn = connect(logged_in, key="notrades-123456789").json()
    logged_in.put(
        f"/api/wallets/{w['id']}/source",
        json={"kind": "exchange", "connection_id": conn["id"]},
        headers=H,
    )
    out = logged_in.post(f"/api/wallets/{w['id']}/sync", headers=H).json()
    assert (
        out["ok"]
        and out["sync"]["trades_error"] == "The demo exchange says this key can't read trades"
    )
    assert logged_in.get("/api/trades").json()["total"] == 0


def test_one_account_one_wallet(logged_in):
    _, conn = synced(logged_in)
    other = logged_in.post(
        "/api/wallets", json={"name": "Second", "kind": "exchange"}, headers=H
    ).json()
    r = logged_in.put(
        f"/api/wallets/{other['id']}/source",
        json={"kind": "exchange", "connection_id": conn["id"]},
        headers=H,
    )
    assert r.status_code == 409 and "already syncs Demo account" in r.json()["detail"]


def test_trades_outlive_their_wallet(logged_in, app):
    w, _ = synced(logged_in)
    assert logged_in.delete(f"/api/wallets/{w['id']}", headers=H).status_code == 204
    with app.state.session_factory() as db:
        rows = db.scalars(select(Trade)).all()
        assert len(rows) == 3 and all(
            t.wallet_id is None and t.account == "Demo account" for t in rows
        )


# ---- reading ---------------------------------------------------------------------------------


def test_filters_and_paging(logged_in):
    synced(logged_in)

    def ids(**q):
        return [t["trade_id"] for t in logged_in.get("/api/trades", params=q).json()["trades"]]

    assert ids() == ["d3", "d2", "d1"]
    assert ids(asset="eth") == ["d3", "d2"]
    assert ids(side="buy") == ["d2", "d1"]
    assert ids(since="2026-02-10", until="2026-02-10") == ["d2"]  # the whole day
    first = logged_in.get("/api/trades", params={"limit": 1}).json()["trades"][0]
    assert ids(before_id=first["id"]) == ["d2", "d1"]
    assert logged_in.get("/api/trades", params={"asset": "B T C"}).status_code == 422


def test_needs_wallets_view_and_the_app(logged_in, app):
    nobody = user_with(app, logged_in, "nobody", ["prices.view"])
    assert nobody.get("/api/trades").status_code == 403
    assert nobody.get("/api/trades/export?format=generic").status_code == 403
    viewer = user_with(app, logged_in, "viewer", ["wallets.view"])
    assert viewer.get("/api/trades").status_code == 200
    vid = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "viewer")
    logged_in.put(f"/api/apps/accounts/{vid}", json={"apps": ["wallets"]}, headers=H)
    assert viewer.get("/api/trades").status_code == 403


# ---- the CSV formats -------------------------------------------------------------------------


def test_every_format_has_the_official_header(logged_in):
    synced(logged_in)
    for fmt in tax_csv.FORMATS:
        rows = export(logged_in, fmt)
        assert rows[0] == tax_csv.HEADERS[fmt] and len(rows) == 4, fmt
        assert all(len(r) == len(rows[0]) for r in rows), fmt
    # The headers, exactly as the tools' own templates have them.
    assert tax_csv.HEADERS["turbotax"] == [
        "Date",
        "Type",
        "Sent Asset",
        "Sent Amount",
        "Received Asset",
        "Received Amount",
        "Fee Asset",
        "Fee Amount",
        "Market Value Currency",
        "Market Value",
        "Description",
        "Transaction Hash",
        "Transaction ID",
    ]
    assert ",".join(tax_csv.HEADERS["coinledger"]) == (
        "Date (UTC),Platform (Optional),Asset Sent,Amount Sent,Asset Received,Amount Received,"
        "Fee Currency (Optional),Fee Amount (Optional),Type,Description (Optional),"
        "TxHash (Optional)"
    )


def by_id(rows, column, value):
    head = rows[0]
    return next(dict(zip(head, r, strict=True)) for r in rows[1:] if value in r[head.index(column)])


def test_turbotax_rows(logged_in):
    synced(logged_in)
    rows = export(logged_in, "turbotax")
    buy = by_id(rows, "Transaction ID", "d1")
    assert buy == {
        "Date": "2026-01-05 10:00:00",
        "Type": "Buy",
        "Sent Asset": "USD",
        "Sent Amount": "20000",
        "Received Asset": "BTC",
        "Received Amount": "0.5",
        "Fee Asset": "USD",
        "Fee Amount": "20",
        "Market Value Currency": "USD",
        "Market Value": "20020",
        "Description": "Demo exchange trade d1",
        "Transaction Hash": "",
        "Transaction ID": "d1",
    }
    sale = by_id(rows, "Transaction ID", "d3")
    assert (
        sale["Type"],
        sale["Sent Asset"],
        sale["Sent Amount"],
        sale["Received Asset"],
        sale["Received Amount"],
        sale["Market Value"],
    ) == ("Sale", "ETH", "0.75", "USD", "1875", "1873.125")  # fee taken off


def test_turbotax_converts_and_eight_decimals(logged_in):
    demo.TRADES[:] = [
        ("c1", "2026-05-01T12:00:00Z", "ETH", "BTC", "buy", "1.123456789", "0.05", "0.000000015")
    ]
    synced(logged_in)
    row = by_id(export(logged_in, "turbotax"), "Transaction ID", "c1")
    assert row["Type"] == "Convert" and row["Market Value"] == ""
    assert row["Received Amount"] == "1.12345679"  # rounded to 8 decimals for TurboTax
    assert row["Fee Amount"] == "0.00000002"
    generic = by_id(export(logged_in, "generic"), "trade_id", "c1")
    assert generic["amount"] == "1.123456789" and generic["fee"] == "0.000000015"  # exact


def test_coinledger_cointracker_koinly_rows(logged_in):
    synced(logged_in)
    cl = by_id(export(logged_in, "coinledger"), "Description (Optional)", "trade d1")
    assert (
        cl["Date (UTC)"],
        cl["Platform (Optional)"],
        cl["Asset Sent"],
        cl["Amount Sent"],
        cl["Asset Received"],
        cl["Amount Received"],
        cl["Type"],
    ) == ("01/05/2026 10:00:00", "Demo exchange", "USD", "20000", "BTC", "0.5", "Trade")
    ct = export(logged_in, "cointracker")
    sell = next(dict(zip(ct[0], r, strict=True)) for r in ct[1:] if r[0].startswith("03/15/2026"))
    assert (
        sell["Received Quantity"],
        sell["Received Currency"],
        sell["Sent Quantity"],
        sell["Sent Currency"],
        sell["Tag"],
    ) == ("1875", "USD", "0.75", "ETH", "")
    ko = by_id(export(logged_in, "koinly"), "Description", "trade d2")
    assert (
        ko["Date"],
        ko["Sent Amount"],
        ko["Sent Currency"],
        ko["Received Amount"],
        ko["Received Currency"],
        ko["Fee Amount"],
        ko["Fee Currency"],
        ko["Net Worth Amount"],
    ) == ("2026-02-10 15:30:00", "6000", "USD", "3", "ETH", "6", "USD", "")


def test_export_is_filtered_audited_and_safe_in_spreadsheets(logged_in, app):
    synced(logged_in, "=HYPERLINK(evil)")
    rows = export(logged_in, "generic", since="2026-02-01")
    assert len(rows) == 3  # the January trade filtered out
    assert all(r[2] == "'=HYPERLINK(evil)" for r in rows[1:])  # not a formula in Excel
    entry = logged_in.get("/api/audit?q=trades.export").json()[0]
    assert entry["detail"] == "Generic CSV: 2 trade(s)"
    assert logged_in.get("/api/trades/export?format=nope").status_code == 422


def test_formats_list(logged_in):
    got = {f["id"]: f["name"] for f in logged_in.get("/api/trades/formats").json()}
    assert got == {
        "generic": "Generic CSV",
        "koinly": "Koinly",
        "cointracker": "CoinTracker",
        "coinledger": "CoinLedger",
        "turbotax": "TurboTax",
    }
