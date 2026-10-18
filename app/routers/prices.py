import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import money
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import effective_permissions, require_app, require_permission
from app.models import CustomCoin, User
from app.prices import history
from app.prices.catalog import FIATS, MAX_CUSTOM_COINS, all_coins
from app.prices.providers import ProviderError
from app.prices.service import PricesUnavailable
from app.prices.valuation import portfolio
from app.timeutil import utcnow

router = APIRouter(tags=["prices"])
view = require_permission("prices.view")
manage = require_permission("prices.manage")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,10}$")
COINGECKO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


def _fiat(value: str) -> str:
    fiat = value.lower()
    if fiat not in FIATS:
        raise ValueError(f"fiat must be one of {', '.join(FIATS)}")
    return fiat


def _bad(msg: str, status: int = 422, **extra):
    return JSONResponse({"detail": msg, **extra}, status_code=status)


def _unavailable(e: PricesUnavailable):
    return _bad(f"Prices aren't available right now: {e}", 503)


def _meta(snap) -> dict:
    return {
        "as_of": snap.as_of,
        "source": snap.source,
        "attribution": snap.attribution,
        "stale": snap.stale,
        "error": snap.error,
    }


@router.get("/api/prices", dependencies=[Depends(require_app("overview"))])
def get_prices(
    request: Request,
    symbols: str | None = Query(default=None, max_length=1000),
    fiat: str = "usd",
    _: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    """Current prices from the shared snapshot. Without ?symbols=, every supported coin."""
    try:
        fiat = _fiat(fiat)
    except ValueError as e:
        return _bad(str(e))
    coins = all_coins(db)
    wanted = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else sorted(coins)
    )
    if len(wanted) > 200 or any(not SYMBOL_RE.match(s) for s in wanted):
        return _bad("symbols is a comma-separated list of up to 200 symbols like BTC,ETH")
    try:
        snap = request.app.state.prices.snapshot(db)
    except PricesUnavailable as e:
        return _unavailable(e)
    rows, unpriced = [], []
    for s in dict.fromkeys(wanted):
        coin = coins.get(s)
        q = snap.quotes.get(coin.coingecko_id, {}).get(fiat) if coin else None
        if q is None:
            unpriced.append(s)
            continue
        rows.append(
            {
                "symbol": s,
                "name": coin.name,
                "price": money.format_amount(q.price),
                "change_24h": None if q.change_24h is None else str(q.change_24h),
            }
        )
    return {"fiat": fiat, "prices": rows, "unpriced": unpriced, **_meta(snap)}


@router.get("/api/prices/supported")
def supported(_: User = Depends(view), db: DbSession = Depends(get_db)):
    return {
        "coins": [
            {
                "symbol": c.symbol,
                "name": c.name,
                "coingecko_id": c.coingecko_id,
                "builtin": c.builtin,
            }
            for c in all_coins(db).values()
        ],
        "fiats": list(FIATS),
    }


@router.get("/api/portfolio", dependencies=[Depends(require_app("overview", "wallets"))])
def get_portfolio(
    request: Request,
    fiat: str | None = None,
    include_archived: bool = False,
    user: User = Depends(require_permission("wallets.view")),
    db: DbSession = Depends(get_db),
):
    """Total value, per coin and per wallet. Needs wallets.view and prices.view."""
    if "prices.view" not in effective_permissions(user):
        return _bad("Permission denied", 403)
    try:
        fiat = _fiat(fiat or (user.preferences or {}).get("fiat", "usd"))
        snap = request.app.state.prices.snapshot(db)
    except ValueError as e:
        return _bad(str(e))
    except PricesUnavailable as e:
        return _unavailable(e)
    return portfolio(db, snap, all_coins(db), fiat, include_archived)


# ---- history -----------------------------------------------------------------------------


