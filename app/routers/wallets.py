from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import colors, money, networks
from app import wallets as svc
from app.audit import write_audit
from app.db import begin_immediate, get_db
from app.deps import current_user, effective_permissions, require_permission
from app.models import User, Wallet

router = APIRouter(tags=["wallets"])
view = require_permission("wallets.view")
edit = require_permission("wallets.edit")

Kind = Literal["exchange", "onchain", "paper"]
Mode = Literal["auto", "custom"]
Scheme = Literal["analogous", "complementary", "triadic", "shade"]


def fail(e: svc.WalletError):
    return JSONResponse({"detail": e.message, **e.extra}, status_code=e.status)


class WalletIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    nickname: str | None = Field(default=None, max_length=200)
    kind: Kind
    provider: str | None = Field(default=None, max_length=200)
    network: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=256)
    notes: str = Field(default="", max_length=4000)
    color_primary: str | None = None
    color_secondary: str | None = None
    color_secondary_mode: Mode = "auto"
    color_scheme: Scheme = "analogous"
    tags: list[str] = Field(default_factory=list, max_length=100)


class WalletPatch(BaseModel):
    """Only the fields you send change. Send null to clear an optional field."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    nickname: str | None = Field(default=None, max_length=200)
    kind: Kind | None = None
    provider: str | None = Field(default=None, max_length=200)
    network: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=256)
    notes: str | None = Field(default=None, max_length=4000)
    color_primary: str | None = None
    color_secondary: str | None = None
    color_secondary_mode: Mode | None = None
    color_scheme: Scheme | None = None
    tags: list[str] | None = Field(default=None, max_length=100)
    archived: bool | None = None


class AmountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: object  # validated by app.money so a JSON number gets a helpful message


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wallet_ids: list[int] = Field(max_length=1000)


def _apply_colors(w: Wallet, data: dict) -> None:
    if "color_primary" in data:
        w.color_primary = (
            colors.normalize_hex(data["color_primary"]) if data["color_primary"] else None
        )
    if "color_secondary" in data:
        w.color_secondary = (
            colors.normalize_hex(data["color_secondary"]) if data["color_secondary"] else None
        )
        if w.color_secondary and "color_secondary_mode" not in data:
            w.color_secondary_mode = "custom"  # picking a color means you want it used
    if data.get("color_secondary_mode"):
        w.color_secondary_mode = data["color_secondary_mode"]
    if data.get("color_scheme"):
        w.color_scheme = data["color_scheme"]
    if w.color_secondary_mode == "custom" and not w.color_secondary:
        raise svc.WalletError(422, "Custom secondary color mode needs color_secondary.")


def _get_wallet(db: DbSession, wallet_id: int) -> Wallet:
    w = db.get(Wallet, wallet_id)
    if w is None:
        raise svc.WalletError(404, "Wallet not found.")
    return w


def _add_values(request, db, user: User, out: list[dict], fiat: str | None) -> None:
    """Add each wallet's value, only for people who may see prices (permission split)."""
    if "prices.view" not in effective_permissions(user) or not out:
        return
    from app.prices.catalog import FIATS, all_coins
    from app.prices.service import PricesUnavailable
    from app.prices.valuation import wallet_value

    fiat = (fiat or (user.preferences or {}).get("fiat") or "usd").lower()
    if fiat not in FIATS:
        raise HTTPException(status_code=422, detail=f"fiat must be one of {', '.join(FIATS)}")
    try:
        snap = request.app.state.prices.snapshot(db)
    except PricesUnavailable:
        for w in out:
            w.update(value=None, value_fiat=fiat, unpriced=[h["symbol"] for h in w["holdings"]])
        return
    coins = all_coins(db)
    for w in out:
        wallet = db.get(Wallet, w["id"])
        wv = wallet_value(db, wallet, snap, coins, fiat)
        w.update(
            value=wv["value"], value_fiat=fiat, unpriced=wv["unpriced"], prices_stale=snap.stale
        )
        for h in w["holdings"]:
            h["value"] = wv["_per_coin"].get(h["symbol"])


def _order_for(user: User) -> list[int]:
    return list((user.preferences or {}).get("wallet_order", []))


# ---- reference data ----------------------------------------------------------------------


@router.get("/api/meta/networks")
def meta_networks(_: User = Depends(view)):
    return {
        "networks": networks.KNOWN_NETWORKS,
        "coin_networks": {k: sorted(v) for k, v in networks.COIN_NETWORKS.items()},
        "kinds": list(svc.KINDS),
        "color_schemes": list(colors.SCHEMES),
        "max_tags": svc.MAX_TAGS,
        "simulated_label": svc.SIMULATED_LABEL,
    }


# ---- wallets -----------------------------------------------------------------------------


