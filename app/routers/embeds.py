"""Managing embed links (embeds.create). The links themselves are served by the embed server."""

import html
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.audit import write_audit
from app.db import get_db
from app.deps import require_permission
from app.embeds import image
from app.embeds.options import ITEMS, KINDS, EmbedOptions, base_url
from app.embeds.server import theme_for
from app.embeds.view import Unavailable, build
from app.models import Embed, User
from app.security import hash_token
from app.timeutil import utcnow

router = APIRouter(prefix="/api/embeds", tags=["embeds"])
create_perm = require_permission("embeds.create")
MAX_PER_USER = 50


def naive_utc(dt: datetime | None) -> datetime | None:
    """Stored times are naive UTC: convert an aware time first, don't just drop its offset."""
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def out(request: Request, e: Embed) -> dict:
    token = request.app.state.secret_box.decrypt(e.token_encrypted)
    url = f"{base_url(request.app.state.settings)}/embed/{token}"
    return {
        "id": e.id,
        "name": e.name,
        "kind": e.kind,
        "enabled": e.enabled,
        "expires_at": e.expires_at,
        "views": e.views,
        "last_viewed_at": e.last_viewed_at,
        "created_at": e.created_at,
        "options": e.options,
        "url": url,
        "image_url": f"{url}.png",
        "iframe": (
            f'<iframe src="{url}" width="480" height="420" loading="lazy" '
            f'style="border:0" title="{html.escape(e.name)}"></iframe>'
        ),
    }


def _mine(db: DbSession, me: User, embed_id: int) -> Embed:
    e = db.get(Embed, embed_id)
    if e is None or e.owner_id != me.id:
        raise HTTPException(status_code=404, detail="Embed not found")
    return e


def _new_token(request: Request) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(24)
    return token, hash_token(token), request.app.state.secret_box.encrypt(token)


def _problems(e: ValidationError) -> JSONResponse:
    problems = [
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
        for err in e.errors()
    ]
    return JSONResponse({"detail": "; ".join(problems)}, status_code=422)


@router.get("/meta")
def meta(request: Request, _: User = Depends(create_perm)):
    s = request.app.state.settings
    return {
        "enabled": s.embed_enabled,
        "base_url": base_url(s),
        "kinds": list(KINDS),
        "items": {
            k: {"default": d, "label": label, "sensitive": sens}
            for k, (d, label, sens) in ITEMS.items()
        },
        "enable_command": "crypto-helper embed enable",
    }


@router.get("")
def list_embeds(request: Request, me: User = Depends(create_perm), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(Embed).where(Embed.owner_id == me.id).order_by(Embed.created_at.desc())
    ).all()
    return [out(request, e) for e in rows]


class EmbedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(pattern=r"^(portfolio|wallets|prices)$")
    options: dict = Field(default_factory=dict)
    expires_at: datetime | None = None


class EmbedPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    options: dict | None = None
    enabled: bool | None = None
    expires_at: datetime | None = None


@router.post("", status_code=201)
def create(
    body: EmbedIn,
    request: Request,
    me: User = Depends(create_perm),
    db: DbSession = Depends(get_db),
):
    try:
        opts = EmbedOptions(**body.options)
    except ValidationError as e:
        return _problems(e)
    count = db.scalar(select(func.count()).select_from(Embed).where(Embed.owner_id == me.id))
    if (count or 0) >= MAX_PER_USER:
        return JSONResponse({"detail": f"At most {MAX_PER_USER} embeds each."}, status_code=409)
    _, token_hash, token_enc = _new_token(request)
    e = Embed(
        owner_id=me.id,
        name=body.name.strip(),
        kind=body.kind,
        token_hash=token_hash,
        token_encrypted=token_enc,
        options=opts.model_dump(),
        enabled=True,
        expires_at=naive_utc(body.expires_at),
    )
    db.add(e)
    db.flush()
    sensitive = [k for k, (_, _, s) in ITEMS.items() if s and opts.on(k)]
    write_audit(
        db,
        request,
        "embed.create",
        user=me,
        detail=f"{e.name} (id {e.id}) kind={e.kind}"
        + (f"; shows {', '.join(sensitive)}" if sensitive else ""),
    )
    db.commit()
    return out(request, e)


@router.patch("/{embed_id}")
def change(
    embed_id: int,
    body: EmbedPatch,
    request: Request,
    me: User = Depends(create_perm),
    db: DbSession = Depends(get_db),
):
    e = _mine(db, me, embed_id)
    data = body.model_dump(exclude_unset=True)
    if "options" in data:
        try:
            e.options = EmbedOptions(**data["options"]).model_dump()
        except ValidationError as err:
            return _problems(err)
    if data.get("name"):
        e.name = data["name"].strip()
    if "enabled" in data and data["enabled"] is not None:
        e.enabled = data["enabled"]
    if "expires_at" in data:
        e.expires_at = naive_utc(data["expires_at"])
    write_audit(
        db,
        request,
        "embed.update",
        user=me,
        detail=f"{e.name} (id {e.id}): {', '.join(sorted(data))}",
    )
    db.commit()
    return out(request, e)


@router.post("/{embed_id}/rotate")
def rotate(
    embed_id: int,
    request: Request,
    me: User = Depends(create_perm),
    db: DbSession = Depends(get_db),
):
    """A new link; the old one stops working at once."""
    e = _mine(db, me, embed_id)
    _, e.token_hash, e.token_encrypted = _new_token(request)
    write_audit(db, request, "embed.rotate", user=me, detail=f"{e.name} (id {e.id})")
    db.commit()
    return out(request, e)


@router.delete("/{embed_id}", status_code=204)
def delete(
    embed_id: int,
    request: Request,
    me: User = Depends(create_perm),
    db: DbSession = Depends(get_db),
):
    e = _mine(db, me, embed_id)
    write_audit(db, request, "embed.delete", user=me, detail=f"{e.name} (id {e.id})")
    db.delete(e)
    db.commit()
    return Response(status_code=204)


@router.get("/{embed_id}/preview.png")
def preview(
    embed_id: int,
    request: Request,
    me: User = Depends(create_perm),
    db: DbSession = Depends(get_db),
):
    """The same image Discord would show, rendered here so it works even with the embed
    server off."""
    e = _mine(db, me, embed_id)
    try:
        view = build(db, e, request.app.state.prices)
    except Unavailable:
        return JSONResponse({"detail": "This embed is off or expired"}, status_code=409)
    png = image.render(view, theme_for(db, EmbedOptions(**e.options), e.owner_id))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


__all__ = ["router", "utcnow"]
