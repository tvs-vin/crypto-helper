"""The single source of truth for prices: one cached snapshot shared by every request.

At most one fetch per cache period (60 s by default), successful or not, so a CoinGecko
outage can't turn every page view into a 10-second timeout. When a fetch fails, the last
good prices are served marked stale; after a restart they come from the price history.
"""

import logging
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.models import PricePoint
from app.prices.catalog import FIATS, all_coins
from app.prices.providers import ProviderError, Quote
from app.timeutil import utcnow

log = logging.getLogger(__name__)


class PricesUnavailable(Exception):
    """No prices at all: the source failed and nothing was ever fetched or recorded."""


@dataclass(frozen=True)
class Snapshot:
    as_of: datetime
    source: str
    attribution: str
    quotes: dict[str, dict[str, Quote]]  # coingecko id -> fiat -> quote
    stale: bool = False
    error: str | None = None


class PriceService:
    def __init__(self, provider, cache_seconds: int = 60):
        self.provider = provider
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None
        self._attempted: float | None = None
        self.last_error: str | None = None

    def invalidate(self) -> None:
        """Fetch again on the next request (e.g. after a coin was added)."""
        with self._lock:
            self._attempted = None

    def snapshot(self, db) -> Snapshot:
        """The shared snapshot. `db` is the caller's session (used to list the coins)."""
        with self._lock:
            now = time.monotonic()
            if self._attempted is not None and now - self._attempted < self._cache_seconds:
                if self._snap is None:
                    raise PricesUnavailable(self.last_error or "prices aren't available yet")
                return self._snap
            self._attempted = now
            ids = sorted({c.coingecko_id for c in all_coins(db).values()})
            try:
                quotes = self.provider.fetch(ids, list(FIATS))
            except ProviderError as e:
                self.last_error = str(e)
                log.warning("price fetch failed: %s", e)
                fallback = self._snap or self._from_history(db)
                if fallback is None:
                    raise PricesUnavailable(str(e)) from None
                self._snap = replace(fallback, stale=True, error=str(e))
                return self._snap
            self.last_error = None
            self._snap = Snapshot(utcnow(), self.provider.name, self.provider.attribution, quotes)
            return self._snap

    def _from_history(self, db) -> Snapshot | None:
        """The newest recorded price of each coin, for serving stale data after a restart."""
        newest = (
            select(PricePoint.coingecko_id, PricePoint.fiat, func.max(PricePoint.at).label("at"))
            .group_by(PricePoint.coingecko_id, PricePoint.fiat)
            .subquery()
        )
        rows = db.scalars(
            select(PricePoint).join(
                newest,
                (PricePoint.coingecko_id == newest.c.coingecko_id)
                & (PricePoint.fiat == newest.c.fiat)
                & (PricePoint.at == newest.c.at),
            )
        ).all()
        if not rows:
            return None
        quotes: dict[str, dict[str, Quote]] = {}
        for r in rows:
            change = Decimal(r.change_24h) if r.change_24h is not None else None
            quotes.setdefault(r.coingecko_id, {})[r.fiat] = Quote(Decimal(r.price), change)
        return Snapshot(
            max(r.at for r in rows),
            f"{self.provider.name} (saved history)",
            self.provider.attribution,
            quotes,
            stale=True,
        )
