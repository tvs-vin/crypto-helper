import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app import migrate
from app.config import Settings
from app.crypto import load_secret_box
from app.db import make_engine, make_session_factory
from app.models import User
from app.routers import audit_log, auth, setup, transfers, users, wallets
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
        yield
        engine.dispose()

    app = FastAPI(
        title="Crypto Helper", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.secret_box = load_secret_box(settings)
    app.state.setup_token = None

    @app.middleware("http")
    async def csrf_and_headers(request: Request, call_next):
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
    return app
