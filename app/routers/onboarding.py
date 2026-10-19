"""The walkthrough and the Getting started checklist (12a). Reading works while an account
rule is pending (the walkthrough shows what to do); everything else needs a usable account."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from app import onboarding as ob
from app.audit import write_audit
from app.db import get_db
from app.deps import current_session, current_user
from app.models import Session, User

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

Step = Literal[
    "welcome", "personalise", "notifications", "tour",
    "key_backup", "network", "services", "data", "people",
]  # fmt: skip


@router.get("")
def get_onboarding(
    request: Request,
    found: tuple[Session, User] = Depends(current_session),
    db: DbSession = Depends(get_db),
):
    return ob.summary(db, found[1], request.app.state.settings)


@router.post("/steps/{step}")
def finish_step(
    step: Step, request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Tick a step that's about looking at something (the others tick themselves)."""
    if step in ob.SERVER_MARKS:
        if not me.is_super:
            raise HTTPException(status_code=403, detail="Only super sets up the server")
        ob.mark_server(db, step, me.username)
        # Install-wide, and the key backup is a promise worth having on record.
        write_audit(db, request, "onboarding.server", user=me, detail=step)
    else:
        ob.mark_account(me, step)
    db.commit()
    return ob.summary(db, me, request.app.state.settings)


@router.post("/finish")
def finish(request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The walkthrough was finished or skipped: don't open it at sign-in any more."""
    me.onboarding = {**ob.account_state(me), "finished": True}
    db.commit()
    return ob.summary(db, me, request.app.state.settings)


@router.post("/restart")
def restart(request: Request, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """Run the walkthrough again at the next sign-in (Getting started → Walk me through it)."""
    me.onboarding = {**ob.account_state(me), "finished": False}
    db.commit()
    return ob.summary(db, me, request.app.state.settings)
