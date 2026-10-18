"""The embed-only server (`crypto-helper serve --embed`).

It serves embed pages, their stylesheet and their preview image, plus fonts. There is no
login, no API and no way to change anything: even a mistake in exposing this port can't
reach accounts or data beyond what each embed shows. Unknown, disabled and expired embeds
all get the same 404.
"""

import json
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from sqlalchemy import select, update

from app import migrate
from app.config import Settings
from app.db import IMMEDIATE, make_engine, make_session_factory
from app.embeds import image, page
from app.embeds.options import EmbedOptions
from app.embeds.view import Unavailable, build, check_usable
from app.models import Embed, UserTheme
from app.netaccess import client_allowed, parse_networks
from app.prices.providers import make_provider
from app.prices.service import PriceService
from app.security import hash_token
from app.timeutil import utcnow

WEB = Path(__file__).resolve().parents[1] / "web"
STATIC = Path(__file__).resolve().parent / "static"
ASSETS = {
    "embed.css": (STATIC / "embed.css", "text/css"),
    "fonts/inter.woff2": (WEB / "fonts" / "inter.woff2", "font/woff2"),
    "fonts/monasans.woff2": (WEB / "fonts" / "monasans.woff2", "font/woff2"),
}
NOT_FOUND = "Not found"
IMAGE_CACHE_SECONDS = 120


def theme_for(db, opts: EmbedOptions, owner_id: int) -> dict:
    """The embed's theme: built-in, or an uploaded one its owner can still use."""
    if opts.theme.startswith("custom:"):
        t = db.get(UserTheme, int(opts.theme.split(":")[1]))
        if t is not None and (t.owner_id == owner_id or t.published):
            return t.data
        name = "dark"
    else:
        name = opts.theme
    return json.loads((WEB / "themes" / f"{name}.ctheme").read_text())


def headers_for(opts: EmbedOptions | None) -> dict[str, str]:
    origins = " ".join(opts.allowed_origins) if opts and opts.allowed_origins else "'none'"
    h = {
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
            f"base-uri 'none'; form-action 'none'; frame-ancestors {origins}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
    }
    if not (opts and opts.allowed_origins):
        h["X-Frame-Options"] = "DENY"
    return h


class RateLimit:
    """At most `per_minute` requests per client address (in memory, per process)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self.hits) > 10000:  # don't let a scan grow memory forever
                self.hits.clear()
            return True


def create_embed_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    prices = PriceService(make_provider(settings), max(settings.price_cache_seconds, 120))
    networks = parse_networks(settings.embed_allowed_networks)
    limiter = RateLimit(settings.embed_rate_per_minute)
    images: dict[str, tuple[float, bytes]] = {}

    @asynccontextmanager
    async def lifespan(_app):
        # The main service owns migrations; refuse to run on a database it hasn't upgraded.
        current = migrate.current_revision(engine)
        if current != migrate.head_revision():
            raise RuntimeError(
                f"database is at {current}; start the main service first so it can migrate"
            )
        yield
        engine.dispose()

    app = FastAPI(
        title="Crypto Helper embeds",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.prices = prices

    def base_url(request: Request) -> str:
        return settings.embed_public_url.rstrip("/") or str(request.base_url).rstrip("/")

    def plain(text: str, status: int, opts=None) -> Response:
        return PlainTextResponse(text, status_code=status, headers=headers_for(opts))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.client.host if request.client else None
        if not client_allowed(host, networks):
            return plain("Forbidden", 403)
        if not limiter.allow(host or "?"):
            return plain("Too many requests", 429)
        if request.method not in ("GET", "HEAD"):
            return plain("Method not allowed", 405)
        return await call_next(request)

    def load(db, token: str):
        embed = db.scalar(select(Embed).where(Embed.token_hash == hash_token(token)))
        if embed is None:
            raise Unavailable
        return embed

    @app.get("/embed-assets/{name:path}")
    def assets(name: str):
        if name not in ASSETS:
            return plain(NOT_FOUND, 404)
        path, media = ASSETS[name]
        return FileResponse(
            path,
            media_type=media,
            headers={**headers_for(None), "Cache-Control": "public, max-age=86400"},
        )

    @app.get("/embed/{token}.css")
    def embed_css(token: str):
        with factory() as db:
            try:
                embed = load(db, token)
                view = build(db, embed, prices)
                opts = EmbedOptions(**embed.options)
                body = page.css(theme_for(db, opts, embed.owner_id), view)
            except Unavailable:
                return plain(NOT_FOUND, 404)
        return Response(
            body,
            media_type="text/css",
            headers={**headers_for(opts), "Cache-Control": "public, max-age=60"},
        )

    @app.get("/embed/{token}.png")
    def embed_png(token: str):
        with factory() as db:
            try:
                # Checked every time (a quick lookup): a link that was switched off, expired
                # or replaced stops at once, even while its picture is cached.
                embed = load(db, token)
                check_usable(db, embed)
                version = json.dumps(embed.options, sort_keys=True)
                cached = images.get(token)
                if (cached and cached[1] == version
                        and time.monotonic() - cached[0] < IMAGE_CACHE_SECONDS):  # fmt: skip
                    png, opts = cached[2]
                else:
                    view = build(db, embed, prices)
                    opts = EmbedOptions(**embed.options)
                    png = image.render(view, theme_for(db, opts, embed.owner_id))
                    images[token] = (time.monotonic(), version, (png, opts))
            except Unavailable:
                images.pop(token, None)
                return plain(NOT_FOUND, 404)
        return Response(
            png,
            media_type="image/png",
            headers={
                **headers_for(opts),
                "Cache-Control": f"public, max-age={IMAGE_CACHE_SECONDS}",
            },
        )

    @app.get("/embed/{token}")
    def embed_page(token: str, request: Request):
        with factory() as db:
            try:
                embed = load(db, token)
                view = build(db, embed, prices)
                opts = EmbedOptions(**embed.options)
            except Unavailable:
                return plain(NOT_FOUND, 404)
            html = page.render(view, token, base_url(request), opts.refresh_seconds)
            embed_id = embed.id
        with factory() as db:  # count the view (its own short write)
            db.connection(execution_options={IMMEDIATE: True})
            db.execute(
                update(Embed)
                .where(Embed.id == embed_id)
                .values(views=Embed.views + 1, last_viewed_at=utcnow())
            )
            db.commit()
        return HTMLResponse(
            html, headers={**headers_for(opts), "Cache-Control": "public, max-age=60"}
        )

    @app.api_route("/{rest:path}", methods=["GET", "HEAD"])
    def anything_else(rest: str):
        return plain(NOT_FOUND, 404)

    return app
