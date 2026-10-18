from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC now. SQLite drops tzinfo, so everything is stored as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)
