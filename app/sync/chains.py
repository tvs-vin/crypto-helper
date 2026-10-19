"""Balances on a blockchain from public addresses (phase 2, milestone 11c). Watch-only: nothing
here can spend, and nothing here ever accepts a private key.

- Bitcoin: one or more addresses, or an extended public key (xpub/ypub/zpub) from a hardware
  or phone wallet. The wallet's receive and change addresses are derived (`embit`, checked
  against the BIP44/49/84/86 test vectors) until 20 unused ones in a row; balances come from an
  Esplora server (mempool.space by default, or your own).
- Ethereum, Base, Arbitrum, Optimism, Polygon: one or more addresses; the native coin plus the
  fixed token list in `app/networks.py`, read over JSON-RPC (public endpoints by default).

Every request has a time limit and goes through `app/sync/http.py`; callers hold no database
session meanwhile.
"""

import ipaddress
import json
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from app import networks as nets
from app.models import AppSetting
from app.sync import SourceError, http

SETTINGS_KEY = "chains"
DEFAULT_ESPLORA = "https://mempool.space/api"
DEFAULT_RPC = {
    "ethereum": "https://ethereum-rpc.publicnode.com",
    "base": "https://base-rpc.publicnode.com",
    "arbitrum": "https://arbitrum-one-rpc.publicnode.com",
    "optimism": "https://optimism-rpc.publicnode.com",
    "polygon": "https://polygon-bor-rpc.publicnode.com",
}
GAP_LIMIT = 20
MAX_DERIVED = 1000  # per chain (receive / change) and address type
MAX_ADDRESSES = 50
PUBLIC_PAUSE = 0.1  # seconds between calls to a shared public server
SCRIPTS = {
    "wpkh": "Native SegWit (bc1q…)",
    "tr": "Taproot (bc1p…)",
    "sh-wpkh": "Nested SegWit (3…)",
    "pkh": "Legacy (1…)",
}
XPUB_PREFIXES = {"xpub": None, "ypub": "sh-wpkh", "zpub": "wpkh"}
PRIVATE_PREFIXES = ("xprv", "yprv", "zprv", "tprv", "uprv", "vprv", "Yprv", "Zprv")


def _url(v: str) -> str:
    """https anywhere; plain http only to this machine or a private network (your own node)."""
    v = v.strip().rstrip("/")
    u = urllib.parse.urlsplit(v)
    if u.scheme == "https" and u.hostname:
        return v
    if u.scheme == "http" and u.hostname:
        try:
            ip = ipaddress.ip_address(u.hostname)
        except ValueError:
            ip = None
        if u.hostname == "localhost" or (ip and (ip.is_private or ip.is_loopback)):
            return v
    raise ValueError("Use an https:// address (plain http only for a server on your own network)")


class ChainSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    esplora_url: str = Field(default=DEFAULT_ESPLORA, max_length=200)
    rpc: dict[str, str] = Field(default_factory=dict)  # network -> your own endpoint

    @field_validator("esplora_url")
    @classmethod
    def _esplora(cls, v):
        return _url(v)

    @field_validator("rpc")
    @classmethod
    def _rpc(cls, v):
        unknown = set(v) - set(DEFAULT_RPC)
        if unknown:
            raise ValueError(f"Unknown networks: {', '.join(sorted(unknown))}")
        return {k: _url(u) for k, u in v.items() if u.strip()}

    def rpc_for(self, network: str) -> str:
        return self.rpc.get(network) or DEFAULT_RPC[network]


def load_settings(db: DbSession) -> ChainSettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    return ChainSettings(**row.value) if row else ChainSettings()


def save_settings(db: DbSession, s: ChainSettings, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=s.model_dump(), updated_by=actor))
    else:
        row.value, row.updated_by = s.model_dump(), actor


# ---- what to watch ---------------------------------------------------------------------------


