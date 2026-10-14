"""Configuration, read from BOT_* environment variables (never from the repo)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/bot.db"
    # Must be true when served over HTTPS (Tailscale / Cloudflare Access).
    cookie_secure: bool = False
    session_hours: int = 12
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    price_provider: str = "coingecko"
    host: str = "127.0.0.1"
    port: int = 8000