@router.get("/api/prices/history", dependencies=[Depends(require_app("overview"))])
def price_history(
    symbol: str,
    fiat: str = "usd",
    hours: int = Query(default=24, ge=1, le=24 * 3650),
    _: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    try:
        fiat = _fiat(fiat)
    except ValueError as e:
        return _bad(str(e))
    coin = all_coins(db).get(symbol.strip().upper())
    if coin is None:
        return _bad(f"{symbol} isn't a supported coin", 404)
    rows = history.query(db, coin.coingecko_id, fiat, utcnow() - timedelta(hours=hours))
    return {"symbol": coin.symbol, "fiat": fiat, "rows": rows}


@router.get("/api/prices/history/settings")
def get_history_settings(_: User = Depends(view), db: DbSession = Depends(get_db)):
    return {
        "settings": history.load_settings(db).model_dump(),
        "stats": history.stats(db),
        "coarse_choices": list(history.COARSE_CHOICES),
    }


@router.put("/api/prices/history/settings")
def put_history_settings(
    body: dict, request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    try:
        new = history.HistorySettings(**body)
    except (ValidationError, TypeError) as e:
        msgs = (
            [err["msg"].removeprefix("Value error, ") for err in e.errors()]
            if isinstance(e, ValidationError)
            else [str(e)]
        )
        return _bad("; ".join(msgs))
    old = history.load_settings(db).model_dump()
    history.save_settings(db, new, actor.username)
    changed = {k: f"{old[k]} -> {v}" for k, v in new.model_dump().items() if old[k] != v}
    if changed:
        write_audit(
            db,
            request,
            "prices.history_settings",
            user=actor,
            detail="; ".join(f"{k}: {v}" for k, v in changed.items()),
        )
    db.commit()
    return {"settings": new.model_dump()}


# ---- custom coins ------------------------------------------------------------------------


class CoinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coingecko_id: str = Field(max_length=128)
    symbol: str | None = Field(default=None, max_length=16)
    confirm: bool = False


@router.post("/api/coins", status_code=201)
def add_coin(
    body: CoinIn, request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    """Add a coin by its CoinGecko id (the part after coingecko.com/en/coins/)."""
    cid = body.coingecko_id.strip().lower()
    if not COINGECKO_ID_RE.match(cid):
        return _bad(
            "coingecko_id looks like 'pepe' or 'render-token': lowercase letters, "
            "digits and dashes. Copy it from the coin's page address on coingecko.com."
        )
    coins = all_coins(db)
    if any(c.coingecko_id == cid for c in coins.values()):
        return _bad(f"{cid} is already added.", 409)
    if (db.scalar(select(func.count()).select_from(CustomCoin)) or 0) >= MAX_CUSTOM_COINS:
        return _bad(f"At most {MAX_CUSTOM_COINS} extra coins.", 409)
    provider = request.app.state.prices.real  # verify coins against the real source
    db.commit()  # don't hold the write lock while CoinGecko answers (up to 10 s)
    try:
        listing = provider.coin_list()
    except ProviderError as e:
        return _bad(f"Couldn't check the coin with CoinGecko: {e}", 503)
    begin_immediate(db)
    coins = all_coins(db)  # again: someone may have added coins meanwhile
    if any(c.coingecko_id == cid for c in coins.values()):
        return _bad(f"{cid} is already added.", 409)
    if (db.scalar(select(func.count()).select_from(CustomCoin)) or 0) >= MAX_CUSTOM_COINS:
        return _bad(f"At most {MAX_CUSTOM_COINS} extra coins.", 409)
    info = next((c for c in listing if c.coingecko_id == cid), None)
    if info is None:
        return _bad(
            f"CoinGecko has no coin with the id {cid!r}. Check the address of its "
            "page on coingecko.com.",
            404,
        )
    symbol = (body.symbol or info.symbol).strip().upper()
    if not SYMBOL_RE.match(symbol):
        return _bad(
            f"CoinGecko's symbol {info.symbol!r} doesn't fit (2-10 letters or digits); "
            'choose one with "symbol".'
        )
    if symbol in coins:
        owner = coins[symbol]
        return _bad(
            f"{symbol} is already used by {owner.name}"
            + (" (built in, can't be replaced)" if owner.builtin else "")
            + '. Pick another symbol with "symbol".',
            409,
        )
    lookalikes = [
        {"coingecko_id": c.coingecko_id, "name": c.name}
        for c in listing
        if c.symbol.upper() == symbol and c.coingecko_id != cid
    ]
    if lookalikes and not body.confirm:
        return _bad(
            f"{len(lookalikes)} other coin(s) also use the symbol {symbol}. Scam tokens often "
            f"copy a popular symbol. Make sure {info.name} (coingecko.com/en/coins/{cid}) is "
            'the one you mean, then send again with "confirm": true.',
            409,
            coin={"coingecko_id": cid, "symbol": symbol, "name": info.name},
            lookalikes=lookalikes[:20],
            lookalike_count=len(lookalikes),
        )
    db.add(
        CustomCoin(symbol=symbol, coingecko_id=cid, name=info.name[:128], created_by=actor.username)
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return _bad(f"{symbol} or {cid} was just added by someone else.", 409)
    write_audit(
        db,
        request,
        "coin.add",
        user=actor,
        detail=f"{symbol} = {cid} ({info.name})"
        + (f"; confirmed despite {len(lookalikes)} look-alike(s)" if lookalikes else ""),
    )
    db.commit()
    request.app.state.prices.invalidate()
    return {
        "symbol": symbol,
        "coingecko_id": cid,
        "name": info.name,
        "builtin": False,
        "lookalike_count": len(lookalikes),
    }


@router.delete("/api/coins/{symbol}", status_code=204)
def remove_coin(
    symbol: str, request: Request, actor: User = Depends(manage), db: DbSession = Depends(get_db)
):
    symbol = symbol.upper()
    coin = db.scalar(select(CustomCoin).where(CustomCoin.symbol == symbol))
    if coin is None:
        builtin = symbol in all_coins(db)
        return _bad(
            f"{symbol} is built in and can't be removed."
            if builtin
            else f"No extra coin {symbol}.",
            409 if builtin else 404,
        )
    db.execute(delete(CustomCoin).where(CustomCoin.id == coin.id))
    write_audit(db, request, "coin.remove", user=actor, detail=f"{symbol} = {coin.coingecko_id}")
    db.commit()
    request.app.state.prices.invalidate()
    return JSONResponse(None, status_code=204)
