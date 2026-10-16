import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select

from app import migrate
from app.config import Settings
from app.crypto import load_secret_box
from app.db import make_engine, make_session_factory
from app.features import FeatureOff
from app.models import User
from app.netaccess import client_allowed, parse_networks
from app.prices.background import HistoryJob
from app.prices.providers import make_provider
from app.prices.service import PriceService
from app.routers import apps as apps_router
from app.routers import (
    audit_log,
    auth,
    embeds,
    me,
    prices,
    setup,
    system,
    themes,
    transfers,
    users,
    wallets,
    web,
)
from app.setup_token import clear_setup_token, write_setup_token

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        migrate.upgrade(engine)
        with session_factory() as db:
            has_users = (db.scalar(select(func.count()).select_from(User)) or 0) > 0
        if has_users:
            clear_setup_token(settings)
        else:
            app.state.setup_token = secrets.token_urlsafe(24)
            write_setup_token(settings, app.state.setup_token)
            if os.environ.get("INVOCATION_ID"):
                # Under systemd the console is the journal, which keeps lines for weeks and
                # is readable by admins: point to the token instead of printing it.
                shown = "run `sudo crypto-helper setup token` to see it"
            else:
                shown = app.state.setup_token
            print(
                "\n=== FIRST LAUNCH ===\n"
                "No users exist yet. Use this one-time setup token to create the `super` user:\n"
                f"  {shown}\n"
                "====================\n",
                flush=True,
            )
        task = None
        if settings.price_background:
            task = asyncio.create_task(app.state.history_job.run_forever())
        yield
        if task:
            task.cancel()
        engine.dispose()

    app = FastAPI(
        title="Crypto Helper", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.secret_box = load_secret_box(settings)
    app.state.prices = PriceService(make_provider(settings), settings.price_cache_seconds)
    app.state.history_job = HistoryJob(app.state.prices, session_factory)
    app.state.setup_token = None

    networks = parse_networks(settings.allowed_networks)

    @app.middleware("http")
    async def csrf_and_headers(request: Request, call_next):
        # Outermost check: only allowed client networks get anything at all.
        if not client_allowed(request.client.host if request.client else None, networks):
            return PlainTextResponse("Forbidden", status_code=403, headers=dict(SECURITY_HEADERS))
        # CSRF guard: browsers can't add a custom header cross-site without CORS (which we
        # don't enable), so requiring it blocks forged state-changing requests.
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api")
            and request.headers.get("x-requested-with") != "fetch"
        ):
            response = JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.url.path.startswith("/api"):
            # API answers can carry one-time secrets (2FA setup, recovery codes): never cache.
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(FeatureOff)
    async def feature_off(request: Request, exc: FeatureOff):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # FastAPI's default answer echoes the rejected input back. That input can be a
        # password or a pasted seed phrase, so send only where and why it failed.
        errors = [
            {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=422)

    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(audit_log.router)
    app.include_router(wallets.router)
    app.include_router(transfers.router)
    app.include_router(prices.router)
    app.include_router(me.router)
    app.include_router(themes.router)
    app.include_router(system.router)
    app.include_router(embeds.router)
    app.include_router(apps_router.router)
    app.include_router(web.router)
    web.mount(app)
    return app
