"""What an embed shows. Every item has its own switch; amounts and values start off."""

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.netaccess import parse_hosts, probe_host
from app.secret_guard import find_secret

KINDS = ("portfolio", "wallets", "prices")

# key -> (default, label, sensitive). Sensitive items reveal how much you hold.
ITEMS: dict[str, tuple[bool, str, bool]] = {
    "title": (True, "Title", False),
    "wallet_names": (True, "Wallet names and nicknames", False),
    "network": (True, "Wallet kind and network", False),
    "tags": (True, "Wallet tags", False),
    "colors": (True, "Wallet colors", False),
    "coins": (True, "Which coins", False),
    "percent": (True, "Share of the total (%)", False),
    "prices": (True, "Prices", False),
    "change_24h": (True, "24h change", False),
    "updated": (True, "Last updated time", False),
    "amounts": (False, "Amounts held", True),
    "values": (False, "Values and totals", True),
}
ORIGIN_RE = re.compile(r"^https?://[a-z0-9.-]+(:\d{1,5})?$")


class EmbedOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, bool] = Field(default_factory=lambda: {k: v[0] for k, v in ITEMS.items()})
    wallet_ids: list[int] = Field(default_factory=list, max_length=200)  # empty: all active
    symbols: list[str] = Field(default_factory=list, max_length=50)  # empty: all
    theme: str = Field(default="dark", pattern=r"^(dark|light|terminal|template|custom:\d{1,9})$")
    fiat: Literal["usd", "eur", "gbp", "jpy", "cad", "aud"] = "usd"
    # Websites allowed to show this embed in an <iframe>. Empty: none can.
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)
    refresh_seconds: int = Field(default=300, ge=60, le=3600)
    heading: str = Field(default="", max_length=80)

    @field_validator("items")
    @classmethod
    def _items(cls, v):
        unknown = set(v) - set(ITEMS)
        if unknown:
            raise ValueError(f"unknown items: {', '.join(sorted(unknown))}")
        return {k: bool(v.get(k, ITEMS[k][0])) for k in ITEMS}

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v):
        out = list(dict.fromkeys(s.strip().upper() for s in v))
        if any(not re.match(r"^[A-Z0-9]{2,10}$", s) for s in out):
            raise ValueError("symbols are 2-10 letters or digits, like BTC")
        return out

    @field_validator("allowed_origins")
    @classmethod
    def _origins(cls, v):
        out = []
        for raw in v:
            o = raw.strip().lower().rstrip("/")
            if not ORIGIN_RE.match(o):
                raise ValueError(f"{raw!r} isn't a site address like https://example.com")
            out.append(o)
        return list(dict.fromkeys(out))

    @field_validator("heading")
    @classmethod
    def _heading(cls, v):
        if any(ord(c) < 32 for c in v):
            raise ValueError("the heading can't contain control characters")
        if find_secret(v):  # an embed can be public: never show a pasted recovery phrase
            raise ValueError("that looks like a recovery phrase or key: not saved")
        return v.strip()

    def on(self, item: str) -> bool:
        return self.items.get(item, False)


def base_url(settings) -> str:
    """Where embed links point: the public tunnel address if set, else the embed server."""
    if settings.embed_public_url:
        return settings.embed_public_url.rstrip("/")
    # Prefer an address other devices can use (e.g. the NetBird one) over 127.0.0.1.
    hosts = parse_hosts(settings.embed_hosts_value)
    reachable = [h for h in hosts if h not in ("0.0.0.0", "::") and not _loopback(h)]
    host = reachable[0] if reachable else probe_host(settings.embed_hosts_value)
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return (
        f"http://[{host}]:{settings.embed_port}"
        if ":" in host
        else f"http://{host}:{settings.embed_port}"
    )


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
