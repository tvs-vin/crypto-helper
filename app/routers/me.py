"""Your own preferences. Each user only ever changes their own; no permission needed."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.deps import current_user
from app.models import User

router = APIRouter(tags=["preferences"])
MAX_BYTES = 16 * 1024
Panel = Literal["wallets", "overview", "transfers", "users", "audit", "settings"]
Column = Literal["price", "change_24h", "holdings", "value"]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel: Panel
    x: int = Field(ge=0, le=10000)
    y: int = Field(ge=0, le=10000)
    w: int = Field(ge=120, le=10000)
    h: int = Field(ge=80, le=10000)
    open: bool = True
    z: int = Field(default=0, ge=0, le=100)


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: list[Window] = Field(default_factory=list, max_length=20)

    @field_validator("windows")
    @classmethod
    def _one_per_panel(cls, v):
        panels = [w.panel for w in v]
        if len(panels) != len(set(panels)):
            raise ValueError("each panel can appear once")
        return v


class Sort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: Literal["value", "name", "change_24h", "symbol"] = "value"
    direction: Literal["asc", "desc"] = "desc"


class Overview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[Column] = Field(
        default_factory=lambda: ["price", "change_24h", "holdings", "value"], max_length=4
    )
    sort: Sort = Field(default_factory=Sort)

    @field_validator("columns")
    @classmethod
    def _unique(cls, v):
        return list(dict.fromkeys(v))


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["dark", "light", "terminal"] = "dark"
    fiat: Literal["usd", "eur", "gbp", "jpy", "cad", "aud"] = "usd"
    watchlist: list[str] = Field(default_factory=list, max_length=50)
    overview: Overview = Field(default_factory=Overview)
    layout: Layout = Field(default_factory=Layout)
    wallet_order: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("watchlist")
    @classmethod
    def _symbols(cls, v):
        import re

        out = list(dict.fromkeys(s.strip().upper() for s in v))
        bad = [s for s in out if not re.match(r"^[A-Z0-9]{2,10}$", s)]
        if bad:
            raise ValueError("watchlist entries are symbols like BTC (2-10 letters or digits)")
        return out


def current(user: User) -> Preferences:
    """Stored preferences with defaults filled in. Anything invalid falls back to defaults
    rather than breaking the page."""
    stored = user.preferences or {}
    try:
        return Preferences(**stored)
    except (ValidationError, TypeError):
        return Preferences(**{k: v for k, v in stored.items() if k == "wallet_order"})


def _save(user: User, prefs: Preferences, db: DbSession):
    data = prefs.model_dump()
    if len(JSONResponse(data).body) > MAX_BYTES:
        return JSONResponse(
            {"detail": f"Preferences are limited to {MAX_BYTES // 1024} KB."}, status_code=413
        )
    user.preferences = data
    db.commit()
    return data


@router.get("/api/me/preferences")
def get_preferences(user: User = Depends(current_user)):
    return current(user).model_dump()


@router.put("/api/me/preferences")
def put_preferences(
    body: Preferences, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Replace all preferences (anything you leave out goes back to its default)."""
    return _save(user, body, db)


@router.patch("/api/me/preferences")
def patch_preferences(
    body: dict,
    request: Request,
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """Change only the top-level settings you send (e.g. {"theme": "light"})."""
    merged = {**current(user).model_dump(), **body}
    try:
        prefs = Preferences(**merged)
    except ValidationError as e:
        errors = [
            {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
            for err in e.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)
    return _save(user, prefs, db)
