"""`crypto-helper bot ...`: paper-trading bots from the server's command line (12d). The kill
switch works here even if the web UI doesn't."""

from sqlalchemy import select

from app import bots as engine
from app import readiness
from app.audit import record
from app.cli.common import CLI_ACTOR, CliError, bad, load_settings, ok, open_db, warn
from app.models import Bot


def bot(action: str, everything: bool = False, reason: str = "", yes: bool = False) -> int:
    _, factory = open_db(load_settings())
    with factory() as db:
        kill = engine.kill_state(db)
        if action in ("list", "status"):
            if kill["tripped"]:
                print(
                    bad(
                        f"Kill switch TRIPPED {kill.get('at', '')} by {kill.get('by')}: "
                        f"{kill.get('reason')}"
                    )
                )
            else:
                print(ok("Kill switch armed: bots may trade (on paper)."))
            rows = db.scalars(select(Bot).order_by(Bot.id)).all()
            if action == "status":
                running = sum(b.status == "running" for b in rows)
                print(f"{len(rows)} bot(s), {running} running.")
                return 0
            if not rows:
                print("No bots.")
            for b in rows:
                why = f" ({b.status_reason})" if b.status_reason else ""
                print(f"  {b.id:>3}  {b.status:<8} {b.name}{why}")
            return 0
        if action == "stop":
            if not everything:
                raise CliError("Use `bot stop --all`: it stops every bot (the kill switch).")
            if not engine.trip(db, None, CLI_ACTOR, reason or "stopped from the command line"):
                print(warn("The kill switch was already tripped."))
                return 0
            db.commit()
            print(ok("Kill switch tripped: every bot stopped, waiting orders cancelled."))
            print("Re-arm it with `crypto-helper bot rearm` (bots then start one by one).")
            return 0
        if action == "rearm":
            if not kill["tripped"]:
                print("The kill switch isn't tripped.")
                return 0
            if not yes:
                answer = input(
                    "Re-arm the kill switch? Bots stay paused until started. Type REARM: "
                )
                if answer.strip() != "REARM":
                    print("Cancelled. Nothing was changed.")
                    return 1
            engine.rearm(db, None, CLI_ACTOR)
            db.commit()
            print(ok("Kill switch re-armed. Start bots again in Paper trading."))
            return 0
        if action == "drill":
            if kill["tripped"]:
                raise CliError("The kill switch is already tripped: re-arm it first.")
            engine.trip(db, None, CLI_ACTOR, reason or "drill from the command line", drill=True)
            db.commit()
            answer = engine.BotJob(None, factory).tick()  # it must refuse before anything else
            engine.drill_checked(db, answer)
            db.commit()
            d = engine.kill_state(db)["drill"]
            good = d["all_stopped"] and d["check_refused"]
            print((ok if good else bad)(
                f"Drill: {d['bots_stopped']} bot(s) stopped, {d['orders_cancelled']} order(s) "
                f"cancelled, bot check {'refused to trade' if d['check_refused'] else 'RAN'}."
            ))  # fmt: skip
            print("Re-arm to complete it: crypto-helper bot rearm (bots then start one by one).")
            return 0 if good else 1
        if action == "selfcheck":
            result = readiness.selfcheck()
            readiness.save_selfcheck(db, result, CLI_ACTOR)
            failed = [r["name"] for r in result["results"] if not r["ok"]]
            detail = "passed" if result["passed"] else f"FAILED: {', '.join(failed)}"
            record(db, "bots.selfcheck", user_id=None, username=CLI_ACTOR,
                   detail=f"{detail} ({result['risk_code']})")  # fmt: skip
            db.commit()
            for r in result["results"]:
                mark = ok("ok") if r["ok"] else bad("FAILED")
                print(
                    f"  {mark}  {r['name']}: {r['shows']}"
                    + (f" ({r['problem']})" if r["problem"] else "")
                )
            return 0 if result["passed"] else 1
        if action == "readiness":
            r = readiness.report(db)
            print((ok if r["ready"] else warn)(
                "Ready for live trading (phase 4)." if r["ready"]
                else "Not ready for live trading yet."
            ))  # fmt: skip
            d = r["drill"]
            last = d["last"]
            when = f" (last {last['at']})" if last else " (none yet: crypto-helper bot drill)"
            print(
                f"  {'✓' if d['ok'] else '✗'} kill switch drill in the last {d['days']} days{when}"
            )
            c = r["selfcheck"]
            why = "" if c["ok"] else (" (the risk code changed: run it again)" if c["outdated"]
                                      else " (crypto-helper bot selfcheck)")  # fmt: skip
            print(f"  {'✓' if c['ok'] else '✗'} limits self-check passed{why}")
            if not r["bots"]:
                print(f"  ✗ no bots: one must run cleanly for {r['clean_days']} days")
            for b in r["bots"]:
                print(f"  {'✓' if b['ok'] else '✗'} {b['name']}: "
                      + "; ".join(c2["detail"] for c2 in b["checks"]))  # fmt: skip
            return 0
    raise CliError(f"Unknown action {action!r}")
