"""Build exactly what an embed may show, and nothing more.

Every value that leaves here was switched on in the embed's options, and the embed's owner
must still be active and still allowed to see it (a deactivated owner or a lost permission
turns the embed off).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import money
from app.deps import effective_permissions
from app.embeds.options import EmbedOptions
from app.models import Embed, Holding, User, Wallet
from app.prices.catalog import all_coins
from app.prices.service import PricesUnavailable
from app.prices.valuation import price_of, round_fiat, value
from app.timeutil import utcnow


class Unavailable(Exception):
    """The embed doesn't exist, is off, expired, or its owner can't show it any more."""


@dataclass
class Row:
    label: str
    sub: str = ""
    amount: str | None = None
    value: str | None = None
    percent: str | None = None
    price: str | None = None
    change: str | None = None
    color: str | None = None
    tags: list[str] = field(default_factory=list)
    children: list["Row"] = field(default_factory=list)


@dataclass
class View:
    kind: str
    title: str | None
    rows: list[Row]
    fiat: str
    total: str | None = None
    updated: str | None = None
    source: str | None = None
    attribution: str | None = None
    stale: bool = False
    summary: str = ""


def check_usable(db: DbSession, embed: Embed | None) -> tuple[Embed, User, EmbedOptions]:
    if embed is None or not embed.enabled:
        raise Unavailable
    if embed.expires_at is not None and embed.expires_at <= utcnow():
        raise Unavailable
    owner = db.get(User, embed.owner_id)
    if owner is None or not owner.is_active:
        raise Unavailable
    perms = effective_permissions(owner)
    needs = {"embeds.create"} | ({"wallets.view"} if embed.kind != "prices" else set())
    if not needs <= perms:
        raise Unavailable
    opts = EmbedOptions(**(embed.options or {}))
    if "prices.view" not in perms:  # can't show anything that needs prices
        opts.items.update(prices=False, change_24h=False, values=False, percent=False)
    return embed, owner, opts


def _pct(part: Decimal, whole: Decimal) -> str | None:
    if whole <= 0:
        return None
    return f"{(part * 100 / whole).quantize(Decimal('0.1'))}"


def build(db: DbSession, embed: Embed, prices) -> View:
    embed, owner, o = check_usable(db, embed)
    snap = None
    if any(o.on(k) for k in ("prices", "change_24h", "values", "percent")):
        try:
            snap = prices.snapshot(db)
        except PricesUnavailable:
            snap = None
    coins = all_coins(db)
    fiat = o.fiat

    def quote(symbol):
        return price_of(snap, coins, symbol, fiat) if snap else None

    title = (o.heading or embed.name) if o.on("title") else None
    rows: list[Row] = []
    total = Decimal(0)

    if embed.kind == "prices":
        symbols = o.symbols or sorted(coins)
        for s in symbols:
            q = quote(s)
            rows.append(
                Row(
                    label=s if o.on("coins") else "•",
                    sub=coins[s].name if s in coins and o.on("coins") else "",
                    price=money.format_amount(q.price) if q and o.on("prices") else None,
                    change=str(q.change_24h)
                    if q and q.change_24h is not None and o.on("change_24h")
                    else None,
                )
            )
    else:
        stmt = select(Wallet).where(Wallet.archived.is_(False)).order_by(Wallet.name)
        if o.wallet_ids:
            stmt = stmt.where(Wallet.id.in_(o.wallet_ids))
        wallets = db.scalars(stmt).all()
        per_coin_amount: dict[str, Decimal] = {}
        per_coin_value: dict[str, Decimal] = {}
        wallet_rows = []
        for w in wallets:
            holdings = db.scalars(select(Holding).where(Holding.wallet_id == w.id)).all()
            if o.symbols:
                holdings = [h for h in holdings if h.symbol in o.symbols]
            w_total = Decimal(0)
            children = []
            for h in holdings:
                amt = Decimal(h.amount)
                q = quote(h.symbol)
                v = value(amt, q, fiat) if q else None
                per_coin_amount[h.symbol] = money.add(
                    per_coin_amount.get(h.symbol, Decimal(0)), amt
                )
                if v is not None:
                    per_coin_value[h.symbol] = per_coin_value.get(h.symbol, Decimal(0)) + v
                    w_total += v
                children.append((h.symbol, amt, v, q))
            total += w_total
            wallet_rows.append((w, w_total, children))
        if embed.kind == "portfolio":
            for s in sorted(
                per_coin_amount, key=lambda s: per_coin_value.get(s, Decimal(0)), reverse=True
            ):
                q = quote(s)
                v = per_coin_value.get(s)
                rows.append(
                    Row(
                        label=s if o.on("coins") else "•",
                        sub=coins[s].name if s in coins and o.on("coins") else "",
                        amount=money.format_amount(per_coin_amount[s]) if o.on("amounts") else None,
                        value=round_fiat(v, fiat) if v is not None and o.on("values") else None,
                        percent=_pct(v, total) if v is not None and o.on("percent") else None,
                        price=money.format_amount(q.price) if q and o.on("prices") else None,
                        change=str(q.change_24h)
                        if q and q.change_24h is not None and o.on("change_24h")
                        else None,
                    )
                )
        else:  # wallets
            from app import colors as palette

            for w, w_total, children in wallet_rows:
                label = (w.nickname or w.name) if o.on("wallet_names") else "Wallet"
                sub = ""
                if o.on("network"):
                    sub = " · ".join(x for x in (w.kind, w.network) if x)
                rows.append(
                    Row(
                        label=label,
                        sub=sub,
                        value=round_fiat(w_total, fiat) if o.on("values") else None,
                        percent=_pct(w_total, total) if o.on("percent") else None,
                        color=palette.resolve(
                            w.name,
                            w.color_primary,
                            w.color_secondary,
                            w.color_secondary_mode,
                            w.color_scheme,
                        )["primary"]
                        if o.on("colors")
                        else None,
                        tags=list(w.tags or []) if o.on("tags") else [],
                        children=[
                            Row(
                                label=s if o.on("coins") else "•",
                                amount=money.format_amount(a) if o.on("amounts") else None,
                                value=round_fiat(v, fiat)
                                if v is not None and o.on("values")
                                else None,
                                percent=_pct(v, w_total)
                                if v is not None and o.on("percent")
                                else None,
                            )
                            for s, a, v, _q in children
                        ]
                        if o.on("coins")
                        else [],
                    )
                )

    view = View(
        kind=embed.kind,
        title=title,
        rows=rows,
        fiat=fiat,
        total=round_fiat(total, fiat) if o.on("values") and embed.kind != "prices" else None,
        updated=(snap.as_of.isoformat() if snap else utcnow().isoformat())
        if o.on("updated")
        else None,
        source=snap.source if snap else None,
        attribution=snap.attribution if snap else None,
        stale=bool(snap and snap.stale),
    )
    view.summary = describe(view)
    return view


def describe(v: View) -> str:
    """One line for link previews (Discord's description), from shown fields only."""
    bits = []
    for r in v.rows[:4]:
        piece = r.label
        if r.percent is not None:
            piece += f" {r.percent}%"
        elif r.price is not None:
            piece += f" {r.price}"
        bits.append(piece)
    text = ", ".join(bits)
    if v.total is not None:
        text = f"Total {v.total} {v.fiat.upper()}. " + text
    return text[:200]
