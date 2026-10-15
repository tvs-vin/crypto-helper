"""Configuration, read from BOT_* environment variables (never from the repo)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/bot.db"
    # Runtime files that aren't the database (e.g. the one-time setup token).
    state_dir: str = "data"
    # Encryption key for secrets at rest (2FA secrets now, exchange keys later).
    # Either the key itself, or a file that holds it (created on first run if missing).
    secret_key: str | None = None
    secret_key_file: str = "~/.config/crypto-helper/secret.key"
    # Must be true when served over HTTPS (Tailscale / Cloudflare Access).
    cookie_secure: bool = False
    session_hours: int = 12
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    price_provider: str = "coingecko"  # coingecko | mock
    # Optional free CoinGecko "Demo" key for higher rate limits. Never logged.
    coingecko_api_key: str | None = None
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    price_cache_seconds: int = 60
    price_timeout_seconds: float = 10
    # Background job that records price history (see /api/prices/history/settings).
    price_background: bool = True
    # One or more addresses to listen on, comma-separated, e.g. 127.0.0.1,100.64.39.116
    host: str = "127.0.0.1"
    port: int = 8000
    # Clients allowed to connect, as addresses or networks, comma-separated. Anything else
    # gets 403 before reaching the app. Add your NetBird network to use it over NetBird.
    allowed_networks: str = "127.0.0.0/8,::1/128"
    # Allow BOT_HOST to be a non-loopback address (e.g. a NetBird/Tailscale IP).
    # Binding to every interface (0.0.0.0) is refused regardless.
    allow_remote_bind: bool = False
