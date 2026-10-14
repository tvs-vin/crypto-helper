from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Session(Base):
    """Server-side login session. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


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
