"""Uploaded themes: private to whoever uploads them; an admin can publish one for everyone."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import themes
from app.audit import write_audit
from app.db import get_db
from app.deps import current_user, effective_permissions, require_permission
from app.models import User, UserTheme

router = APIRouter(prefix="/api/themes", tags=["themes"])
MAX_PER_USER = 20


def _out(t: UserTheme, me: User, owners: dict[int, str]) -> dict:
    return {
        "id": t.id,
        "key": f"custom:{t.id}",
        "name": t.name,
        "author": t.data.get("author", ""),
        "owner": owners.get(t.owner_id),
        "published": t.published,
        "mine": t.owner_id == me.id,
        "colors": {k: t.data["colors"][k] for k in ("desktop", "surface", "accent")},
    }


def visible(db: DbSession, me: User, theme_id: int) -> UserTheme:
    t = db.get(UserTheme, theme_id)
    if t is None or (t.owner_id != me.id and not t.published):
        raise HTTPException(status_code=404, detail="Theme not found")
    return t


@router.get("")
def list_themes(me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(UserTheme)
        .where(or_(UserTheme.owner_id == me.id, UserTheme.published.is_(True)))
        .order_by(UserTheme.name)
    ).all()
    owners = dict(
        db.execute(
            select(User.id, User.username).where(User.id.in_({t.owner_id for t in rows}))
        ).all()
    )
    return {
        "builtin": list(themes.BUILTIN),
        "custom": [_out(t, me, owners) for t in rows],
        "can_publish": "themes.publish" in effective_permissions(me),
        "max_per_user": MAX_PER_USER,
    }


@router.get("/{theme_id}")
def get_theme(theme_id: int, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    """The .ctheme itself (to apply or download)."""
    return visible(db, me, theme_id).data


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str  # the .ctheme file's text


@router.post("", status_code=201)
def upload(
    body: Upload,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    try:
        theme = themes.parse(body.content)
    except ValidationError as e:
        # Say where and why only. str(e) would include the rejected values themselves.
        problems = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg'].removeprefix('Value error, ')}"
            for err in e.errors()
        ]
        return JSONResponse(
            {
                "detail": "That theme can't be used: " + "; ".join(problems)[:600],
                "problems": problems[:30],
            },
            status_code=422,
        )
    except ValueError as e:  # not JSON / not a .ctheme / too big: fixed messages, no input
        return JSONResponse({"detail": f"That theme can't be used: {e}"}, status_code=422)
    count = (
        db.scalar(select(func.count()).select_from(UserTheme).where(UserTheme.owner_id == me.id))
        or 0
    )
    if count >= MAX_PER_USER:
        return JSONResponse(
            {"detail": f"You can keep at most {MAX_PER_USER} themes. Delete one first."},
            status_code=409,
        )
    t = UserTheme(owner_id=me.id, name=theme.name, data=theme.model_dump(mode="json"))
    db.add(t)
    db.flush()
    write_audit(db, request, "theme.upload", user=me, detail=f"{t.name} (id {t.id})")
    db.commit()
    return _out(t, me, {me.id: me.username})


class Publish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published: bool


@router.post("/{theme_id}/publish")
def publish(
    theme_id: int,
    body: Publish,
    request: Request,
    me: User = Depends(require_permission("themes.publish")),
    db: DbSession = Depends(get_db),
):
    t = db.get(UserTheme, theme_id)
    # Admins can publish their own themes and unpublish anyone's published one.
    if t is None or (t.owner_id != me.id and not t.published):
        raise HTTPException(status_code=404, detail="Theme not found")
    t.published = body.published
    write_audit(
        db,
        request,
        "theme.publish" if body.published else "theme.unpublish",
        user=me,
        detail=f"{t.name} (id {t.id})",
    )
    db.commit()
    return {"id": t.id, "published": t.published}


@router.delete("/{theme_id}", status_code=204)
def delete(
    theme_id: int,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    t = db.get(UserTheme, theme_id)
    if t is None or t.owner_id != me.id:
        raise HTTPException(status_code=404, detail="Theme not found")
    write_audit(db, request, "theme.delete", user=me, detail=f"{t.name} (id {t.id})")
    db.delete(t)
    db.commit()
    return JSONResponse(None, status_code=204)
