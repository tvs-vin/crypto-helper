"""Providers, the cached price service, and price history (no HTTP layer)."""

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db import make_engine, make_session_factory
from app.migrate import upgrade
from app.models import PriceCandle, PricePoint
from app.prices import history
from app.prices.background import HistoryJob
from app.prices.providers import CoinGeckoProvider, MockProvider, ProviderError, Quote
from app.prices.service import PriceService, PricesUnavailable, Snapshot
from app.prices.valuation import round_fiat


@pytest.fixture
def db():
    engine = make_engine("sqlite://")
    upgrade(engine)
    session = make_session_factory(engine)()
    yield session
    session.close()


class FakeHttp:
    def __init__(self, status=200, body=b"{}", exc=None):
        self.status, self.body, self.exc = status, body, exc
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers))
        if self.exc:
            raise self.exc
        return self.status, self.body


# ---- CoinGecko provider ------------------------------------------------------------------


def test_coingecko_parses_exact_decimals_never_float():
    body = (
        b'{"bitcoin":{"usd":81586.123456789012345678,"usd_24h_change":-2.135371362182366,'
        b'"eur":73019},"ethereum":{"usd":0.1}}'
    )
    p = CoinGeckoProvider(http_get=FakeHttp(body=body))
    q = p.fetch(["bitcoin", "ethereum"], ["usd", "eur"])
    assert q["bitcoin"]["usd"].price == Decimal("81586.123456789012345678")
    assert isinstance(q["bitcoin"]["usd"].price, Decimal)
    assert q["bitcoin"]["usd"].change_24h == Decimal("-2.135371362182366")
    assert q["bitcoin"]["eur"].change_24h is None
    assert q["ethereum"]["usd"].price == Decimal("0.1") and "eur" not in q["ethereum"]


def test_coingecko_ignores_junk_rows():
    body = b'{"bitcoin":{"usd":-5},"evil":{"usd":1},"ethereum":"nope","solana":{"usd":"7"}}'
    assert (
        CoinGeckoProvider(http_get=FakeHttp(body=body)).fetch(
            ["bitcoin", "ethereum", "solana"], ["usd"]
        )
        == {}
    )


@pytest.mark.parametrize(
    ("http", "fragment"),
    [
        (FakeHttp(status=429), "rate limit"),
        (FakeHttp(status=401), "BOT_COINGECKO_API_KEY"),
        (FakeHttp(status=503), "HTTP 503"),
        (FakeHttp(exc=TimeoutError()), "didn't answer"),
        (FakeHttp(exc=OSError("dns")), "didn't answer"),
        (FakeHttp(body=b"<html>"), "isn't JSON"),
        (FakeHttp(body=b"[1,2]"), "unexpected"),
    ],
)
def test_coingecko_failures_become_provider_errors(http, fragment):
    with pytest.raises(ProviderError, match=fragment):
        CoinGeckoProvider(http_get=http).fetch(["bitcoin"], ["usd"])


def test_api_key_only_sent_when_set():
    http = FakeHttp(body=b"{}")
    CoinGeckoProvider(http_get=http).fetch(["bitcoin"], ["usd"])
    CoinGeckoProvider(api_key="demo-key", http_get=http).fetch(["bitcoin"], ["usd"])
    assert "x-cg-demo-api-key" not in http.calls[0][1]
    assert http.calls[1][1]["x-cg-demo-api-key"] == "demo-key"
    assert "demo-key" not in http.calls[1][0]  # never in the URL (URLs end up in logs)


def test_one_request_for_all_coins_and_fiats():
    http = FakeHttp(body=b"{}")
    CoinGeckoProvider(http_get=http).fetch(["bitcoin", "ethereum"], ["usd", "eur"])
    assert len(http.calls) == 1
    assert "ids=bitcoin%2Cethereum" in http.calls[0][0]
    assert "vs_currencies=usd%2Ceur" in http.calls[0][0]


def test_coin_list_is_cached():
    http = FakeHttp(body=json.dumps([{"id": "pepe", "symbol": "pepe", "name": "Pepe"}]).encode())
    p = CoinGeckoProvider(http_get=http)
    assert p.coin_list()[0].coingecko_id == "pepe"
    p.coin_list()
    assert len(http.calls) == 1


