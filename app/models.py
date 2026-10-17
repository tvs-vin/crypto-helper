from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.timeutil import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    is_super: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fernet-encrypted base32 secret. Set but not enabled = enrolment pending.
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Time step of the last accepted TOTP code; codes from that step or earlier are replays.
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    # Apps switched on for this account (app/apps.py). None = every app, including new ones.
    apps: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Session(Base):
    """Server-side login session. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    # Where the session was started, so you can recognise it in Settings → Account.
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AuditLog(Base):
    """Append-only. Never store passwords, tokens or secrets in `detail`."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RecoveryCode(Base):
    """Single-use 2FA backup code. Only an argon2 hash is stored; used codes are deleted."""

    __tablename__ = "recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Wallet(Base):
    """A place coins are tracked. Phase 1: balances are typed in; nothing secret is stored."""

    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique identifier, also what you type to confirm a forced delete.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # Optional display title, shown largest in the UI.
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # exchange | onchain | paper
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    network: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    color_primary: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_secondary: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_secondary_mode: Mapped[str] = mapped_column(String(8), default="auto")
    color_scheme: Mapped[str] = mapped_column(String(16), default="analogous")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Holding(Base):
    """How much of one coin a wallet holds. Decimal stored as text, never float."""

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("wallet_id", "symbol", name="uq_holdings_wallet_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(10))
    amount: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Transfer(Base):
    """A simulated (bookkeeping-only) transfer. Wallet names are copied so history stays
    readable after a wallet is renamed or deleted."""

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    from_wallet_id: Mapped[int | None] = mapped_column(
        ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_wallet_id: Mapped[int | None] = mapped_column(
        ForeignKey("wallets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    from_wallet_name: Mapped[str] = mapped_column(String(64))
    to_wallet_name: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(10))
    amount: Mapped[str] = mapped_column(String(64))
    network: Mapped[str | None] = mapped_column(String(32), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CustomCoin(Base):
    """A coin added beyond the built-in list, by its CoinGecko id."""

    __tablename__ = "custom_coins"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10), unique=True)
    coingecko_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PricePoint(Base):
    """A detailed price snapshot (every few minutes), kept for a short window, then
    compacted into PriceCandle rows."""

    __tablename__ = "price_points"
    __table_args__ = (Index("ix_price_points_coin_fiat_at", "coingecko_id", "fiat", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    coingecko_id: Mapped[str] = mapped_column(String(128))
    fiat: Mapped[str] = mapped_column(String(8))
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    price: Mapped[str] = mapped_column(String(64))
    change_24h: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PriceCandle(Base):
    """Open/high/low/close for one coin over one interval (hourly by default)."""

    __tablename__ = "price_candles"
    __table_args__ = (
        UniqueConstraint(
            "coingecko_id", "fiat", "interval_minutes", "start", name="uq_price_candles_bucket"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    coingecko_id: Mapped[str] = mapped_column(String(128))
    fiat: Mapped[str] = mapped_column(String(8))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[str] = mapped_column(String(64))
    high: Mapped[str] = mapped_column(String(64))
    low: Mapped[str] = mapped_column(String(64))
    close: Mapped[str] = mapped_column(String(64))
    points: Mapped[int] = mapped_column(Integer)


class AppSetting(Base):
    """Server-wide settings changed at runtime (e.g. price history), as JSON by key."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserTheme(Base):
    """An uploaded .ctheme. Private to its owner unless an admin publishes it."""

    __tablename__ = "user_themes"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Wallpaper(Base):
    """An uploaded (and re-encoded) wallpaper. Files live in <state_dir>/wallpapers/. Private
    to its owner unless an admin publishes it; one that came in a theme bundle belongs to that
    theme (and goes with it)."""

    __tablename__ = "wallpapers"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    theme_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_themes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))  # image | animated | video
    file: Mapped[str] = mapped_column(String(80), unique=True)
    poster: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(32))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """One notification for one user. Never store secrets or full amounts here."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(16))  # security | system | prices | messages
    level: Mapped[str] = mapped_column(String(16))  # info | warning | critical
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(32), nullable=True)  # a window to open
    sender: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotificationChannel(Base):
    """An outside channel for one user (Discord webhook). The address is a secret: anyone who has
    it can post there. Stored encrypted; only a masked label is ever shown again."""

    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_channels_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # discord
    secret_encrypted: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(80))  # masked, for display
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)


class Delivery(Base):
    """A notification waiting to go out on a channel (an outbox: survives restarts)."""

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Embed(Base):
    """A read-only embed link. The token is stored hashed for lookup and encrypted so the
    owner can see the link again; the embed shows only what its options turn on."""

    __tablename__ = "embeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))  # portfolio | wallets | prices
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_encrypted: Mapped[str] = mapped_column(String(255))
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PriceAlert(Base):
    """A person's price alert: a coin above/below a price, or moving N % in 24 hours, in one
    currency. Fires once, then waits until the price crosses back before it can fire again."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    coingecko_id: Mapped[str] = mapped_column(String(100))
    fiat: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(8))  # above | below | move
    value: Mapped[str] = mapped_column(String(40))  # Decimal as text: a price, or a percent
    armed: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
