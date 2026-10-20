import asyncio
import os
import secrets
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, select

from app import migrate, notifications
from app.balance_history import BalanceHistoryJob
from app.config import Settings
from app.crypto import load_secret_box
from app.db import make_engine, make_session_factory
from app.deps import Restricted
from app.features import FeatureOff
from app.health import HealthWatcher
from app.models import User
from app.netaccess import client_allowed, parse_networks
from app.price_alerts import PriceAlertJob
from app.prices.background import HistoryJob
from app.prices.daily import DailyPriceJob
from app.prices.importer import PriceImport
from app.prices.providers import make_provider
from app.prices.service import PriceService
from app.routers import alerts as alerts_router
from app.routers import apps as apps_router
from app.routers import (
    audit_log,
    auth,
    embeds,
    me,
    prices,
    services,
    setup,
    shell,
    system,
    themes,
    transfers,
    users,
    wallets,
    web,
)
from app.routers import balance_history as balance_history_router
from app.routers import help as help_router
from app.routers import notifications as notifications_router
from app.routers import onboarding as onboarding_router
from app.routers import price_alerts as price_alerts_router
from app.routers import server as server_router
from app.routers import sync as sync_router
from app.routers import trades as trades_router
from app.routers import wallpapers as wallpapers_router
from app.selftest import SelfTest
from app.setup_token import clear_setup_token, write_setup_token
from app.smart_alerts import SmartAlertJob
from app.sync.engine import SyncJob

MAX_API_BODY = 2 * 1024 * 1024
UPLOADS = {"/api/wallpapers", "/api/themes/upload"}  # stream and limit their own size

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
        app.state.hub.bind(asyncio.get_running_loop())
        with session_factory() as db:
            wallpapers_router.sweep(settings.state_dir, db)  # files whose owner is gone
            notifications.sweep(db)  # older than 90 days
            db.commit()
        if has_users:
            clear_setup_token(settings)
        else:
            app.state.setup_token = secrets.token_urlsafe(24)
            write_setup_token(settings, app.state.setup_token)
            if sys.stdout.isatty() and not os.environ.get("INVOCATION_ID"):
                shown = app.state.setup_token  # someone is watching this terminal
            else:
                # Output that's kept (the systemd journal, a log file, a container's logs, a
                # pipe) never gets the token: point to where it can be read instead.
                shown = "run `sudo crypto-helper setup token` to see it"
            print(
                "\n=== FIRST LAUNCH ===\n"
                "No users exist yet. Use this one-time setup token to create the `super` user:\n"
                f"  {shown}\n"
                "====================\n",
                flush=True,
            )
        tasks = []
        if settings.price_background:
            tasks.append(asyncio.create_task(app.state.history_job.run_forever()))
            tasks.append(asyncio.create_task(app.state.price_alerts.run_forever()))
            tasks.append(asyncio.create_task(app.state.balance_job.run_forever()))
            tasks.append(asyncio.create_task(app.state.daily_prices.run_forever()))
            tasks.append(asyncio.create_task(app.state.smart_alerts.run_forever()))
        if settings.notify_background:
            tasks.append(asyncio.create_task(app.state.delivery.run_forever()))
            tasks.append(asyncio.create_task(app.state.health.run_forever()))
        if settings.sync_background:
            tasks.append(asyncio.create_task(app.state.sync_job.run_forever()))
        yield
        for task in tasks:
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
    app.state.balance_job = BalanceHistoryJob(app.state.prices, session_factory)
    app.state.daily_prices = DailyPriceJob(session_factory, settings.daily_prices_url)
    app.state.price_import = PriceImport(session_factory, settings.daily_prices_url)
    app.state.setup_token = None
    # Changes on every start: the browser uses it to tell the restarted server from the old one
    # (confirming a network change must come from the new one).
    app.state.boot_id = secrets.token_hex(8)
    app.state.selftest = SelfTest(settings.state_dir)
    app.state.terminal_tickets = {}  # one-time WebSocket tickets (app/routers/shell.py)
    app.state.wallpaper_lock = asyncio.Semaphore(1)  # one upload processed at a time
    app.state.hub = notifications.Hub()  # live notification streams
    app.state.delivery = notifications.DeliveryWorker(session_factory, app.state.secret_box)
    app.state.sync_job = SyncJob(app.state)  # syncs wallets from exchanges and addresses
    app.state.price_alerts = PriceAlertJob(app.state.prices, session_factory, app.state.hub)
    app.state.smart_alerts = SmartAlertJob(app.state.prices, session_factory, app.state.hub)
    app.state.health = HealthWatcher(settings, session_factory, app.state.prices,
                                     app.state.selftest, hub=app.state.hub)  # fmt: skip

    networks = parse_networks(settings.allowed_networks)

    def _too_big(request: Request) -> bool:
        """API bodies are small JSON, except the two uploads, which check their own (larger)
        limits while streaming. Refused before anything reads the body."""
        if request.url.path in UPLOADS:
            return False
        try:
            return int(request.headers.get("content-length") or 0) > MAX_API_BODY
        except ValueError:
            return True

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
        elif _too_big(request):
            response = JSONResponse({"detail": "That request is too big."}, status_code=413)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if request.url.path.startswith("/api"):
            # API answers can carry one-time secrets (2FA setup, recovery codes): never cache,
            # unless an endpoint chose its own caching (immutable wallpaper files).
            if "cache-control" not in response.headers:
                response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Restricted)
    async def restricted(request: Request, exc: Restricted):
        return JSONResponse({"detail": str(exc), "restricted": exc.need}, status_code=403)

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
    app.include_router(services.router)
    app.include_router(shell.router)
    app.include_router(wallpapers_router.router)
    app.include_router(notifications_router.router)
    app.include_router(price_alerts_router.router)
    app.include_router(help_router.router)
    app.include_router(sync_router.router)
    app.include_router(trades_router.router)
    app.include_router(balance_history_router.router)
    app.include_router(server_router.router)
    app.include_router(onboarding_router.router)
    app.include_router(alerts_router.router)
    app.include_router(web.router)
    web.mount(app)
    return app
