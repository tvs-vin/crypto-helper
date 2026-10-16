"""Feature switches for the whole install, changed in the Services window (services.manage).

Unlike app switches (app/apps.py), these apply to everyone, super included: they describe how
this install runs, not who may do what. Price history recording has its own switch in
the price history settings (app/prices/history.py), shown in the Services window too.
"""

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DbSession

from app.models import AppSetting

SETTINGS_KEY = "features"


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # New wallets of kind "paper" (practice balances). Existing ones stay either way.
    paper_wallets: bool = True
    # Simulated transfers between tracked wallets.
    practice_transfers: bool = True
    # Use made-up prices instead of CoinGecko (for trying things out offline). While on,
    # price history isn't recorded, so practice prices never mix with real ones.
    practice_prices: bool = False


LABELS = {
    "paper_wallets": "Paper wallets",
    "practice_transfers": "Practice transfers",
    "practice_prices": "Practice prices",
}


def load(db: DbSession) -> Features:
    row = db.get(AppSetting, SETTINGS_KEY)
    return Features(**row.value) if row else Features()


def save(db: DbSession, features: Features, actor: str | None) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        db.add(AppSetting(key=SETTINGS_KEY, value=features.model_dump(), updated_by=actor))
    else:
        row.value = features.model_dump()
        row.updated_by = actor


class FeatureOff(Exception):
    """A request needs a feature that's switched off (answered as 403 with the reason)."""

    def __init__(self, key: str):
        super().__init__(
            f"{LABELS[key]} are turned off on this install (Services window)"
            if key != "practice_prices"
            else "Practice prices are turned off"
        )


def require(db: DbSession, key: str) -> None:
    if not getattr(load(db), key):
        raise FeatureOff(key)
