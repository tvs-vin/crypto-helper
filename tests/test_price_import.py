"""12b: importing past prices onto the charts. What's imported (daily years back, hourly for the
recent days, per currency Coinbase trades), that it only fills the time before recording and
never replaces recorded prices, the chart query that joins them, and the rules."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import DailyCandle, PriceCandle, PricePoint
from app.prices import daily, history, importer
from tests.conftest import H
from tests.test_daily_prices import TODAY, FakeCoinbase
from tests.wallet_helpers import user_with

NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 12)


@pytest.fixture
def coinbase(monkeypatch):
    monkeypatch.setattr(daily, "PAUSE", 0)
    fake = FakeCoinbase({"BTC": TODAY - timedelta(days=700), "ETH": TODAY - timedelta(days=10)})
    yield fake
    fake.close()


@pytest.fixture
def job(client, app, coinbase, monkeypatch):
    j = importer.PriceImport(app.state.session_factory, coinbase.url)
    j.now = lambda: NOW
    monkeypatch.setattr(importer, "HOURLY_DAYS", 3)
    app.state.price_import = j
    return j


def count(app, model, *where):
    with app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def test_imports_days_and_hours_per_currency(app, job):
    out = job.run(["BTC", "ETH", "SOL"], ["usd", "eur"], "super")
    assert out["days"] == 701 + 11 + 701  # BTC and ETH in USD, BTC in EUR (SOL-EUR is empty)
    assert out["hours"] == 3 * 24 * 3  # three days of hours: BTC-USD, ETH-USD, BTC-EUR
    assert sorted(out["skipped"]) == ["ETH-EUR", "SOL-USD"]  # no such markets
    assert out["errors"] == {} and out["by"] == "super"
    assert count(app, DailyCandle, DailyCandle.quote == "eur") == 701
    with app.state.session_factory() as db:
        eur = db.scalar(
            select(DailyCandle)
            .where(DailyCandle.symbol == "BTC", DailyCandle.quote == "eur")
            .order_by(DailyCandle.day)  # fmt: skip
        )
        assert eur.close == "0.9"  # BTC-EUR's own prices, not converted from USD
        last = job.last(db)
        cov = job.coverage(db)
    assert last["days"] == out["days"]
    assert cov["BTC"]["eur"]["days"] == 701 and cov["BTC"]["usd"]["hours"] == 72
    # Again: nothing new to add (only today's day, which is rewritten).
    again = job.run(["BTC"], ["usd"], "super")
    assert (again["days"], again["hours"], again["errors"]) == (0, 0, {})  # no duplicates


def test_hours_only_before_anything_recorded(app, job):
    with app.state.session_factory() as db:  # recorded here since a day and a half ago
        db.add(PriceCandle(coingecko_id="bitcoin", fiat="usd", interval_minutes=60,
                           start=NOW - timedelta(hours=36), open="5", high="5", low="5",
                           close="5", points=6))  # fmt: skip
        db.commit()
    out = job.run(["BTC"], ["usd"], "super")
    assert out["hours"] == 3 * 24 - 36  # up to the first recorded hour, not after
    with app.state.session_factory() as db:
        latest = db.scalar(
            select(func.max(PriceCandle.start)).where(PriceCandle.source == "coinbase")
        )
    assert latest < NOW - timedelta(hours=36)


def test_recorded_prices_replace_imported_ones(app, job):
    job.run(["BTC"], ["usd"], "super")
    hour = NOW - timedelta(hours=5)
    with app.state.session_factory() as db:  # a recorded point in an imported hour (rare)
        db.add(PricePoint(coingecko_id="bitcoin", fiat="usd", at=hour + timedelta(minutes=10),
                          price="999"))  # fmt: skip
        db.commit()
        history.compact(db, history.HistorySettings(fine_keep_hours=1), NOW + timedelta(hours=3))
        db.commit()
        c = db.scalar(select(PriceCandle).where(PriceCandle.start == hour))
        assert (c.source, c.close) == ("recorded", "999")


def test_pruning_keeps_imported_prices(app, job):
    job.run(["BTC"], ["usd"], "super")
    before = count(app, PriceCandle, PriceCandle.source == "coinbase")
    with app.state.session_factory() as db:
        history.compact(db, history.HistorySettings(coarse_keep_days=1), NOW + timedelta(days=30))
        db.commit()
    assert count(app, PriceCandle, PriceCandle.source == "coinbase") == before


def test_the_chart_joins_them_without_overlap(app, job):
    with app.state.session_factory() as db:
        db.add(PriceCandle(coingecko_id="bitcoin", fiat="usd", interval_minutes=60,
                           start=NOW - timedelta(hours=10), open="5", high="5", low="5",
                           close="5", points=6))  # fmt: skip
        db.commit()
    job.run(["BTC"], ["usd"], "super")
    with app.state.session_factory() as db:
        rows = history.query(db, "bitcoin", "usd", NOW - timedelta(days=10), symbol="BTC")
    sources = [(r["source"], r.get("interval_minutes")) for r in rows]
    # Daily (imported) first, then hourly (imported), then recorded: each only before the next.
    assert sources[0] == ("coinbase", 1440) and sources[-1] == ("recorded", 60)
    kinds = [s for i, s in enumerate(sources) if i == 0 or s != sources[i - 1]]
    assert kinds == [("coinbase", 1440), ("coinbase", 60), ("recorded", 60)]
    times = [r["at"] for r in rows]
    assert times == sorted(times) and len(set(times)) == len(times)
    first_hour = next(r["at"] for r in rows if r.get("interval_minutes") == 60)
    last_day = max(r["at"] for r in rows if r.get("interval_minutes") == 1440)
    assert last_day < first_hour


def test_imported_hours_after_recording_began_are_hidden(app, job):
    """However they got there, imported hours never overlap recorded prices on the chart."""
    with app.state.session_factory() as db:
        for h in range(48):
            db.add(PriceCandle(coingecko_id="bitcoin", fiat="usd", interval_minutes=60,
                               start=NOW - timedelta(hours=48 - h), open="1", high="1", low="1",
                               close="1", points=0, source="coinbase"))  # fmt: skip
        db.add(PricePoint(coingecko_id="bitcoin", fiat="usd", at=NOW - timedelta(hours=20),
                          price="7"))  # fmt: skip
        db.commit()
        rows = history.query(db, "bitcoin", "usd", NOW - timedelta(days=3), symbol="BTC")
    imported = [r["at"] for r in rows if r["source"] == "coinbase"]
    assert imported and max(imported) < NOW - timedelta(hours=20)


def test_a_chart_uses_only_its_own_currency(app, job):
    job.run(["BTC"], ["usd", "eur"], "super")
    with app.state.session_factory() as db:
        usd = history.query(db, "bitcoin", "usd", NOW - timedelta(days=3650), symbol="BTC")
        eur = history.query(db, "bitcoin", "eur", NOW - timedelta(days=3650), symbol="BTC")
    days = [r for r in usd if r.get("interval_minutes") == 1440]
    assert len(days) == len({r["at"] for r in days})  # one row a day, not one per currency
    assert days[0]["price"] == "1" and eur[0]["price"] == "0.9"


def test_long_ranges_are_thinned(app, job, monkeypatch):
    job.run(["BTC"], ["usd"], "super")
    monkeypatch.setattr(history, "MAX_QUERY_ROWS", 100)
    with app.state.session_factory() as db:
        rows = history.query(db, "bitcoin", "usd", NOW - timedelta(days=3650), symbol="BTC")
        full = db.scalar(select(func.count()).select_from(DailyCandle))
    assert len(rows) == 100 and full > 100
    assert rows[0]["at"].date() == TODAY - timedelta(days=700)  # the oldest is kept


def test_remove_keeps_usd_daily_prices(app, job):
    job.run(["BTC"], ["usd", "eur"], "super")
    with app.state.session_factory() as db:
        out = importer.PriceImport.remove(db)
        db.commit()
    assert out == {"hours": 144, "days": 701}
    assert count(app, DailyCandle, DailyCandle.quote == "usd") == 701  # trend alerts use them


# ---- the API ---------------------------------------------------------------------------------


def wait(app):
    import time

    for _ in range(200):
        if not app.state.price_import.progress["running"]:
            return
        time.sleep(0.05)
    raise AssertionError("the import didn't finish")


def test_api_runs_one_at_a_time_and_is_audited(logged_in, app, job):
    r = logged_in.post("/api/prices/import", json={"fiats": ["usd"], "symbols": ["btc"]}, headers=H)
    assert r.status_code == 202
    wait(app)
    s = logged_in.get("/api/prices/import").json()
    assert s["progress"]["running"] is False and s["last"]["days"] >= 701
    assert s["coverage"]["BTC"]["usd"]["days"] == 701 and s["hourly_days"] == 3
    details = [e["detail"] for e in logged_in.get("/api/audit?q=prices.import").json()]
    assert "BTC in USD" in details
    job.progress["running"] = True  # as if one were running: nothing else starts or removes
    assert (
        logged_in.post("/api/prices/import", json={"fiats": ["usd"]}, headers=H).status_code == 409
    )
    assert logged_in.delete("/api/prices/import", headers=H).status_code == 409
    job.progress["running"] = False
    r = logged_in.delete("/api/prices/import", headers=H)
    assert r.status_code == 200 and r.json()["hours"] == 72
    assert logged_in.get("/api/audit?q=prices.import").json()[0]["detail"].startswith("72 hourly")


def test_api_rules(logged_in, app, job):
    r = logged_in.post(
        "/api/prices/import", json={"fiats": ["usd"], "symbols": ["NOPE"]}, headers=H
    )
    assert r.status_code == 422 and "NOPE" in r.json()["detail"]
    assert logged_in.post("/api/prices/import", json={"fiats": []}, headers=H).status_code == 422
    assert (
        logged_in.post("/api/prices/import", json={"fiats": ["xyz"]}, headers=H).status_code == 422
    )
    viewer = user_with(app, logged_in, "viewer", ["prices.view"])
    assert viewer.get("/api/prices/import").status_code == 403
    assert viewer.post("/api/prices/import", json={"fiats": ["usd"]}, headers=H).status_code == 403
    assert viewer.delete("/api/prices/import", headers=H).status_code == 403


def test_chart_api_shows_imported_history(logged_in, app, job):
    job.run(["BTC"], ["usd"], "super")
    r = logged_in.get("/api/prices/history?symbol=BTC&fiat=usd&hours=262800")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows[0]["source"] == "coinbase" and len(rows) > 700
    assert Decimal(rows[0]["price"]) == 1


def test_a_failing_coinbase_is_reported(app, job):
    job.client.base = "http://127.0.0.1:9"
    out = job.run(None, ["usd"], "super")
    assert "Coinbase" in out["errors"] and out["days"] == 0
    assert job.progress["running"] is False
