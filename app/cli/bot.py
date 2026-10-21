"""`crypto-helper bot ...`: paper-trading bots from the server's command line (12d). The kill
switch works here even if the web UI doesn't."""

from sqlalchemy import select

from app import bots as engine
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
    raise CliError(f"Unknown action {action!r}")