@router.get("/api/wallets")
def list_wallets(
    kind: Kind | None = None,
    tag: str | None = Query(default=None, max_length=64),
    network: str | None = Query(default=None, max_length=64),
    archived: Literal["false", "true", "all"] = "false",
    sort: Literal["custom", "name", "created", "value"] = "custom",
    fiat: str | None = Query(default=None, max_length=8),
    request: Request = None,
    user: User = Depends(view),
    db: DbSession = Depends(get_db),
):
    stmt = select(Wallet)
    if kind:
        stmt = stmt.where(Wallet.kind == kind)
    if network:
        stmt = stmt.where(Wallet.network == network.lower())
    if archived != "all":
        stmt = stmt.where(Wallet.archived.is_(archived == "true"))
    out = [svc.serialize(w, svc.holdings_of(db, w)) for w in db.scalars(stmt)]
    if tag:
        t = tag.strip().lower()
        out = [w for w in out if t in w["tags"] or t in w["system_tags"]]
    out.sort(key=lambda w: w["display_name"].lower())
    _add_values(request, db, user, out, fiat)
    if sort == "value":
        if not out or "value" not in out[0]:
            if out:
                raise HTTPException(status_code=403, detail="Sorting by value needs prices.view")
        else:
            out.sort(key=lambda w: Decimal(w["value"] or "0"), reverse=True)
    if sort == "created":
        out.sort(key=lambda w: w["created_at"])
    elif sort == "custom":
        rank = {wid: i for i, wid in enumerate(_order_for(user))}
        out.sort(key=lambda w: rank.get(w["id"], len(rank)))  # stable: unranked keep name order
    return out


@router.get("/api/wallets/{wallet_id}")
def get_wallet(wallet_id: int, _: User = Depends(view), db: DbSession = Depends(get_db)):
    try:
        w = _get_wallet(db, wallet_id)
    except svc.WalletError as e:
        return fail(e)
    return svc.serialize(w, svc.holdings_of(db, w))


@router.post("/api/wallets", status_code=201)
def create_wallet(
    body: WalletIn, request: Request, actor: User = Depends(edit), db: DbSession = Depends(get_db)
):
    try:
        svc.guard(
            name=body.name,
            nickname=body.nickname,
            provider=body.provider,
            address=body.address,
            notes=body.notes,
            tags=body.tags,
        )
        name = svc.clean_text(body.name, "name", 64, required=True)
        svc.unique_name(db, name)
        network = svc.check_kind_network(body.kind, body.network)
        address = svc.clean_text(body.address, "address", 128)
        svc.check_address(address, network)
        w = Wallet(
            name=name,
            nickname=svc.clean_text(body.nickname, "nickname", 64),
            kind=body.kind,
            provider=svc.clean_text(body.provider, "provider", 64),
            network=network,
            address=address,
            notes=(body.notes or "").strip(),
            tags=svc.clean_tags(body.tags),
        )
        _apply_colors(w, body.model_dump(exclude_unset=True))
    except svc.WalletError as e:
        return fail(e)
    except ValueError as e:
        return fail(svc.WalletError(422, str(e)))
    db.add(w)
    try:
        db.flush()
    except IntegrityError:  # lost a race with a same-named wallet
        db.rollback()
        return fail(svc.WalletError(409, f"A wallet named {w.name!r} already exists."))
    write_audit(
        db,
        request,
        "wallet.create",
        user=actor,
        detail=f"{w.name} (id {w.id}) kind={w.kind} network={w.network or '-'}",
    )
    db.commit()
    return svc.serialize(w, [])


@router.patch("/api/wallets/{wallet_id}")
def update_wallet(
    wallet_id: int,
    body: WalletPatch,
    request: Request,
    actor: User = Depends(edit),
    db: DbSession = Depends(get_db),
):
    data = body.model_dump(exclude_unset=True)
    try:
        svc.guard(
            **{
                k: v
                for k, v in data.items()
                if k in ("name", "nickname", "provider", "address", "notes", "tags")
                and v is not None
            }
        )
        w = _get_wallet(db, wallet_id)
        before = svc.serialize(w, [])
        if "name" in data:
            name = svc.clean_text(data["name"], "name", 64, required=True)
            svc.unique_name(db, name, exclude_id=w.id)
            w.name = name
        for field, limit in (("nickname", 64), ("provider", 64)):
            if field in data:
                setattr(w, field, svc.clean_text(data[field], field, limit))
        if "notes" in data:
            w.notes = (data["notes"] or "").strip()
        if "kind" in data or "network" in data:
            kind = data.get("kind") or w.kind
            network = svc.check_kind_network(
                kind, data["network"] if "network" in data else w.network
            )
            for h in svc.holdings_of(db, w):  # existing coins must be possible there
                problem = networks.coin_allowed_on(h.symbol, network)
                if problem:
                    raise svc.WalletError(
                        409, f"Can't change the network while it holds {h.symbol}. " + problem
                    )
            w.kind, w.network = kind, network
        if "address" in data:
            w.address = svc.clean_text(data["address"], "address", 128)
        if "address" in data or "network" in data:
            svc.check_address(w.address, w.network)
        if "tags" in data:
            w.tags = svc.clean_tags(data["tags"] or [])
        _apply_colors(w, data)
        if "archived" in data:
            w.archived = data["archived"]
    except svc.WalletError as e:
        db.rollback()
        return fail(e)
    except ValueError as e:
        db.rollback()
        return fail(svc.WalletError(422, str(e)))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return fail(svc.WalletError(409, "A wallet with that name already exists."))
    after = svc.serialize(w, [])
    changed = sorted(
        k
        for k in after
        if k not in ("updated_at", "system_tags", "holdings") and after[k] != before[k]
    )
    if changed:
        write_audit(
            db,
            request,
            "wallet.update",
            user=actor,
            detail=f"{w.name} (id {w.id}): {', '.join(changed)}"
            + (f" (archived={w.archived})" if "archived" in changed else ""),
        )
    db.commit()
    return svc.serialize(w, svc.holdings_of(db, w))