@dataclass
class Watch:
    addresses: list[str] = field(default_factory=list)
    xpub: str | None = None
    script: str = "auto"

    def dump(self) -> str:
        return json.dumps({"addresses": self.addresses, "xpub": self.xpub, "script": self.script})

    @classmethod
    def load(cls, text: str) -> "Watch":
        d = json.loads(text)
        return cls(d.get("addresses") or [], d.get("xpub"), d.get("script") or "auto")

    def masked(self) -> str:
        if self.xpub:
            return f"{self.xpub[:4]}…{self.xpub[-4:]}"
        first = self.addresses[0]
        more = f" and {len(self.addresses) - 1} more" if len(self.addresses) > 1 else ""
        return f"{first[:6]}…{first[-4:]}{more}"


PRIVATE_KEY_WARNING = (
    "That's an extended PRIVATE key: it can spend everything in the wallet. Never paste it "
    "anywhere. If it was real, move the funds to a new wallet. Export the extended PUBLIC key "
    "instead (it starts with xpub, ypub or zpub)."
)


def check_xpub(text: str) -> str:
    """An extended public key from a wallet, or a plain explanation of why not."""
    key = text.strip()
    if key.startswith(PRIVATE_PREFIXES):
        raise ValueError(PRIVATE_KEY_WARNING)
    if key[:4] in ("tpub", "upub", "vpub"):
        raise ValueError("That's a testnet key; only real Bitcoin is supported")
    if key[:4] not in XPUB_PREFIXES:
        raise ValueError("An extended public key starts with xpub, ypub or zpub")
    from embit import bip32

    try:
        bip32.HDKey.from_string(key)
    except Exception:
        raise ValueError(
            "That isn't a valid extended public key (check it was copied whole)"
        ) from None
    return key


def check_watch(network: str, addresses: list[str], xpub: str | None, script: str) -> Watch:
    """Validate what to watch for a wallet on `network`. Raises ValueError with the reason."""
    if network not in nets.SYNCABLE:
        raise ValueError(f"Syncing {nets.network_name(network)} wallets isn't supported yet")
    if script != "auto" and script not in SCRIPTS:
        raise ValueError("Unknown address type")
    if xpub:
        if network != "bitcoin":
            raise ValueError("Extended public keys are for Bitcoin wallets")
        return Watch([], check_xpub(xpub), script)
    clean = list(dict.fromkeys(a.strip() for a in addresses if a.strip()))
    if not clean:
        raise ValueError("Give at least one address (or, for Bitcoin, an xpub)")
    if len(clean) > MAX_ADDRESSES:
        raise ValueError(f"At most {MAX_ADDRESSES} addresses")
    for a in clean:
        try:
            nets.check_address(a, network)
        except nets.NetworkError as e:
            raise ValueError(str(e)) from None
    return Watch(clean, None, script)


# ---- reading ---------------------------------------------------------------------------------


@dataclass
class Read:
    balances: dict[str, Decimal]
    info: dict


def read(network: str, watch: Watch, s: ChainSettings) -> Read:
    if network == "bitcoin":
        return Bitcoin(s.esplora_url).read(watch)
    if network in DEFAULT_RPC:
        return Evm(network, s.rpc_for(network)).read(watch)
    raise SourceError(f"Syncing {nets.network_name(network)} isn't supported", final=True)


SATS = Decimal(100_000_000)


