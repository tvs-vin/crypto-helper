"""`crypto-helper live ...`: live trading (phase 4) from the server's command line. `live off`
switches live trading off on every exchange at once, without the web server."""

from sqlalchemy import func, select

from app import readiness
from app import trading as tr
from app.audit import record
from app.cli.common import CLI_ACTOR, CliError, bad, load_settings, ok, open_db, warn
from app.models import TradingKey


def live(action: str) -> int:
    settings = load_settings()
    _, factory = open_db(settings)
    with factory() as db:
        if action == "status":
            on = [k for k, v in tr.switches(db).items() if v]
            print(
                ok(f"Live trading switched on for: {', '.join(on)}")
                if on
                else "Live trading is switched off on every exchange."
            )
            keys = db.execute(select(TradingKey.kind, func.count()).group_by(TradingKey.kind)).all()
            for kind, n in keys:
                print(f"  {n} trading key(s) for {kind}")
            if not keys:
                print("  No trading keys.")
            r = readiness.report(db, test=readiness.test_clock(settings))
            print(
                ok("Readiness: green, live trading may run.")
                if r["live_allowed"]
                else warn("Readiness: not green, so no live order can be placed (rule 10).")
            )
            return 0
        if action == "off":
            was = tr.all_off(db, CLI_ACTOR)
            detail = "live trading off on every exchange"
            if was:
                detail += f" (was on: {', '.join(was)})"
            record(db, "services.live", user_id=None, username=CLI_ACTOR, detail=detail)
            db.commit()
            print(ok("Live trading is switched off on every exchange."))
            if was:
                print(bad(f"It was on for: {', '.join(was)}. Super can switch it on again."))
            return 0
    raise CliError(f"Unknown action {action!r}")