@router.delete("/api/wallets/{wallet_id}")
def delete_wallet(
    wallet_id: int,
    request: Request,
    move_to: int | None = None,
    force: bool = False,
    confirm_name: str | None = Query(default=None, max_length=200),
    actor: User = Depends(edit),
    db: DbSession = Depends(get_db),
):
    """Empty wallets go straight away. A wallet that still holds coins needs either
    ?move_to=<wallet id> (moves everything first, all or nothing) or
    ?force=true&confirm_name=<its exact name> (destroys the holdings)."""
    begin_immediate(db)
    try:
        w = _get_wallet(db, wallet_id)
        holdings = svc.holdings_of(db, w)
        held = [{"symbol": h.symbol, "amount": h.amount} for h in holdings]
        detail = f"{w.name} (id {w.id})"
        if holdings and move_to is not None:
            dst = _get_wallet(db, move_to)
            moved = svc.move_everything(db, w, dst, actor)
            detail += f": moved {len(moved)} holding(s) to {dst.name} first"
        elif holdings and force:
            if confirm_name != w.name:
                raise svc.WalletError(
                    409,
                    f"To delete {w.name} with its holdings, confirm_name must be exactly "
                    f"{w.name!r}.",
                    holdings=held,
                )
            detail += ": FORCED, destroyed " + ", ".join(
                f"{h['amount']} {h['symbol']}" for h in held
            )
        elif holdings:
            raise svc.WalletError(
                409,
                f"{w.name} still holds coins, so it wasn't deleted.",
                holdings=held,
                options={
                    "move_to": "Move everything to another wallet first: ?move_to=<wallet id>",
                    "force": "Delete it with its holdings: ?force=true&confirm_name=<exact name>."
                    " The holdings are gone for good; transfer history is kept.",
                    "archive": 'Or archive it instead: PATCH {"archived": true} hides it '
                    "and keeps everything.",
                },
            )
    except svc.WalletError as e:
        db.rollback()
        return fail(e)
    db.delete(w)
    write_audit(db, request, "wallet.delete", user=actor, detail=detail)
    db.commit()
    return Response(status_code=204)


# ---- holdings ----------------------------------------------------------------------------


@router.put("/api/wallets/{wallet_id}/holdings/{symbol}")
def put_holding(
    wallet_id: int,
    symbol: str,
    body: AmountIn,
    request: Request,
    actor: User = Depends(edit),
    db: DbSession = Depends(get_db),
):
    try:
        amount = money.parse_amount(body.amount)
        sym = svc.clean_symbol(symbol)
        begin_immediate(db)
        w = _get_wallet(db, wallet_id)
        old, new = svc.set_holding(db, w, sym, amount)
    except money.AmountError as e:
        return fail(svc.WalletError(422, str(e)))
    except svc.WalletError as e:
        db.rollback()
        return fail(e)
    if old != new:
        write_audit(
            db,
            request,
            "holding.change",
            user=actor,
            detail=f"{w.name} (id {w.id}) {sym}: {old} -> {new}",
        )
    db.commit()
    return {"wallet_id": w.id, "symbol": sym, "amount": new}


@router.get("/api/holdings/summary")
def holdings_summary(
    include_archived: bool = False, _: User = Depends(view), db: DbSession = Depends(get_db)
):
    return svc.summary(db, include_archived)


# ---- personal wallet order ---------------------------------------------------------------


@router.put("/api/me/wallet-order")
def set_wallet_order(
    body: OrderIn, user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    """Your own order for the wallet list. Only affects your view; no permission needed."""
    ids = list(dict.fromkeys(body.wallet_ids))
    known = set(db.scalars(select(Wallet.id).where(Wallet.id.in_(ids))))
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown wallet ids: {unknown}")
    user.preferences = {**(user.preferences or {}), "wallet_order": ids}
    db.commit()
    return {"wallet_order": ids}
