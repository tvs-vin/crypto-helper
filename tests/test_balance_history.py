"""11e: balance history. Recording (when, what, never with made-up or stale prices),
compaction to one a day, the wallet and portfolio series, and the rules."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import balance_history as bh
from app.models import BalancePoint, BalanceSnapshot
from app.prices.valuation import round_fiat
from app.routers import balance_history as bh_router
from tests.conftest import H
from tests.wallet_helpers import hold, user_with, wallet


class Clock:
    """The job's and the API's idea of now, moved by hand."""

    def __init__(self, monkeypatch):
        self.now = datetime.now().replace(microsecond=0) + timedelta(seconds=1)
        monkeypatch.setattr(bh, "utcnow", lambda: self.now)
        monkeypatch.setattr(bh_router, "utcnow", lambda: self.now)

    def __call__(self, **delta):
        self.now += timedelta(**delta)
        return self.now


@pytest.fixture
def clock(monkeypatch, logged_in):
    # The test clock runs on real UTC (wallets get their real creation time).
    from app.timeutil import utcnow

    c = Clock(monkeypatch)
    c.now = utcnow().replace(microsecond=0) + timedelta(seconds=1)
    return c


def tick(app):
    return app.state.balance_job.tick()


def price(app, coin_id, fiat="usd") -> Decimal:
    return app.state.prices.fresh(app.state.session_factory).quotes[coin_id][fiat].price


def count(app, model) -> int:
    with app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model))


# ---- recording -------------------------------------------------------------------------------


def test_records_every_wallet_with_its_value_in_every_currency(logged_in, app, clock):
    a = wallet(logged_in, "Cold")
    b = wallet(logged_in, "Hot")
    hold(logged_in, a["id"], "BTC", "0.5")
    hold(logged_in, b["id"], "ETH", "2")
    hold(logged_in, b["id"], "BTC", "0.25")
    clock(seconds=5)
    assert tick(app)["recorded"] == 3
    with app.state.session_factory() as db:
        pts = {(p.wallet_id, p.symbol): p for p in db.scalars(select(BalancePoint))}
    btc = pts[(a["id"], "BTC")]
    assert btc.amount == "0.5"
    assert set(btc.values) == {"usd", "eur", "gbp", "jpy", "cad", "aud"}
    assert btc.values["usd"] == round_fiat(Decimal("0.5") * price(app, "bitcoin"), "usd")
    assert btc.values["jpy"] == round_fiat(Decimal("0.5") * price(app, "bitcoin", "jpy"), "jpy")


def test_when_it_records(logged_in, app, clock):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    clock(seconds=5)
    assert tick(app)["recorded"] == 1  # the first one at once
    clock(minutes=1)
    assert tick(app)["recorded"] == 0  # nothing changed, not an hour yet
    hold(logged_in, w["id"], "BTC", "2")
    clock(minutes=2)
    assert tick(app)["recorded"] == 0  # changed, but changes wait 5 minutes after the last
    clock(minutes=3)
    assert tick(app)["recorded"] == 1  # now
    clock(minutes=30)
    assert tick(app)["recorded"] == 0
    clock(minutes=30)
    assert tick(app)["recorded"] == 1  # an hour since the last: on schedule
    wallet(logged_in, "Empty")  # a new wallet is a change too
    clock(minutes=6)
    assert tick(app)["recorded"] == 1
    assert count(app, BalanceSnapshot) == 4


def test_nothing_recorded_without_wallets_or_real_prices(logged_in, app, clock):
    assert tick(app) == {"skipped": "no wallets"}
    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    logged_in.put("/api/services/features", json={"practice_prices": True}, headers=H)
    assert tick(app) == {"skipped": "practice prices are on"}  # made-up values never mix in
    logged_in.put("/api/services/features", json={"practice_prices": False}, headers=H)
    app.state.prices.real.fail_with = "offline"
    app.state.prices.invalidate()
    out = tick(app)
    assert out["recorded"] == 0 and "offline" in out["skipped"]
    app.state.prices.real.fail_with = None
    app.state.prices.invalidate()
    assert tick(app)["recorded"] == 1
    assert count(app, BalanceSnapshot) == 1


def test_stale_prices_arent_recorded(logged_in, app, clock):
    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    app.state.prices.fresh(app.state.session_factory)  # a good snapshot, cached
    app.state.prices.real.fail_with = "offline"
    app.state.prices.invalidate()  # the next fetch fails: the old prices come back stale
    out = tick(app)
    assert (out["recorded"], out["skipped"]) == (0, "prices are stale")
    assert count(app, BalanceSnapshot) == 0


def test_the_switch(logged_in, app, clock):
    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    r = logged_in.put("/api/services/features", json={"balance_history": False}, headers=H)
    assert r.status_code == 200 and r.json()["balance_history"] is False
    assert tick(app) == {"disabled": True}
    assert (
        "balance_history off" in logged_in.get("/api/audit?q=services.feature").json()[0]["detail"]
    )


def test_holds_no_lock_while_fetching(tmp_path):
    """While prices are fetched (up to 10 s), other writes must go through."""
    from sqlalchemy import text

    from app.db import make_engine, make_session_factory
    from app.migrate import upgrade
    from app.models import Holding, Wallet
    from app.prices.providers import MockProvider
    from app.prices.service import PriceService

    engine = make_engine(f"sqlite:///{tmp_path / 'bot.db'}")
    upgrade(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        w = Wallet(name="w", kind="paper")
        db.add(w)
        db.flush()
        db.add(Holding(wallet_id=w.id, symbol="BTC", amount="1"))
        db.commit()
    wrote = []

    class SlowSource(MockProvider):
        def fetch(self, ids, fiats):
            with factory() as other:
                other.execute(text("PRAGMA busy_timeout=200"))
                other.execute(text("CREATE TABLE IF NOT EXISTS t_probe (x INTEGER)"))
                other.execute(text("INSERT INTO t_probe VALUES (1)"))
                other.commit()
                wrote.append(True)
            return super().fetch(ids, fiats)

    assert bh.BalanceHistoryJob(PriceService(SlowSource()), factory).tick()["recorded"] == 1
    assert wrote == [True]
    engine.dispose()


# ---- compaction ------------------------------------------------------------------------------


def shots(app, *times, wallet_id, amount="1"):
    with app.state.session_factory() as db:
        for at in times:
            s = BalanceSnapshot(at=at, daily=False)
            db.add(s)
            db.flush()
            db.add(
                BalancePoint(
                    snapshot_id=s.id,
                    wallet_id=wallet_id,
                    symbol="BTC",
                    amount=amount,
                    values={"usd": str(at.hour)},
                )
            )
        db.commit()


def kept(app):
    with app.state.session_factory() as db:
        return [
            (s.at, s.daily)
            for s in db.scalars(select(BalanceSnapshot).order_by(BalanceSnapshot.at))
        ]


def test_compaction_keeps_each_days_last(logged_in, app):
    w = wallet(logged_in, "Cold")
    day = datetime(2026, 9, 1)
    old = [day + timedelta(hours=h) for h in (1, 9, 23)]
    older = [day - timedelta(days=1) + timedelta(hours=h) for h in (5, 6)]
    recent = [datetime(2026, 9, 20, h) for h in (1, 2)]
    shots(app, *old, *older, *recent, wallet_id=w["id"])
    now = datetime(2026, 9, 21, 12)
    with app.state.session_factory() as db:
        out = bh.compact(db, bh.BalanceHistorySettings(detail_days=14), now)
        db.commit()
    assert out == {"snapshots_kept_daily": 2, "snapshots_removed": 3}
    assert kept(app) == [
        (older[-1], True),
        (old[-1], True),
        (recent[0], False),  # inside the 14 detailed days: untouched
        (recent[1], False),
    ]
    assert count(app, BalancePoint) == 4  # the removed snapshots' points went with them
    with app.state.session_factory() as db:  # again: nothing more to do
        assert bh.compact(db, bh.BalanceHistorySettings(detail_days=14), now) == {
            "snapshots_kept_daily": 0,
            "snapshots_removed": 0,
        }


def test_compaction_waits_for_whole_days_and_prunes(logged_in, app):
    w = wallet(logged_in, "Cold")
    now = datetime(2026, 9, 21, 12)
    # 14 days back is Sep 7 12:00: Sep 7 isn't over (as far as the detail window goes).
    shots(app, datetime(2026, 9, 7, 1), datetime(2026, 9, 7, 2), wallet_id=w["id"])
    shots(app, datetime(2026, 1, 1, 1), wallet_id=w["id"])
    with app.state.session_factory() as db:
        bh.compact(db, bh.BalanceHistorySettings(detail_days=14), now)
        db.commit()
    assert [d for _, d in kept(app)] == [True, False, False]
    with app.state.session_factory() as db:
        out = bh.compact(db, bh.BalanceHistorySettings(detail_days=14, keep_days=90), now)
        db.commit()
    assert out["snapshots_removed"] == 1 and len(kept(app)) == 2  # January is past 90 days


@pytest.mark.parametrize(
    "bad",
    [{"interval_minutes": 1}, {"detail_days": 0}, {"keep_days": -1}, {"surprise": True}],
)
def test_settings_validation(logged_in, bad):
    r = logged_in.put("/api/balance-history/settings", json=bad, headers=H)
    assert r.status_code == 422


def test_settings_round_trip_and_audit(logged_in):
    got = logged_in.get("/api/balance-history/settings").json()
    assert got["settings"] == {
        "enabled": True,
        "interval_minutes": 60,
        "detail_days": 14,
        "keep_days": 0,
    }
    assert got["stats"]["snapshots"] == 0
    r = logged_in.put(
        "/api/balance-history/settings", json={"interval_minutes": 30, "detail_days": 7}, headers=H
    )
    assert r.status_code == 200
    assert (
        logged_in.get("/api/balance-history/settings").json()["settings"]["interval_minutes"] == 30
    )
    entry = logged_in.get("/api/audit?q=balances.history").json()[0]
    assert entry["detail"] == "interval_minutes: 60 -> 30; detail_days: 14 -> 7"


# ---- reading ---------------------------------------------------------------------------------


def test_wallet_and_portfolio_series(logged_in, app, clock):
    a = wallet(logged_in, "Cold")
    b = wallet(logged_in, "Hot")
    hold(logged_in, a["id"], "BTC", "1")
    clock(seconds=5)
    tick(app)
    hold(logged_in, b["id"], "ETH", "2")
    clock(minutes=10)
    tick(app)
    btc, eth = price(app, "bitcoin"), price(app, "ethereum")

    one = logged_in.get(f"/api/balance-history/wallets/{a['id']}?fiat=usd").json()
    assert [r["value"] for r in one["rows"]] == [round_fiat(btc, "usd")] * 2
    assert one["rows"][0]["coins"] == {"BTC": "1"} and one["rows"][0]["unpriced"] == []
    hot = logged_in.get(f"/api/balance-history/wallets/{b['id']}?fiat=usd").json()["rows"]
    assert [r["value"] for r in hot] == ["0.00", round_fiat(2 * eth, "usd")]  # held nothing yet

    folio = logged_in.get("/api/balance-history/portfolio?fiat=usd").json()
    assert [r["value"] for r in folio["rows"]] == [
        round_fiat(btc, "usd"),
        round_fiat(btc + 2 * eth, "usd"),
    ]
    assert folio["change"] == {
        "from": round_fiat(btc, "usd"),
        "to": round_fiat(btc + 2 * eth, "usd"),
        "amount": round_fiat(2 * eth, "usd"),
        "percent": str(
            (Decimal(round_fiat(2 * eth, "usd")) * 100 / Decimal(round_fiat(btc, "usd"))).quantize(
                Decimal("0.01")
            )
        ),
    }
    assert (
        logged_in.get(f"/api/balance-history/wallets/{b['id']}").json()["change"]["percent"] is None
    )  # from zero
    # The user's own currency when none is asked for.
    logged_in.patch("/api/me/preferences", json={"fiat": "eur"}, headers=H)
    assert logged_in.get("/api/balance-history/portfolio").json()["fiat"] == "eur"
    assert logged_in.get("/api/balance-history/portfolio?fiat=xyz").status_code == 422

    # Archived wallets count only when asked; a deleted wallet's history goes with it.
    logged_in.patch(f"/api/wallets/{b['id']}", json={"archived": True}, headers=H)
    rows = logged_in.get("/api/balance-history/portfolio?fiat=usd").json()["rows"]
    assert rows[-1]["value"] == round_fiat(btc, "usd")
    rows = logged_in.get("/api/balance-history/portfolio?fiat=usd&include_archived=true").json()
    assert rows["rows"][-1]["value"] == round_fiat(btc + 2 * eth, "usd")
    logged_in.delete(f"/api/wallets/{a['id']}?force=true&confirm_name=Cold", headers=H)
    assert count(app, BalancePoint) == 1
    assert logged_in.get(f"/api/balance-history/wallets/{a['id']}").status_code == 404

    # The range: nothing older than asked for.
    clock(days=3)
    assert logged_in.get("/api/balance-history/portfolio?days=1").json()["rows"] == []


def test_a_wallet_counts_from_when_it_was_made(logged_in, app, clock):
    from app.models import Wallet

    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    clock(seconds=5)
    tick(app)
    late = wallet(logged_in, "Late")
    with app.state.session_factory() as db:  # made after that snapshot (on the test clock)
        db.get(Wallet, late["id"]).created_at = clock(minutes=1)
        db.commit()
    rows = logged_in.get(f"/api/balance-history/wallets/{late['id']}").json()["rows"]
    assert rows == []  # the snapshot before it existed isn't "zero" for it
    clock(minutes=10)
    tick(app)
    rows = logged_in.get(f"/api/balance-history/wallets/{late['id']}").json()["rows"]
    assert [r["value"] for r in rows] == ["0.00"]  # empty since it was made


def test_unpriced_coins_are_named_not_counted(logged_in, app, clock):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    with app.state.session_factory() as db:  # a coin without a price (removed custom coin)
        from app.models import Holding

        db.add(Holding(wallet_id=w["id"], symbol="ZZZ", amount="5"))
        db.commit()
    clock(seconds=5)
    tick(app)
    row = logged_in.get(f"/api/balance-history/wallets/{w['id']}?fiat=usd").json()["rows"][0]
    assert row["unpriced"] == ["ZZZ"] and row["value"] == round_fiat(price(app, "bitcoin"), "usd")
    assert row["coins"] == {"BTC": "1", "ZZZ": "5"}


def test_every_wallet_at_once_is_thinned(logged_in, app, clock):
    w = wallet(logged_in, "Cold")
    hold(logged_in, w["id"], "BTC", "1")
    for _ in range(12):
        clock(hours=1)
        tick(app)
    out = logged_in.get("/api/balance-history/wallets?most=5").json()
    rows = out["wallets"][str(w["id"])]
    assert len(rows) == 5 and set(rows[0]) == {"at", "value"}
    full = logged_in.get(f"/api/balance-history/wallets/{w['id']}").json()["rows"]
    assert len(full) == 12
    assert (rows[0]["at"], rows[-1]["at"]) == (full[0]["at"], full[-1]["at"])  # ends kept


def test_thin():
    assert bh.thin(list(range(10)), 20) == list(range(10))
    assert bh.thin(list(range(10)), 4) == [0, 3, 6, 9]
    assert bh.thin(list(range(101)), 3) == [0, 50, 100]


def test_needs_wallets_view_prices_view_and_the_app(logged_in, app):
    w = wallet(logged_in, "Cold")
    urls = [
        "/api/balance-history/portfolio",
        "/api/balance-history/wallets",
        f"/api/balance-history/wallets/{w['id']}",
    ]
    prices_only = user_with(app, logged_in, "pricey", ["prices.view"])
    wallets_only = user_with(app, logged_in, "walletsonly", ["wallets.view"])
    both = user_with(app, logged_in, "viewer", ["wallets.view", "prices.view"])
    for url in urls:
        assert prices_only.get(url).status_code == 403, url
        assert wallets_only.get(url).status_code == 403, url  # values reveal prices too
        assert both.get(url).status_code == 200, url
    vid = next(u["id"] for u in logged_in.get("/api/users").json() if u["username"] == "viewer")
    logged_in.put(f"/api/apps/accounts/{vid}", json={"apps": ["trades"]}, headers=H)
    for url in urls:
        assert both.get(url).status_code == 403, url
    # Settings (counts, no values): read with prices.view, like price history's; only
    # prices.manage changes them.
    assert prices_only.get("/api/balance-history/settings").status_code == 200
    assert wallets_only.get("/api/balance-history/settings").status_code == 403
    r = both.put("/api/balance-history/settings", json={"enabled": False}, headers=H)
    assert r.status_code == 403


def test_system_status_shows_it(logged_in, app, clock):
    hold(logged_in, wallet(logged_in, "Cold")["id"], "BTC", "1")
    clock(seconds=5)
    tick(app)
    s = logged_in.get("/api/system/status").json()["balance_history"]
    assert s["snapshots"] == 1 and s["points"] == 1 and s["newest"]


def test_doctor_check(tmp_path):
    from app.cli import doctor
    from app.config import Settings
    from app.db import make_engine, make_session_factory
    from app.migrate import upgrade
    from app.models import Wallet
    from app.timeutil import utcnow

    url = f"sqlite:///{tmp_path / 'bot.db'}"
    engine = make_engine(url)
    upgrade(engine)
    factory = make_session_factory(engine)
    settings = Settings(database_url=url, _env_file=None)
    r = doctor.check_balance_history(settings)
    assert (r.level, r.title) == (doctor.INFO, "No balance history recorded yet")
    with factory() as db:
        db.add(Wallet(name="w", kind="paper"))
        db.add(BalanceSnapshot(at=utcnow() - timedelta(hours=4)))
        db.commit()
    r = doctor.check_balance_history(settings)
    assert r.level == doctor.WARN and "stopped" in r.title  # 3 intervals + 5 min without one
    with factory() as db:
        db.add(BalanceSnapshot(at=utcnow()))
        db.commit()
    r = doctor.check_balance_history(settings)
    assert (r.level, r.title) == (doctor.OK, "Balance history recording (2 snapshots)")
    with factory() as db:
        bh.save_settings(db, bh.BalanceHistorySettings(enabled=False), None)
        db.commit()
    assert doctor.check_balance_history(settings).level == doctor.INFO
    engine.dispose()


def test_doctor_says_one_snapshot(tmp_path):
    from app.cli import doctor
    from app.config import Settings
    from app.db import make_engine, make_session_factory
    from app.migrate import upgrade
    from app.timeutil import utcnow

    url = f"sqlite:///{tmp_path / 'bot.db'}"
    engine = make_engine(url)
    upgrade(engine)
    with make_session_factory(engine)() as db:
        db.add(BalanceSnapshot(at=utcnow()))
        db.commit()
    r = doctor.check_balance_history(Settings(database_url=url, _env_file=None))
    assert r.title == "Balance history recording (1 snapshot)"
    engine.dispose()


def test_doctor_warns_when_super_skips_2fa(monkeypatch):
    from app.cli import doctor
    from app.config import Settings

    monkeypatch.setenv("BOT_SUPER_REQUIRES_TWO_FACTOR", "true")
    assert doctor.check_super_2fa(Settings(_env_file=None)).level == doctor.OK
    monkeypatch.setenv("BOT_SUPER_REQUIRES_TWO_FACTOR", "false")
    assert doctor.check_super_2fa(Settings(_env_file=None)).level == doctor.WARN
