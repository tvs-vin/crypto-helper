"""Wallpapers: a built-in set, plus uploads (checked and re-encoded, see app/wallpapers.py).
Uploads are private to whoever made them; an admin with themes.publish can publish one.

Uploading takes a while (videos are re-encoded), so that endpoint doesn't hold the database
write lock while it works: it signs the request in, lets go, processes, then writes."""

import asyncio
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import wallpapers as wp
from app.audit import write_audit
from app.db import IMMEDIATE, get_db
from app.deps import SESSION_COOKIE, current_user, effective_permissions, lookup_session
from app.models import User, UserTheme, Wallpaper
from app.secret_guard import find_secret

router = APIRouter(prefix="/api/wallpapers", tags=["wallpapers"])
MAX_PER_USER = 20
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
STATIC = "/static/wallpapers"

# The built-in set (app/web/wallpapers/, made by toolchain/wallpapers/make.py).
BUILTINS: dict[str, tuple[str, str, str]] = {
    "aurora": ("Aurora", "image", "aurora.webp"),
    "drift": ("Drift", "video", "drift.webm"),
    "dusk": ("Dusk", "image", "dusk.webp"),
    "midnight-grid": ("Midnight grid", "image", "midnight-grid.webp"),
    "paper": ("Paper", "image", "paper.webp"),
}


def folder(request: Request) -> Path:
    f = Path(request.app.state.settings.state_dir) / "wallpapers"
    f.mkdir(mode=0o700, parents=True, exist_ok=True)
    return f


def builtin_out(slug: str) -> dict:
    name, kind, file = BUILTINS[slug]
    return {
        "key": f"builtin:{slug}",
        "name": name,
        "kind": kind,
        "url": f"{STATIC}/{file}",
        "poster": f"{STATIC}/{slug}.poster.webp",
        "builtin": True,
        "mine": False,
        "published": True,
    }


def out(w: Wallpaper, me: User, owners: dict[int, str]) -> dict:
    return {
        "key": f"user:{w.id}",
        "id": w.id,
        "name": w.name,
        "kind": w.kind,
        "url": f"/api/wallpapers/{w.id}/file",
        "poster": f"/api/wallpapers/{w.id}/poster",
        "width": w.width,
        "height": w.height,
        "duration_ms": w.duration_ms,
        "bytes": w.bytes,
        "builtin": False,
        "mine": w.owner_id == me.id,
        "owner": owners.get(w.owner_id),
        "published": w.published,
        "theme_id": w.theme_id,
    }


def can_see(db: DbSession, me: User, w: Wallpaper) -> bool:
    if me.is_super or w.owner_id == me.id or w.published:
        return True
    if w.theme_id is not None:  # came in a theme: visible to whoever can see the theme
        t = db.get(UserTheme, w.theme_id)
        return bool(t and (t.published or t.owner_id == me.id))
    return False


def _owners(db: DbSession, ids) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(set(ids)))).all())