def test_mock_is_deterministic():
    a = MockProvider().fetch(["bitcoin"], ["usd", "jpy"])
    b = MockProvider().fetch(["bitcoin"], ["usd", "jpy"])
    assert a == b and a["bitcoin"]["jpy"].price == a["bitcoin"]["usd"].price * 150


# ---- the cached service ------------------------------------------------------------------


def test_one_fetch_per_cache_period(db):
    provider = MockProvider()
    svc = PriceService(provider, cache_seconds=60)
    first = svc.snapshot(db)
    assert svc.snapshot(db) is first and provider.calls == 1
    svc.invalidate()
    svc.snapshot(db)
    assert provider.calls == 2


def test_outage_serves_last_good_marked_stale(db):
    provider = MockProvider()
    svc = PriceService(provider, cache_seconds=0)
    good = svc.snapshot(db)
    provider.fail_with = "CoinGecko didn't answer (TimeoutError)"
    stale = svc.snapshot(db)
    assert stale.stale and stale.error.startswith("CoinGecko didn't answer")
    assert stale.quotes == good.quotes and stale.as_of == good.as_of


def test_failures_are_cached_too_so_an_outage_isnt_hammered(db):
    provider = MockProvider()
    provider.fail_with = "down"
    svc = PriceService(provider, cache_seconds=60)
    for _ in range(5):
        with pytest.raises(PricesUnavailable, match="down"):
            svc.snapshot(db)
    assert provider.calls == 1


def test_after_restart_stale_prices_come_from_history(db):
    db.add(
        PricePoint(
            coingecko_id="bitcoin",
            fiat="usd",
            at=datetime(2026, 1, 1),
            price="50000",
            change_24h="1.5",
        )
    )
    db.commit()
    provider = MockProvider()
    provider.fail_with = "offline"
    snap = PriceService(provider).snapshot(db)
    assert snap.stale and "saved history" in snap.source
    assert snap.quotes["bitcoin"]["usd"].price == Decimal("50000")


# ---- history settings, recording, compaction ---------------------------------------------


def test_history_defaults():
    s = history.HistorySettings()
    assert (
        s.fine_interval_minutes,
        s.fine_keep_hours,
        s.coarse_interval_minutes,
        s.coarse_keep_days,
        s.fiats,
    ) == (10, 24, 60, 0, ["usd"])


@pytest.mark.parametrize(
    "bad",
    [
        {"fine_interval_minutes": 0},
        {"fine_interval_minutes": 61},
        {"coarse_interval_minutes": 45},  # doesn't divide a day
        {"fine_interval_minutes": 7, "coarse_interval_minutes": 60},  # 60 isn't a multiple of 7
        {"fiats": []},
        {"fiats": ["btc"]},
        {"coarse_keep_days": -1},
        {"surprise": 1},
    ],
)
def test_history_settings_validation(bad):
    with pytest.raises(ValueError):
        history.HistorySettings(**bad)


def test_settings_round_trip(db):
    history.save_settings(
        db, history.HistorySettings(fine_interval_minutes=5, fiats=["usd", "eur"]), "super"
    )
    db.commit()
    assert history.load_settings(db).fiats == ["usd", "eur"]


def snap_at(at, prices, stale=False):
    return Snapshot(
        at,
        "test",
        "",
        {cid: {"usd": Quote(Decimal(p), Decimal("1"))} for cid, p in prices.items()},
        stale=stale,
    )


def test_record_only_configured_fiats_and_never_stale(db):
    s = history.HistorySettings()
    snap = Snapshot(
        datetime(2026, 1, 1),
        "t",
        "",
        {"bitcoin": {"usd": Quote(Decimal("1"), None), "eur": Quote(Decimal("2"), None)}},
    )
    assert history.record(db, snap, s) == 1
    assert history.record(db, snap_at(datetime(2026, 1, 1), {"bitcoin": "1"}, stale=True), s) == 0


def test_due_respects_interval(db):
    s = history.HistorySettings(fine_interval_minutes=10)
    now = datetime(2026, 1, 1, 12, 0)
    assert history.is_due(db, s, now)
    history.record(db, snap_at(now, {"bitcoin": "1"}), s)
    assert not history.is_due(db, s, now + timedelta(minutes=5))
    assert history.is_due(db, s, now + timedelta(minutes=10))


