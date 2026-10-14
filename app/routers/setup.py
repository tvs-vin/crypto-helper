from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.audit import write_audit
from app.db import get_db
from app.models import User
from app.permissions import SUPER_USERNAME
from app.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    tokens_equal,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


def _any_user(db: DbSession) -> bool:
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


@router.get("/status")
def setup_status(db: DbSession = Depends(get_db)):
    return {"setup_required": not _any_user(db)}


@router.post("", status_code=201)
def do_setup(body: SetupRequest, request: Request, db: DbSession = Depends(get_db)):
    if _any_user(db):
        raise HTTPException(status_code=409, detail="Setup already completed")
    expected = request.app.state.setup_token
    if expected is None or not tokens_equal(body.token, expected):
        write_audit(db, request, "setup.fail", detail="bad setup token")
        db.commit()
        raise HTTPException(status_code=403, detail="Invalid setup token")
    user = User(
        username=SUPER_USERNAME,
        password_hash=hash_password(body.password),
        permissions=[],
        is_super=True,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with a concurrent setup: the unique username constraint decides.
        db.rollback()
        raise HTTPException(status_code=409, detail="Setup already completed") from None
    write_audit(db, request, "setup", user=user)
    db.commit()
    request.app.state.setup_token = None
    return {"username": user.username}
