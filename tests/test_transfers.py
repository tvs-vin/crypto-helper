import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import wallets as svc
from app.config import Settings
from app.main import create_app
from app.models import AuditLog, Holding, Transfer
from tests.conftest import PASSWORD, H
from tests.wallet_helpers import amounts, hold, send, user_with, wallet


def two_paper(client, btc="1"):
    a, b = wallet(client, "A"), wallet(client, "B")
    hold(client, a["id"], "BTC", btc)
    return a["id"], b["id"]


# ---- permissions -------------------------------------------------------------------------


def test_transfer_permissions(logged_in, app):
    a, b = two_paper(logged_in)
    viewer = user_with(app, logged_in, "viewer1", ["wallets.view"])
    mover = user_with(app, logged_in, "mover", ["transfers.create"])
    assert send(TestClient(app), a, b, "BTC", "0.1").status_code == 401
    assert send(viewer, a, b, "BTC", "0.1").status_code == 403
    assert viewer.get("/api/transfers").status_code == 200
    assert mover.get("/api/transfers").status_code == 403
    assert send(mover, a, b, "BTC", "0.1").status_code == 201


# ---- the happy path ----------------------------------------------------------------------


def test_transfer_moves_exact_amounts_and_is_labelled_simulated(logged_in, app):
    a, b = two_paper(logged_in, "1")
    r = send(logged_in, a, b, "BTC", "0.1", note="testing")
    assert r.status_code == 201
    t = r.json()
    assert t["simulated"] is True and t["label"] == "Simulated, no real funds move"
    assert t["amount"] == "0.1" and t["username"] == "super" and t["note"] == "testing"
    send(logged_in, a, b, "BTC", "0.2")
    assert amounts(logged_in, a) == {"BTC": "0.7"}  # exact: no 0.7000000000000001
    assert amounts(logged_in, b) == {"BTC": "0.3"}
    with app.state.session_factory() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "transfer")).all()) == 2


def test_sending_everything_removes_the_holding(logged_in):
    a, b = two_paper(logged_in, "0.000000000000000001")
    assert send(logged_in, a, b, "BTC", "0.000000000000000001").status_code == 201
    assert amounts(logged_in, a) == {}
    assert amounts(logged_in, b) == {"BTC": "0.000000000000000001"}


# ---- refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "status", "fragment"),
    [
        ("2", 409, "not enough"),
        ("0", 422, "more than zero"),
        ("-1", 422, "never negative"),
        (0.5, 422, "as text"),
        ("1e-3", 422, "plain numbers"),
    ],
)
def test_amount_refusals(logged_in, amount, status, fragment):
    a, b = two_paper(logged_in, "1")
    r = send(logged_in, a, b, "BTC", amount)
    assert r.status_code == status and fragment in r.text, r.text
    assert amounts(logged_in, a) == {"BTC": "1"} and amounts(logged_in, b) == {}


def test_same_wallet_refused(logged_in):
    a, _ = two_paper(logged_in)
    assert send(logged_in, a, a, "BTC", "0.1").status_code == 422


def test_coin_you_dont_have(logged_in):
    a, b = two_paper(logged_in)
    r = send(logged_in, a, b, "ETH", "1")
    assert r.status_code == 409 and "has 0 ETH" in r.text


def test_missing_wallet(logged_in):
    a, _ = two_paper(logged_in)
    assert send(logged_in, a, 999, "BTC", "0.1").status_code == 404


def test_archived_wallets_cant_send_or_receive(logged_in):
    a, b = two_paper(logged_in)
    logged_in.patch(f"/api/wallets/{b}", json={"archived": True}, headers=H)
    r = send(logged_in, a, b, "BTC", "0.1")
    assert r.status_code == 409 and "archived" in r.text


def test_seed_phrase_in_note_refused(logged_in):
    from tests.wallet_helpers import SEED12

    a, b = two_paper(logged_in)
    r = send(logged_in, a, b, "BTC", "0.1", note=SEED12)
    assert r.status_code == 422 and "abandon" not in r.text
    assert amounts(logged_in, a) == {"BTC": "1"}


# ---- networks ----------------------------------------------------------------------------


def test_onchain_to_onchain_needs_same_network(logged_in):
    eth = wallet(logged_in, "ETH main", kind="onchain", network="ethereum")
    sol = wallet(logged_in, "SOL main", kind="onchain", network="solana")
    eth2 = wallet(logged_in, "ETH cold", kind="onchain", network="ethereum")
    hold(logged_in, eth["id"], "USDC", "100")
    r = send(logged_in, eth["id"], sol["id"], "USDC", "10")
    assert r.status_code == 409 and "bridge" in r.text
    assert amounts(logged_in, eth["id"]) == {"USDC": "100"}
    r = send(logged_in, eth["id"], eth2["id"], "USDC", "10")
    assert r.status_code == 201 and r.json()["network"] == "ethereum" and not r.json()["warnings"]


