"""Values in fiat: amount x price, rounded to the currency's smallest unit."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import money
from app.models import Holding, Wallet
from app.prices.catalog import FIATS, Coin
from app.prices.service import Snapshot


def round_fiat(value: Decimal, fiat: str) -> str:
    exp = Decimal(1).scaleb(-FIATS[fiat])
    return format(value.quantize(exp, rounding=ROUND_HALF_UP), "f")


def price_of(snap: Snapshot, coins: dict[str, Coin], symbol: str, fiat: str):
    coin = coins.get(symbol)
    if coin is None:
        return None
    return snap.quotes.get(coin.coingecko_id, {}).get(fiat)


def value(amount: Decimal, quote, fiat: str) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = money.PRECISION
        return amount * quote.price


def wallet_value(db: DbSession, wallet: Wallet, snap: Snapshot, coins, fiat: str) -> dict:
    total, unpriced, per_coin = Decimal(0), [], {}
    for h in db.scalars(select(Holding).where(Holding.wallet_id == wallet.id)):
        q = price_of(snap, coins, h.symbol, fiat)
        if q is None:
            unpriced.append(h.symbol)
            per_coin[h.symbol] = None
        else:
            v = value(Decimal(h.amount), q, fiat)
            per_coin[h.symbol] = round_fiat(v, fiat)
            total += v
    return {
        "value": round_fiat(total, fiat),
        "unpriced": sorted(unpriced),
        "_raw": total,
        "_per_coin": per_coin,
    }


def portfolio(db: DbSession, snap: Snapshot, coins, fiat: str, include_archived: bool) -> dict:
    stmt = select(Wallet).order_by(Wallet.name)
    if not include_archived:
        stmt = stmt.where(Wallet.archived.is_(False))
    wallets = db.scalars(stmt).all()
    per_coin: dict[str, Decimal] = {}
    out_wallets = []
    grand = Decimal(0)
    unpriced: set[str] = set()
    for w in wallets:
        wv = wallet_value(db, w, snap, coins, fiat)
        grand += wv.pop("_raw")
        wv.pop("_per_coin")
        unpriced.update(wv["unpriced"])
        out_wallets.append({"id": w.id, "name": w.name, "display_name": w.nickname or w.name, **wv})
        for h in db.scalars(select(Holding).where(Holding.wallet_id == w.id)):
            per_coin[h.symbol] = money.add(per_coin.get(h.symbol, Decimal(0)), Decimal(h.amount))
    coin_rows = []
    for symbol, amount in sorted(per_coin.items()):
        q = price_of(snap, coins, symbol, fiat)
        coin = coins.get(symbol)
        coin_rows.append(
            {
                "symbol": symbol,
                "name": coin.name if coin else None,
                "amount": money.format_amount(amount),
                "price": money.format_amount(q.price) if q else None,
                "change_24h": str(q.change_24h) if q and q.change_24h is not None else None,
                "value": round_fiat(value(amount, q, fiat), fiat) if q else None,
            }
        )
    return {
        "fiat": fiat,
        "total": round_fiat(grand, fiat),
        "coins": coin_rows,
        "wallets": out_wallets,
        "unpriced": sorted(unpriced),
        "as_of": snap.as_of,
        "source": snap.source,
        "attribution": snap.attribution,
        "stale": snap.stale,
        "error": snap.error,
    }
