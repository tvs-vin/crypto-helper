"""The background job inside the server: records price history and compacts it.

It runs whether or not anyone is logged in, which alerts will need (phase 3).
"""

import asyncio
import logging
import time

from app import features
from app.db import IMMEDIATE
from app.prices import history
from app.prices.service import PricesUnavailable
from app.timeutil import utcnow

log = logging.getLogger(__name__)
TICK_SECONDS = 30
COMPACT_EVERY_SECONDS = 600


class HistoryJob:
    def __init__(self, service, session_factory):
        self.service = service
        self.factory = session_factory
        self._last_compact = 0.0
        self.last_result: dict = {}

    def tick(self) -> dict:
        """One pass: record a snapshot if due, compact if it's been a while."""
        result: dict = {"recorded": 0}
        with self.factory() as db:
            settings = history.load_settings(db)
            if not settings.enabled:
                return {"disabled": True}
            if features.load(db).practice_prices:
                # Never mix made-up prices into the real history.
                return {"skipped": "practice prices are on"}
            due = history.is_due(db, settings, utcnow())
        snap = None
        if due:
            try:
                # Fetched with no database session open: holding the write lock while the
                # price source answers (up to 10 s) would make other writes give up.
                snap = self.service.fresh(self.factory)
            except PricesUnavailable as e:
                result["skipped"] = str(e)
        with self.factory() as db:
            # This pass writes: take the write lock first (see app.db.get_db).
            db.connection(execution_options={IMMEDIATE: True})
            now = utcnow()
            if snap is not None and history.is_due(db, settings, now):
                result["recorded"] = history.record(db, snap, settings)
                if snap.stale:
                    result["skipped"] = "prices are stale"
            if time.monotonic() - self._last_compact >= COMPACT_EVERY_SECONDS:
                result.update(history.compact(db, settings, now))
                self._last_compact = time.monotonic()
            db.commit()
        self.last_result = result
        return result

    async def run_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # never let one bad tick stop history for good
                log.exception("price history tick failed")
            await asyncio.sleep(TICK_SECONDS)