def test_exchange_withdrawal_must_target_a_network_the_coin_lives_on(logged_in):
    cb = wallet(logged_in, "Coinbase", kind="exchange")
    hold(logged_in, cb["id"], "BTC", "1")
    eth = wallet(logged_in, "ETH main", kind="onchain", network="ethereum")
    btc = wallet(logged_in, "BTC cold", kind="onchain", network="bitcoin")
    r = send(logged_in, cb["id"], eth["id"], "BTC", "0.1")
    assert r.status_code == 409 and "WBTC" in r.text
    r = send(logged_in, cb["id"], btc["id"], "BTC", "0.1")
    assert r.status_code == 201
    assert (
        r.json()["network"] == "bitcoin" and "deposit or withdrawal page" in r.json()["warnings"][0]
    )


def test_deposit_to_exchange_warns(logged_in):
    sol = wallet(logged_in, "Phantom", kind="onchain", network="solana")
    hold(logged_in, sol["id"], "SOL", "5")
    kraken = wallet(logged_in, "Kraken", kind="exchange")
    r = send(logged_in, sol["id"], kraken["id"], "SOL", "1")
    assert r.status_code == 201 and r.json()["network"] == "solana" and r.json()["warnings"]


# ---- history -----------------------------------------------------------------------------


def test_history_newest_first_paging_and_wallet_filter(logged_in):
    a, b = two_paper(logged_in, "10")
    c = wallet(logged_in, "C")["id"]
    for _ in range(3):
        send(logged_in, a, b, "BTC", "1")
    send(logged_in, a, c, "BTC", "1")
    rows = logged_in.get("/api/transfers").json()
    assert [r["to_wallet_name"] for r in rows] == ["C", "B", "B", "B"]
    page = logged_in.get(f"/api/transfers?limit=2&before_id={rows[1]['id']}").json()
    assert [r["id"] for r in page] == [rows[2]["id"], rows[3]["id"]]
    assert len(logged_in.get(f"/api/transfers?wallet_id={c}").json()) == 1


def test_history_keeps_names_after_rename_and_delete(logged_in):
    a, b = two_paper(logged_in, "1")
    send(logged_in, a, b, "BTC", "1")
    logged_in.patch(f"/api/wallets/{a}", json={"name": "Renamed"}, headers=H)
    logged_in.delete(f"/api/wallets/{a}", headers=H)  # now empty, so it deletes
    t = logged_in.get("/api/transfers").json()[0]
    assert t["from_wallet_name"] == "A" and t["from_wallet_id"] is None


# ---- deleting wallets that hold coins ----------------------------------------------------


def test_delete_empty_wallet(logged_in, app):
    w = wallet(logged_in, "Empty")
    assert logged_in.delete(f"/api/wallets/{w['id']}", headers=H).status_code == 204
    with app.state.session_factory() as db:
        assert db.scalars(select(AuditLog).where(AuditLog.action == "wallet.delete")).one()


def test_delete_with_holdings_refused_with_options(logged_in):
    a, _ = two_paper(logged_in, "1")
    r = logged_in.delete(f"/api/wallets/{a}", headers=H)
    assert r.status_code == 409
    body = r.json()
    assert body["holdings"] == [{"symbol": "BTC", "amount": "1"}]
    assert set(body["options"]) == {"move_to", "force", "archive"}
    assert amounts(logged_in, a) == {"BTC": "1"}


def test_delete_moving_everything_first(logged_in):
    a, b = two_paper(logged_in, "1")
    hold(logged_in, a, "ETH", "2")
    hold(logged_in, b, "BTC", "0.5")
    assert logged_in.delete(f"/api/wallets/{a}?move_to={b}", headers=H).status_code == 204
    assert amounts(logged_in, b) == {"BTC": "1.5", "ETH": "2"}
    notes = {t["note"] for t in logged_in.get("/api/transfers").json()}
    assert notes == {"Moved before deleting wallet A"}


