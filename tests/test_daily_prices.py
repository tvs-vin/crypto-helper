"""12a: daily prices from Coinbase's public history, against a local fake that pages like the
real one (at most 300 candles, newest first, nothing before a coin was listed)."""

import json
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.models import DailyCandle
from app.prices import daily

TODAY = date(2026, 10, 19)


class FakeCoinbase:
    def __init__(self, listed: dict[str, date], delisted=("OLD",)):
        self.listed = listed  # symbol -> first day with a candle
        self.delisted = delisted
        self.requests: list[str] = []
        self.close_today = Decimal("100")
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.requests.append(self.path)
                url = urlsplit(self.path)
                if url.path == "/products":
                    rows = [{"base_currency": s, "quote_currency": "USD", "status": "online"}
                            for s in fake.listed]  # fmt: skip
                    rows += [{"base_currency": s, "quote_currency": "USD", "status": "delisted"}
                             for s in fake.delisted]  # fmt: skip
                    # Markets in another currency don't count (SOL has only a EUR one here).
                    for base in ("BTC", "SOL"):
                        rows.append(
                            {"base_currency": base, "quote_currency": "EUR", "status": "online"}
                        )
                    return self._send(rows)
                symbol = url.path.split("/")[2].split("-")[0]
                q = parse_qs(url.query)
                start = datetime.fromisoformat(q["start"][0].replace("Z", "+00:00")).date()
                end = datetime.fromisoformat(q["end"][0].replace("Z", "+00:00")).date()
                assert (end - start).days < 300, "more than 300 candles asked for"
                assert q["granularity"] == ["86400"]
                first = fake.listed.get(symbol)
                rows = []
                d = end
                while d >= start:
                    if first and d >= first and d <= TODAY:
                        n = (d - first).days + 1  # price grows by 1 a day from listing
                        close = fake.close_today if d == TODAY else Decimal(n)
                        ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
                        rows.append([ts, str(n - 0.5), str(n + 0.5), str(n), str(close), "10"])
                    d -= timedelta(days=1)
                self._send(rows)  # newest first, like Coinbase

            def _send(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def coinbase(monkeypatch):
    monkeypatch.setattr(daily, "PAUSE", 0)
    fake = FakeCoinbase({"BTC": TODAY - timedelta(days=700), "ETH": TODAY - timedelta(days=10)})
    yield fake
    fake.close()


def job(app, coinbase):
    return daily.DailyPriceJob(app.state.session_factory, coinbase.url, today=lambda: TODAY)


def candles(app, symbol):
    with app.state.session_factory() as db:
        return db.scalars(
            select(DailyCandle).where(DailyCandle.symbol == symbol).order_by(DailyCandle.day)
        ).all()


def test_products_are_usd_markets_still_trading(coinbase):
    assert daily.Coinbase(coinbase.url).products() == {"BTC", "ETH"}


def test_first_run_downloads_everything_then_tops_up(client, app, coinbase):
    j = job(app, coinbase)
    out = j.tick()
    assert out["added"] == {"BTC": 701, "ETH": 11}
    assert "SOL" in out["missing"] and "BTC" not in out["missing"]
    btc = candles(app, "BTC")
    assert (btc[0].day, btc[-1].day, len(btc)) == (TODAY - timedelta(days=700), TODAY, 701)
    assert (btc[0].open, btc[0].high, btc[0].low, btc[0].close) == ("1", "1.5", "0.5", "1")
    # BTC: 3 pages until an empty one (the coin wasn't listed yet), then it stops.
    btc_requests = [r for r in coinbase.requests if "/BTC-USD/" in r]
    assert len(btc_requests) == 4
    assert j.tick() == {"skipped": "not due"}  # once an hour
    # Later: only from the last day; today's candle is rewritten (it changes until midnight).
    coinbase.requests.clear()
    coinbase.close_today = Decimal("123.45")
    assert j.tick(force=True)["added"] == {}
    assert len([r for r in coinbase.requests if "/BTC-USD/" in r]) == 1
    assert candles(app, "BTC")[-1].close == "123.45"
    assert len(candles(app, "BTC")) == 701


def test_a_broken_answer_is_reported_not_stored(client, app, coinbase, monkeypatch):
    def broken(self, symbol, start, end):
        raise daily.SourceError("Coinbase answered 500")

    monkeypatch.setattr(daily.Coinbase, "candles", broken)
    out = job(app, coinbase).tick()
    assert out["errors"]["BTC"] == "Coinbase answered 500" and out["added"] == {}
    assert candles(app, "BTC") == []


def test_unreachable_coinbase_skips_the_run(client, app):
    j = daily.DailyPriceJob(app.state.session_factory, "http://127.0.0.1:9", today=lambda: TODAY)
    assert "skipped" in j.tick()


def test_coverage_recent_and_average(client, app, coinbase):
    job(app, coinbase).tick()
    with app.state.session_factory() as db:
        cov = daily.coverage(db)
        assert cov["ETH"] == {"first": TODAY - timedelta(days=10), "last": TODAY, "days": 11}
        last3 = daily.recent(db, "ETH", 3)
    assert [c.day for c in last3] == [TODAY - timedelta(days=2), TODAY - timedelta(days=1), TODAY]
    assert daily.moving_average([Decimal(1), Decimal(2), Decimal(6)]) == 3
    assert daily.moving_average([]) is None


def test_daily_api(logged_in, app, coinbase):
    job(app, coinbase).tick()
    r = logged_in.get("/api/prices/daily?symbol=eth&days=2").json()
    assert r["symbol"] == "ETH" and [x["close"] for x in r["rows"]] == ["10", "100"]


def test_first_run_right_after_boot(client, app, coinbase, monkeypatch):
    """Monotonic time starts at boot: a machine up for a minute must not wait an hour."""
    monkeypatch.setattr(daily.time, "monotonic", lambda: 60.0)
    assert "added" in job(app, coinbase).tick()
