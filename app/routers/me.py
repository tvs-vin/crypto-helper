"""Your own preferences. Each user only ever changes their own; no permission needed."""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from sqlalchemy.orm import Session as DbSession

from app import apps
from app.db import get_db
from app.deps import current_user
from app.models import User

router = APIRouter(tags=["preferences"])
MAX_BYTES = 16 * 1024
# Every window the desktop has (the app catalog plus core windows like settings).
Panel = Literal[(*apps.APPS, *apps.CORE_APPS)]
WINDOW_ID = re.compile(r"^([a-z]+)(?::([2-9]))?$")
StateValue = Annotated[str, StringConstraints(max_length=40)] | int | bool
Column = Literal["price", "change_24h", "holdings", "value"]


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel: Panel
    # "overview" for the first window of an app, "overview:2" ... for more (older layouts
    # have no id: the window is then the first of its app).
    id: str | None = Field(default=None, max_length=16)
    # A window's own small settings (e.g. which coin an Overview charts): plain values only.
    state: dict[Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,24}$")], StateValue] = Field(
        default_factory=dict, max_length=8
    )
    x: int = Field(ge=0, le=10000)
    y: int = Field(ge=0, le=10000)
    w: int = Field(ge=120, le=10000)
    h: int = Field(ge=80, le=10000)
    open: bool = True
    minimized: bool = False
    maximized: bool = False
    z: int = Field(default=0, ge=0, le=100)


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["floating", "tiled"] = "floating"
    tiling: Literal["master", "grid"] = "master"
    windows: list[Window] = Field(default_factory=list, max_length=20)

    @field_validator("windows")
    @classmethod
    def _ids_and_limits(cls, v):
        ids = []
        for w in v:
            w.id = w.id or w.panel
            m = WINDOW_ID.match(w.id)
            if not m or m.group(1) != w.panel:
                raise ValueError(f"window id {w.id!r} doesn't match its app {w.panel!r}")
            number = int(m.group(2) or 1)
            if number > apps.max_windows(w.panel):
                raise ValueError(f"at most {apps.max_windows(w.panel)} {w.panel} windows")
            ids.append(w.id)
        if len(ids) != len(set(ids)):
            raise ValueError("each window can appear once")
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

    # A built-in theme, or "custom:<id>" for an uploaded one (yours or a published one).
    theme: str = Field(default="dark", pattern=r"^(dark|light|terminal|template|custom:\d{1,9})$")
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