def test_move_is_all_or_nothing_across_networks(logged_in):
    cb = wallet(logged_in, "Coinbase", kind="exchange")
    hold(logged_in, cb["id"], "BTC", "1")
    hold(logged_in, cb["id"], "ETH", "1")
    eth = wallet(logged_in, "ETH main", kind="onchain", network="ethereum")
    r = logged_in.delete(f"/api/wallets/{cb['id']}?move_to={eth['id']}", headers=H)
    assert r.status_code == 409 and "nothing was moved" in r.text
    assert any(p.startswith("BTC:") for p in r.json()["problems"])
    assert amounts(logged_in, cb["id"]) == {"BTC": "1", "ETH": "1"}
    assert amounts(logged_in, eth["id"]) == {}


def test_forced_delete_needs_the_exact_name(logged_in, app):
    a, _ = two_paper(logged_in, "1")
    for bad in ("", "a", "A "):
        r = logged_in.delete(f"/api/wallets/{a}?force=true&confirm_name={bad}", headers=H)
        assert r.status_code == 409
    assert (
        logged_in.delete(f"/api/wallets/{a}?force=true&confirm_name=A", headers=H).status_code
        == 204
    )
    with app.state.session_factory() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.action == "wallet.delete")).one()
        assert db.scalar(select(Holding)) is None
    assert "FORCED" in row.detail and "1 BTC" in row.detail


# ---- atomicity and concurrency -----------------------------------------------------------


def test_crash_mid_transfer_changes_nothing(logged_in, app, monkeypatch):
    a, b = two_paper(logged_in, "1")

    def explode(*args, **kwargs):
        raise RuntimeError("power cut between the debit and the record")

    monkeypatch.setattr(svc, "Transfer", explode)
    crashy = TestClient(app, raise_server_exceptions=False)
    crashy.cookies = logged_in.cookies
    assert send(crashy, a, b, "BTC", "0.4").status_code == 500
    monkeypatch.undo()
    assert amounts(logged_in, a) == {"BTC": "1"} and amounts(logged_in, b) == {}
    with app.state.session_factory() as db:
        assert db.scalar(select(Transfer)) is None


def test_two_transfers_at_once_cannot_overspend(tmp_path, monkeypatch):
    """Two requests each try to send 8 of 10 BTC at the same moment. The write lock taken
    before the balance check must make the second one see the first one's result."""
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/race.db", _env_file=None))
    with TestClient(app) as admin:
        admin.post(
            "/api/setup", json={"token": app.state.setup_token, "password": PASSWORD}, headers=H
        )
        admin.post("/api/auth/login", json={"username": "super", "password": PASSWORD}, headers=H)
        a, b = two_paper(admin, "10")
        c = wallet(admin, "C")["id"]

        first_checked, second_checked = threading.Event(), threading.Event()

        def hold_the_door():
            # The first transfer to pass its balance check waits here so the other one has
            # every chance to read the same old balance (it can't, if the lock works).
            if not first_checked.is_set():
                first_checked.set()
                second_checked.wait(timeout=1.5)
            else:
                second_checked.set()

        monkeypatch.setattr(svc, "_after_balance_check", hold_the_door)
        results = {}

        def go(dst, key):
            c_ = TestClient(app)
            c_.cookies = admin.cookies
            results[key] = send(c_, a, dst, "BTC", "8").status_code

        threads = [
            threading.Thread(target=go, args=(b, "b")),
            threading.Thread(target=go, args=(c, "c")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert sorted(results.values()) == [201, 409], results
        total = sum(float(v) for w in (a, b, c) for v in amounts(admin, w).values())
        assert total == 10 and amounts(admin, a) == {"BTC": "2"}


def test_begin_immediate_really_takes_the_write_lock(tmp_path):
    """Directly prove the SQLite transaction recipe: a second writer must wait."""
    import sqlite3
    import time

    from app.db import begin_immediate, make_engine, make_session_factory
    from app.migrate import upgrade

    engine = make_engine(f"sqlite:///{tmp_path}/lock.db")
    upgrade(engine)
    db = make_session_factory(engine)()
    begin_immediate(db)
    other = sqlite3.connect(tmp_path / "lock.db", timeout=0.2, isolation_level=None)
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        other.execute("BEGIN IMMEDIATE")
    assert time.monotonic() - started >= 0.15
    db.rollback()
    other.execute("BEGIN IMMEDIATE")  # free again once released
    other.execute("ROLLBACK")
    other.close()
    db.close()


def test_archived_source_cant_send(logged_in):
    """Each side is checked: archiving only the sender must block the transfer too."""
    a, b = two_paper(logged_in)
    logged_in.patch(f"/api/wallets/{a}", json={"archived": True}, headers=H)
    r = send(logged_in, a, b, "BTC", "0.1")
    assert r.status_code == 409 and "send from it" in r.text
    assert amounts(logged_in, a) == {"BTC": "1"}
