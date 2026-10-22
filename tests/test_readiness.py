"""12e: readiness for live trading (project rule 10, checked by the app): 14 clean days on
paper, a kill switch drill, and the limits self-check on the code that's running."""

from datetime import datetime, timedelta

import pytest

from app import bots, readiness
from app.models import Bot
from app.timeutil import utcnow
from tests.conftest import H
from tests.test_bots import PLAN, bot_row, make, seed, tick
from tests.wallet_helpers import user_with


@pytest.fixture
def primed(logged_in, app):
    seed(app)
    return logged_in


def report(app, days=0, checks_ran=True):
    """Readiness `days` from now; by default the bot check kept running (with prices) until then."""
    at = utcnow() + timedelta(days=days)
    with app.state.session_factory() as db:
        if checks_ran:
            for b in db.query(Bot).filter(Bot.status == "running"):
                b.state = {**b.state, "last_tick_at": (at - timedelta(minutes=1)).isoformat()}
            db.flush()
        return readiness.report(db, at)


def clean_since(app, bot_id):
    return datetime.fromisoformat(bot_row(app, bot_id).state["clean_since"])


def drill(c):
    r = c.post("/api/bots/drill", json={"reason": "monthly drill"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["kill"]


def rearm(c):
    assert c.post("/api/bots/rearm", json={"confirm": "REARM"}, headers=H).status_code == 200


def selfcheck(c):
    r = c.post("/api/bots/selfcheck", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


# ---- the whole rule --------------------------------------------------------------------------


def test_green_only_with_all_three(primed, app):
    b = make(primed)
    r = primed.get("/api/bots/readiness").json()
    assert r["ready"] is False and r["clean_days"] == 14
    (row,) = r["bots"]
    assert (
        row["clean_days"] < 0.01
        and row["ready_on"] == (utcnow() + timedelta(14)).date().isoformat()
    )
    assert {c["key"]: c["ok"] for c in row["checks"]} == {
        "running": True,
        "limits": True,
        "clean": False,
    }
    assert report(app, days=15)["bots"][0]["ok"] is True  # two weeks on: this bot is fine
    assert report(app, days=15)["ready"] is False  # but no drill, no self-check yet
    drill(primed)
    rearm(primed)
    assert primed.post(f"/api/bots/{b['id']}/start", headers=H).status_code == 200
    assert report(app, days=15)["ready"] is False  # still no self-check
    assert selfcheck(primed)["passed"] is True
    assert report(app, days=15)["ready"] is True
    assert report(app, days=13)["ready"] is False  # one day short


def test_each_check_is_needed(primed, app):
    make(primed)
    selfcheck(primed)
    assert report(app, days=15)["ready"] is False  # no drill
    drill(primed)
    rearm(primed)
    assert report(app, days=15)["ready"] is False  # the bot was stopped by the drill
    primed.post("/api/bots/1/start", headers=H)
    assert report(app, days=15)["ready"] is True


def test_a_bot_whose_check_stopped_has_no_clean_days(primed, app):
    make(primed)
    (row,) = report(app, days=15, checks_ran=False)["bots"]  # the service is down right now
    clean = next(c for c in row["checks"] if c["key"] == "clean")
    assert row["clean_days"] == 0 and "no bot check with prices" in clean["detail"]


def test_a_coin_a_bot_trades_cant_be_removed(primed, app):
    r = primed.post("/api/coins", json={"coingecko_id": "mockcoin"}, headers=H)
    assert r.status_code == 201, r.text
    seed(app, symbols=("MOCK",))
    make(primed, "Mock bot", params={**PLAN, "coins": {"MOCK": "100"}})
    r = primed.delete("/api/coins/MOCK", headers=H)
    assert r.status_code == 409 and "Mock bot" in r.json()["detail"]


def test_a_bot_without_loss_limits_never_counts(primed, app):
    make(primed, limits={"position_loss_pct": None, "daily_loss_pct": None})
    (row,) = report(app, days=30)["bots"]
    assert row["ok"] is False
    assert next(c for c in row["checks"] if c["key"] == "limits")["ok"] is False


# ---- what resets the clean run -------------------------------------------------------------


def test_a_drill_keeps_the_clean_run(primed, app):
    b = make(primed)
    with app.state.session_factory() as db:  # it had been running cleanly for 3 days
        bot = db.get(Bot, b["id"])
        bot.state = {**bot.state, "clean_since": (utcnow() - timedelta(days=3)).isoformat()}
        db.commit()
    before = clean_since(app, b["id"])
    k = drill(primed)
    assert k["drill"] == {"bots_stopped": 1, "orders_cancelled": 1, "all_stopped": True,
                          "check_refused": True}  # fmt: skip
    assert report(app)["drill"]["in_progress"] is True
    assert report(app)["drill"]["ok"] is False  # not until it's re-armed
    rearm(primed)
    d = report(app)["drill"]
    assert d["ok"] is True and d["last"]["rearmed_by"] == "super" and not d["in_progress"]
    primed.post(f"/api/bots/{b['id']}/start", headers=H)
    assert clean_since(app, b["id"]) == before


@pytest.mark.parametrize("how", ["real kill switch", "paused by a person", "its loss limit"])
def test_anything_else_starts_the_two_weeks_again(primed, app, how):
    b = make(primed, limits={"position_loss_pct": "10"})
    tick(app)
    with app.state.session_factory() as db:  # it had been running cleanly for 3 days
        bot = db.get(Bot, b["id"])
        bot.state = {**bot.state, "clean_since": (utcnow() - timedelta(days=3)).isoformat()}
        db.commit()
    before = clean_since(app, b["id"])
    if how == "real kill switch":
        primed.post("/api/bots/kill", json={"reason": "something broke"}, headers=H)
        rearm(primed)
    elif how == "paused by a person":
        primed.post(f"/api/bots/{b['id']}/pause", headers=H)
    else:
        with app.state.session_factory() as db:  # as if it had paid twice today's price
            bot = db.get(Bot, b["id"])
            cost = str(float(bot.account["cost"]["BTC"]) * 2)
            bot.account = {**bot.account, "cost": {"BTC": cost}}
            db.commit()
        tick(app)
        assert bot_row(app, b["id"]).state["paused_by"] == "limit"
    assert report(app, days=30)["bots"][0]["clean_days"] == 0  # paused: not running
    primed.post(f"/api/bots/{b['id']}/start", headers=H)
    row = bot_row(app, b["id"])
    assert datetime.fromisoformat(row.state["clean_since"]) > before
    assert row.state["clean_reset"]["why"].startswith("started again after:")


def test_the_check_stopping_for_6_hours_restarts_it(primed, app):
    b = make(primed)
    now = utcnow()
    tick(app, now)
    tick(app, now + timedelta(hours=5))  # a short outage is fine
    assert clean_since(app, b["id"]) < now
    tick(app, now + timedelta(hours=12))  # the service was down for 7 hours
    row = bot_row(app, b["id"])
    assert clean_since(app, b["id"]) == (now + timedelta(hours=12)).replace(microsecond=0)
    assert row.state["clean_reset"]["why"] == "no bot check for 7 h"


# ---- the drill -------------------------------------------------------------------------------


def test_a_drill_that_didnt_stop_the_check_doesnt_count(primed, app, monkeypatch):
    make(primed)
    monkeypatch.setattr(app.state.bot_job, "tick", lambda now=None: {"bots": 1})  # it ran!
    k = drill(primed)
    assert k["drill"]["check_refused"] is False
    rearm(primed)
    assert report(app)["drill"]["ok"] is False


def test_an_old_drill_doesnt_count(primed, app):
    drill(primed)
    rearm(primed)
    assert report(app, days=89)["drill"]["ok"] is True
    assert report(app, days=91)["drill"]["ok"] is False


def test_no_drill_while_tripped_and_it_is_audited(primed, app):
    drill(primed)
    assert primed.post("/api/bots/drill", json={}, headers=H).status_code == 409
    entry = primed.get("/api/audit?q=bots.kill").json()[0]
    assert entry["detail"].startswith("drill: monthly drill")


# ---- the limits self-check -------------------------------------------------------------------


def test_the_selfcheck_passes_and_never_touches_this_database(primed, app):
    b = make(primed)
    result = selfcheck(primed)
    assert result["passed"] and len(result["results"]) == 6
    assert result["risk_code"] == readiness.risk_code()
    assert primed.get("/api/bots").json()["kill"]["tripped"] is False  # it tripped its own
    assert [x["id"] for x in primed.get("/api/bots").json()["bots"]] == [b["id"]]
    assert "bots.selfcheck" in [e["action"] for e in primed.get("/api/audit?q=bots.").json()]


def test_the_selfcheck_catches_a_broken_engine(monkeypatch):
    monkeypatch.setattr(bots, "check_risk", lambda *a, **k: None)  # limits switched off
    result = readiness.selfcheck()
    failed = {r["name"] for r in result["results"] if not r["ok"]}
    assert result["passed"] is False and failed == {"coin's loss", "day's loss"}


def test_a_changed_engine_needs_a_new_selfcheck(primed, app, monkeypatch):
    selfcheck(primed)
    assert report(app)["selfcheck"]["ok"] is True
    monkeypatch.setattr(readiness, "risk_code", lambda: "something-else")
    c = report(app)["selfcheck"]
    assert c["ok"] is False and c["outdated"] is True


# ---- who may ---------------------------------------------------------------------------------


def test_who_may_check_and_drill(primed, app):
    viewer = user_with(app, primed, "readyviewer", ["bots.view"])
    assert viewer.get("/api/bots/readiness").status_code == 200
    assert viewer.post("/api/bots/drill", json={}, headers=H).status_code == 403
    assert viewer.post("/api/bots/selfcheck", headers=H).status_code == 403
    stopper = user_with(app, primed, "drillstopper", ["bots.view", "bots.stop"])
    assert stopper.post("/api/bots/selfcheck", headers=H).status_code == 403
    assert stopper.post("/api/bots/drill", json={}, headers=H).status_code == 200
    nobody = user_with(app, primed, "readynobody", ["prices.view"])
    assert nobody.get("/api/bots/readiness").status_code == 403


def test_the_command_line(primed, app, capsys, monkeypatch):
    import app.cli.bot as bot_cli
    from app import cli

    make(primed, params=PLAN)
    monkeypatch.setattr(bot_cli, "open_db", lambda settings: (None, app.state.session_factory))
    assert cli.main(["bot", "readiness"]) == 0
    assert "Not ready" in capsys.readouterr().out
    assert cli.main(["bot", "drill"]) == 0
    assert "1 bot(s) stopped" in capsys.readouterr().out
    assert cli.main(["bot", "drill"]) == 1  # already tripped
    assert cli.main(["bot", "rearm", "--yes"]) == 0
    assert cli.main(["bot", "selfcheck"]) == 0
    assert "stale prices" in capsys.readouterr().out
    assert cli.main(["bot", "readiness"]) == 0
    out = capsys.readouterr().out
    assert "✓ kill switch drill" in out and "✓ limits self-check" in out


def test_a_reason_is_never_a_seed_phrase(primed, capsys, app, monkeypatch):
    import app.cli.bot as bot_cli
    from app import cli

    phrase = " ".join(["zoo"] * 11 + ["wrong"])
    for path in ("/api/bots/kill", "/api/bots/drill"):
        r = primed.post(path, json={"reason": phrase}, headers=H)
        assert r.status_code == 422 and "zoo" not in r.text
    assert primed.get("/api/bots").json()["kill"]["tripped"] is False
    monkeypatch.setattr(bot_cli, "open_db", lambda settings: (None, app.state.session_factory))
    assert cli.main(["bot", "stop", "--all", "--reason", phrase]) == 1
    assert "zoo" not in capsys.readouterr().out


def test_the_cli_kill_switch_waits_out_a_busy_database(primed, app, monkeypatch, capsys):
    """If the server is writing, SQLite says "database is locked": the CLI tries again."""
    from sqlalchemy.exc import OperationalError

    import app.cli.bot as bot_cli
    from app import cli

    calls = []
    real = bots.trip

    def busy_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))
        return real(*a, **k)

    monkeypatch.setattr(bot_cli, "open_db", lambda settings: (None, app.state.session_factory))
    monkeypatch.setattr(bots, "trip", busy_once)
    assert cli.main(["bot", "stop", "--all"]) == 0
    assert len(calls) == 2 and "trying again" in capsys.readouterr().out
    with app.state.session_factory() as db:
        assert bots.kill_state(db)["tripped"] is True


def test_a_check_without_prices_doesnt_count(primed, app, monkeypatch):
    """Running, but its coin has no live price: the check ran, the bot couldn't trade."""
    make(primed)
    now = utcnow()
    tick(app, now)
    monkeypatch.setattr(bots, "live_prices", lambda *a: None)
    for hours in (5, 10, 15, 20, 25):  # the check keeps running, never with prices
        tick(app, now + timedelta(hours=hours))
    with app.state.session_factory() as db:
        (row,) = readiness.report(db, now + timedelta(hours=25))["bots"]
    assert row["clean_days"] == 0
