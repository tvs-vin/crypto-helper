"""Uploaded themes: private to whoever uploads them; an admin can publish one for everyone."""

import asyncio
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import theme_bundle, themes
from app import wallpapers as wp
from app.audit import write_audit
from app.db import IMMEDIATE, get_db
from app.deps import current_user, effective_permissions, require_permission
from app.models import User, UserTheme, Wallpaper
from app.routers import wallpapers as wallpapers_router

router = APIRouter(prefix="/api/themes", tags=["themes"])
MAX_PER_USER = 20


def _out(t: UserTheme, me: User, owners: dict[int, str]) -> dict:
    wallpaper = t.data.get("wallpaper") or ""
    return {
        "id": t.id,
        "key": f"custom:{t.id}",
        "name": t.name,
        "author": t.data.get("author", ""),
        "owner": owners.get(t.owner_id),
        "published": t.published,
        "mine": t.owner_id == me.id,
        "colors": {k: t.data["colors"][k] for k in ("desktop", "surface", "accent")},
        "wallpaper": wallpaper or None,
        "icons": len(set(t.data.get("icons") or {}) | set(t.data.get("icon_images") or {})),
        "bundle": bool(wallpaper.startswith("user:") or t.data.get("icon_images")),
    }


def _problems(e: ValidationError) -> JSONResponse:
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
        data = _with_clean_icons(theme, {})
    except ValidationError as e:
        return _problems(e)
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
    t = UserTheme(owner_id=me.id, name=theme.name, data=data)
    db.add(t)
    db.flush()
    write_audit(db, request, "theme.upload", user=me, detail=f"{t.name} (id {t.id})")
    db.commit()
    return _out(t, me, {me.id: me.username})


def _with_clean_icons(theme: themes.Theme, icon_files: dict[str, bytes]) -> dict:
    """The theme as stored: every icon picture re-encoded here (from the JSON or the bundle's
    icons/ folder), never kept as uploaded."""
    import base64

    data = theme.model_dump(mode="json")
    images = {}
    for name, uri in data.get("icon_images", {}).items():
        images[name] = themes.clean_icon(base64.b64decode(uri.split(",", 1)[1]))
    for name, png in icon_files.items():
        if name not in themes.ICON_NAMES:
            raise ValueError(f"icons/{name}.png: no icon is called {name!r}")
        images[name] = themes.clean_icon(png)
    data["icon_images"] = images
    return data


# ---- bundles (theme + wallpapers + icons) ---------------------------------------------------


@router.post("/upload", status_code=201)
async def upload_file(request: Request):
    """A .ctheme file as the raw body: plain JSON, or a bundle (zip). Converting a bundle's
    wallpapers can take a while, so no database lock is held meanwhile."""
    me = await run_in_threadpool(wallpapers_router._who, request)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > theme_bundle.MAX_BUNDLE:
            raise HTTPException(status_code=413, detail="That file is too big.")
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        if theme_bundle.is_bundle(data):
            b = theme_bundle.read(data)
            theme = themes.parse(b.theme_json, bundle=True)
        else:
            b = theme_bundle.Bundle(theme_json=data)
            theme = themes.parse(data)
        stored = _with_clean_icons(theme, b.icons)
        wanted = theme.wallpaper if (theme.wallpaper or "").startswith("wallpapers/") else None
        if wanted and wanted not in b.wallpapers:
            raise ValueError(f"wallpaper: {wanted} isn't in the bundle")
    except ValidationError as e:
        return _problems(e)
    except ValueError as e:  # BundleError too: fixed messages, never the input
        return JSONResponse({"detail": f"That theme can't be used: {e}"}, status_code=422)
    converted = {}
    if b.wallpapers:
        lock: asyncio.Semaphore = request.app.state.wallpaper_lock
        if lock.locked():
            raise HTTPException(
                status_code=429, detail="A wallpaper is being processed; try again in a moment."
            )
        async with lock:
            for name, content in b.wallpapers.items():
                try:
                    converted[name] = await run_in_threadpool(wp.process, content)
                except wp.WallpaperError as e:
                    return JSONResponse(
                        {"detail": f"That theme can't be used: {name}: {e}"}, status_code=422
                    )
    default = wanted or (next(iter(converted)) if converted else None)
    return await run_in_threadpool(_store_bundle, request, me, theme, stored, converted, default)


def _store_bundle(request, me: User, theme, stored: dict, converted: dict, default) -> dict:
    with request.app.state.session_factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        count = db.scalar(
            select(func.count()).select_from(UserTheme).where(UserTheme.owner_id == me.id)
        )
        if (count or 0) >= MAX_PER_USER:
            return JSONResponse(
                {"detail": f"You can keep at most {MAX_PER_USER} themes. Delete one first."},
                status_code=409,
            )
        t = UserTheme(owner_id=me.id, name=theme.name, data=stored)
        db.add(t)
        db.flush()
        base = wallpapers_router.folder(request)
        for name, p in converted.items():
            token = secrets.token_hex(12)
            w = Wallpaper(owner_id=me.id, theme_id=t.id, name=Path(name).stem[:60], kind=p.kind,
                          file=f"{token}.{p.ext}", poster=f"{token}.poster.webp", mime=p.mime,
                          width=p.width, height=p.height, duration_ms=p.duration_ms,
                          bytes=len(p.data) + len(p.poster))  # fmt: skip
            (base / w.file).write_bytes(p.data)
            (base / w.poster).write_bytes(p.poster)
            db.add(w)
            db.flush()
            if name == default:
                t.data = {**t.data, "wallpaper": f"user:{w.id}"}
        detail = f"{t.name} (id {t.id})"
        if converted or stored.get("icon_images") or stored.get("icons"):
            icons = len(stored.get("icon_images") or {}) + len(stored.get("icons") or {})
            detail += f": {len(converted)} wallpaper(s), {icons} icon(s)"
        write_audit(db, request, "theme.upload", user=me, detail=detail)
        db.commit()
        return _out(t, me, {me.id: me.username})


@router.get("/{theme_id}/bundle")
def download_bundle(
    theme_id: int,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    """The theme as a bundle: theme.json, its wallpapers (as converted) and its icon pictures."""
    import base64

    t = visible(db, me, theme_id)
    data = dict(t.data)
    files, icons = {}, {}
    rows = db.scalars(
        select(Wallpaper).where(Wallpaper.theme_id == t.id).order_by(Wallpaper.id)
    ).all()
    base = wallpapers_router.folder(request)
    for w in rows:
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", w.name)[:50] or "wallpaper"
        name = f"wallpapers/{safe}-{w.id}.{w.file.rsplit('.', 1)[1]}"
        if (base / w.file).is_file():
            files[name] = (base / w.file).read_bytes()
            if data.get("wallpaper") == f"user:{w.id}":
                data["wallpaper"] = name
    if (data.get("wallpaper") or "").startswith("user:"):
        data["wallpaper"] = None  # its file is gone
    for name, uri in (data.pop("icon_images", None) or {}).items():
        icons[name] = base64.b64decode(uri.split(",", 1)[1])
    slug = re.sub(r"[^a-z0-9]+", "-", t.name.lower()).strip("-") or "theme"
    return Response(
        theme_bundle.build(data, files, icons),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.ctheme"'},
    )


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
    base = wallpapers_router.folder(request)
    for w in db.scalars(select(Wallpaper).where(Wallpaper.theme_id == t.id)).all():
        wallpapers_router.remove_files(base, w)  # the rows go with the theme
    db.delete(t)
    db.commit()
    return JSONResponse(None, status_code=204)