class Bitcoin:
    name = "The Bitcoin data server"

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.pause = PUBLIC_PAUSE if self.base == DEFAULT_ESPLORA else 0

    def address(self, addr: str) -> tuple[int, int]:
        """(balance in satoshis including unconfirmed, number of transactions)."""
        if self.pause:
            time.sleep(self.pause)
        d = http.call(
            self.name, "GET", f"{self.base}/address/{urllib.parse.quote(addr)}", final_on=()
        )
        try:
            chain, pool = d["chain_stats"], d["mempool_stats"]
            sats = (
                chain["funded_txo_sum"]
                - chain["spent_txo_sum"]
                + pool["funded_txo_sum"]
                - pool["spent_txo_sum"]
            )
            return int(sats), int(chain["tx_count"]) + int(pool["tx_count"])
        except (KeyError, TypeError, ValueError):
            raise SourceError(f"{self.name} sent an answer the app doesn't understand") from None

    def read(self, watch: Watch) -> Read:
        if watch.xpub:
            return self._xpub(watch)
        total = sum(self.address(a)[0] for a in watch.addresses)
        return Read({"BTC": Decimal(total) / SATS}, {"addresses": len(watch.addresses)})

    def _scan(self, key: str, script: str) -> tuple[int, int]:
        """Walk receive and change addresses until GAP_LIMIT unused in a row."""
        from embit.descriptor import Descriptor

        sats = used = 0
        for branch in (0, 1):
            text = f"{script.replace('-', '(')}({key}/{branch}/*)" + (")" if "-" in script else "")
            desc = Descriptor.from_string(text)
            gap = 0
            for i in range(MAX_DERIVED):
                addr = desc.derive(i).script_pubkey().address()
                balance, txs = self.address(addr)
                if txs:
                    sats, used, gap = sats + balance, used + 1, 0
                else:
                    gap += 1
                    if gap >= GAP_LIMIT:
                        break
            else:
                raise SourceError(f"More than {MAX_DERIVED} addresses in use: not supported")
        return sats, used

    def _xpub(self, watch: Watch) -> Read:
        prefix = watch.xpub[:4]
        if watch.script != "auto":
            kinds = [watch.script]
        elif XPUB_PREFIXES[prefix]:
            kinds = [XPUB_PREFIXES[prefix]]
        else:  # a plain xpub can be any type: look at each, keep what's been used
            kinds = list(SCRIPTS)
        sats, used, found = 0, 0, []
        for kind in kinds:
            s, u = self._scan(watch.xpub, kind)
            if u:
                sats, used, found = sats + s, used + u, [*found, kind]
        return Read(
            {"BTC": Decimal(sats) / SATS},
            {"used_addresses": used, "types": [SCRIPTS[k] for k in found]},
        )


class Evm:
    def __init__(self, network: str, url: str):
        self.network, self.url = network, url
        self.name = f"The {nets.network_name(network)} data server"

    def _batch(self, calls: list[tuple[str, list]]) -> list:
        body = json.dumps(
            [
                {"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                for i, (m, p) in enumerate(calls)
            ]
        ).encode()
        out = http.call(
            self.name,
            "POST",
            self.url,
            body=body,
            headers={"Content-Type": "application/json"},
            final_on=(),
        )
        if not isinstance(out, list):
            raise SourceError(f"{self.name} didn't answer the batch (try your own endpoint)")
        by_id = {r.get("id"): r for r in out if isinstance(r, dict)}
        results = []
        for i in range(len(calls)):
            r = by_id.get(i) or {}
            if "error" in r or "result" not in r:
                msg = (r.get("error") or {}).get("message", "no answer")
                raise SourceError(f"{self.name} said: {str(msg)[:120]}")
            results.append(r["result"])
        return results

    def read(self, watch: Watch) -> Read:
        native, native_dec = nets.NATIVE[self.network]
        tokens = nets.TOKENS.get(self.network, ())
        calls, plan = [], []
        for a in watch.addresses:
            calls.append(("eth_getBalance", [a.lower(), "latest"]))
            plan.append((native, native_dec))
            data = "0x70a08231" + a.lower()[2:].rjust(64, "0")  # balanceOf(address)
            for t in tokens:
                calls.append(("eth_call", [{"to": t.contract, "data": data}, "latest"]))
                plan.append((t.symbol, t.decimals))
        balances: dict[str, Decimal] = {}
        for (symbol, decimals), raw in zip(plan, self._batch(calls), strict=True):
            try:
                units = int(raw, 16) if raw not in ("0x", "", None) else 0
            except (TypeError, ValueError):
                raise SourceError(f"{self.name} sent a number the app doesn't understand") from None
            if units:
                balances[symbol] = balances.get(symbol, Decimal(0)) + Decimal(units).scaleb(
                    -decimals
                )
        return Read(balances, {"addresses": len(watch.addresses)})