def test_compaction_builds_correct_candles_and_only_whole_ones(db):
    s = history.HistorySettings()  # 10-minute points, keep 24 h, hourly candles
    t0 = datetime(2026, 1, 1, 10, 0)
    prices = ["100", "130", "90", "110", "120", "105"]  # 10:00 .. 10:50
    for i, p in enumerate(prices):
        history.record(db, snap_at(t0 + timedelta(minutes=10 * i), {"bitcoin": p}), s)
    history.record(db, snap_at(datetime(2026, 1, 2, 10, 20), {"bitcoin": "999"}), s)
    db.commit()
    # 24 h after 11:05: cutoff is 11:05 the day before, so only the 10:00-11:00 hour is whole.
    result = history.compact(db, s, datetime(2026, 1, 2, 11, 5))
    db.commit()
    assert result == {"candles_written": 1, "points_compacted": 6, "candles_pruned": 0}
    c = db.query(PriceCandle).one()
    assert (c.start, c.open, c.high, c.low, c.close, c.points) == (t0, "100", "130", "90", "105", 6)
    assert db.query(PricePoint).count() == 1  # the recent point stays detailed
    assert history.compact(db, s, datetime(2026, 1, 2, 11, 5))["candles_written"] == 0


def test_partial_bucket_waits_until_whole(db):
    s = history.HistorySettings()
    for minute in (0, 10, 20):
        history.record(db, snap_at(datetime(2026, 1, 1, 10, minute), {"bitcoin": "1"}), s)
    # Cutoff 10:25: the 10:00 hour isn't over at the cutoff, so nothing is compacted yet.
    assert history.compact(db, s, datetime(2026, 1, 2, 10, 25))["points_compacted"] == 0


def test_custom_sizes_and_pruning(db):
    s = history.HistorySettings(
        fine_interval_minutes=5, fine_keep_hours=1, coarse_interval_minutes=15, coarse_keep_days=1
    )
    base = datetime(2026, 1, 1, 0, 0)
    for i in range(6):  # 00:00 .. 00:25
        history.record(db, snap_at(base + timedelta(minutes=5 * i), {"bitcoin": str(i + 1)}), s)
    history.compact(db, s, base + timedelta(hours=2))
    starts = [c.start.minute for c in db.query(PriceCandle).order_by(PriceCandle.start)]
    assert starts == [0, 15]
    assert history.compact(db, s, base + timedelta(days=3))["candles_pruned"] == 2


def test_query_mixes_candles_and_points_oldest_first(db):
    s = history.HistorySettings()
    db.add(
        PriceCandle(
            coingecko_id="bitcoin",
            fiat="usd",
            interval_minutes=60,
            start=datetime(2026, 1, 1, 9),
            open="1",
            high="2",
            low="1",
            close="2",
            points=6,
        )
    )
    history.record(db, snap_at(datetime(2026, 1, 1, 11), {"bitcoin": "3"}), s)
    rows = history.query(db, "bitcoin", "usd", datetime(2026, 1, 1))
    assert [(r["kind"], r["price"]) for r in rows] == [("candle", "2"), ("point", "3")]


def test_history_job_tick(db, monkeypatch):
    engine = make_engine("sqlite://")
    upgrade(engine)
    factory = make_session_factory(engine)
    job = HistoryJob(PriceService(MockProvider()), factory)
    assert job.tick()["recorded"] == 18  # every built-in coin, in USD
    assert job.tick()["recorded"] == 0  # not due again for 10 minutes
    with factory() as d:
        history.save_settings(d, history.HistorySettings(enabled=False), None)
        d.commit()
    assert job.tick() == {"disabled": True}


def test_history_job_survives_an_outage():
    engine = make_engine("sqlite://")
    upgrade(engine)
    provider = MockProvider()
    provider.fail_with = "offline"
    result = HistoryJob(PriceService(provider), make_session_factory(engine)).tick()
    assert result["recorded"] == 0 and "offline" in result["skipped"]


# ---- rounding ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "fiat", "shown"),
    [
        ("1234.565", "usd", "1234.57"),
        ("1234.564", "usd", "1234.56"),
        ("0.005", "eur", "0.01"),
        ("1234.5", "jpy", "1235"),
        ("0", "usd", "0.00"),
    ],
)
def test_fiat_rounding(value, fiat, shown):
    assert round_fiat(Decimal(value), fiat) == shown