@router.get("")
def list_wallpapers(me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    rows = db.scalars(
        select(Wallpaper)
        .where(Wallpaper.theme_id.is_(None))
        .where(or_(Wallpaper.owner_id == me.id, Wallpaper.published.is_(True)))
        .order_by(Wallpaper.created_at.desc())
    ).all()
    owners = _owners(db, [w.owner_id for w in rows])
    return {
        "builtin": [builtin_out(s) for s in BUILTINS],
        "uploaded": [out(w, me, owners) for w in rows],
        "can_publish": "themes.publish" in effective_permissions(me),
        "max_per_user": MAX_PER_USER,
        "video": wp.have_ffmpeg(),
        "accept": "image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm",
    }


def _visible(db: DbSession, me: User, wallpaper_id: int) -> Wallpaper:
    w = db.get(Wallpaper, wallpaper_id)
    if w is None or not can_see(db, me, w):
        raise HTTPException(status_code=404, detail="Wallpaper not found")
    return w


@router.get("/{wallpaper_id}")
def one(wallpaper_id: int, me: User = Depends(current_user), db: DbSession = Depends(get_db)):
    w = _visible(db, me, wallpaper_id)
    return out(w, me, _owners(db, [w.owner_id]))


def _file(request: Request, name: str, mime: str) -> FileResponse:
    path = folder(request) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Wallpaper file missing")
    # Random file names never change, so browsers may keep them (this user only).
    return FileResponse(
        path, media_type=mime, headers={"Cache-Control": "private, max-age=604800, immutable"}
    )


@router.get("/{wallpaper_id}/file")
def file(
    wallpaper_id: int,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    w = _visible(db, me, wallpaper_id)
    return _file(request, w.file, w.mime)


@router.get("/{wallpaper_id}/poster")
def poster(
    wallpaper_id: int,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    w = _visible(db, me, wallpaper_id)
    return _file(request, w.poster, "image/webp")


# ---- upload ----------------------------------------------------------------------------------


def _who(request: Request) -> User:
    """Sign the request in without keeping a database session (or its lock) open."""
    with request.app.state.session_factory() as db:
        found = lookup_session(db, request.cookies.get(SESSION_COOKIE))
        db.commit()
        if not found or not found[1].is_active:
            raise HTTPException(status_code=401, detail="Not signed in")
        db.expunge(found[1])
        return found[1]


def _store(request: Request, me: User, name: str, p: wp.Processed) -> dict:
    with request.app.state.session_factory() as db:
        db.connection(execution_options={IMMEDIATE: True})
        mine = db.scalar(
            select(func.count())
            .select_from(Wallpaper)
            .where(Wallpaper.owner_id == me.id, Wallpaper.theme_id.is_(None))
        )
        if (mine or 0) >= MAX_PER_USER:
            raise HTTPException(status_code=409, detail=f"At most {MAX_PER_USER} wallpapers each.")
        used = db.scalar(select(func.coalesce(func.sum(Wallpaper.bytes), 0)))
        if used + len(p.data) > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=507, detail="The server's wallpaper space is full.")
        token = secrets.token_hex(12)
        base = folder(request)
        file_name, poster_name = f"{token}.{p.ext}", f"{token}.poster.webp"
        (base / file_name).write_bytes(p.data)
        (base / poster_name).write_bytes(p.poster)
        w = Wallpaper(
            owner_id=me.id,
            name=name,
            kind=p.kind,
            file=file_name,
            poster=poster_name,
            mime=p.mime,
            width=p.width,
            height=p.height,
            duration_ms=p.duration_ms,
            bytes=len(p.data) + len(p.poster),
        )
        db.add(w)
        db.flush()
        write_audit(db, request, "wallpaper.upload", user=me, detail=f"{name} (id {w.id}) {p.kind}")
        db.commit()
        return out(w, me, {me.id: me.username})


@router.post("", status_code=201)
async def upload(request: Request, name: str = Query(min_length=1, max_length=60)):
    me = await run_in_threadpool(_who, request)
    name = name.strip()
    if not name or find_secret(name):
        raise HTTPException(status_code=422, detail="Give it a plain name.")
    if int(request.headers.get("content-length") or 0) > wp.MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="That file is too big.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > wp.MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="That file is too big.")
        chunks.append(chunk)
    if not size:
        raise HTTPException(status_code=422, detail="The file is empty.")
    lock: asyncio.Semaphore = request.app.state.wallpaper_lock
    if lock.locked():
        raise HTTPException(
            status_code=429, detail="Another wallpaper is being processed; try again in a moment."
        )
    async with lock:
        try:
            processed = await run_in_threadpool(wp.process, b"".join(chunks))
        except wp.WallpaperError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
    return await run_in_threadpool(_store, request, me, name, processed)


class WallpaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=60)
    published: bool | None = None


@router.patch("/{wallpaper_id}")
def change(
    wallpaper_id: int,
    body: WallpaperPatch,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    w = _visible(db, me, wallpaper_id)
    changed = []
    if body.name is not None:
        if w.owner_id != me.id:
            raise HTTPException(status_code=403, detail="Only its owner can rename it")
        if find_secret(body.name):
            raise HTTPException(status_code=422, detail="Give it a plain name.")
        w.name = body.name.strip()
        changed.append("name")
    if body.published is not None:
        if "themes.publish" not in effective_permissions(me):
            raise HTTPException(status_code=403, detail="Publishing needs themes.publish")
        w.published = body.published
        changed.append("published" if body.published else "unpublished")
    write_audit(
        db,
        request,
        "wallpaper.update",
        user=me,
        detail=f"{w.name} (id {w.id}): {', '.join(changed)}",
    )
    db.commit()
    return out(w, me, _owners(db, [w.owner_id]))


def remove_files(base: Path, w: Wallpaper) -> None:
    for name in (w.file, w.poster):
        (base / name).unlink(missing_ok=True)


@router.delete("/{wallpaper_id}", status_code=204)
def delete(
    wallpaper_id: int,
    request: Request,
    me: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    w = _visible(db, me, wallpaper_id)
    if w.owner_id != me.id and not me.is_super:
        raise HTTPException(status_code=403, detail="Only its owner can delete it")
    if w.theme_id is not None:
        raise HTTPException(status_code=409, detail="It belongs to a theme: delete the theme")
    remove_files(folder(request), w)
    write_audit(db, request, "wallpaper.delete", user=me, detail=f"{w.name} (id {w.id})")
    db.delete(w)
    db.commit()


def sweep(state_dir: str, db: DbSession) -> int:
    """Delete wallpaper files no row points at (e.g. after their owner was deleted)."""
    base = Path(state_dir) / "wallpapers"
    if not base.is_dir():
        return 0
    known = {n for row in db.execute(select(Wallpaper.file, Wallpaper.poster)).all() for n in row}
    gone = 0
    for f in base.iterdir():
        if f.is_file() and f.name not in known:
            f.unlink(missing_ok=True)
            gone += 1
    return gone
