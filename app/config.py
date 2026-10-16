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

    # The embed-only server (a separate process: `crypto-helper serve --embed`). Off by
    # default. It serves read-only embed pages and preview images, nothing else.
    embed_enabled: bool = False
    # "main": listen on the same address(es) as the web UI (BOT_HOST), on embed_port.
    # Or list addresses of its own.
    embed_host: str = "main"
    embed_port: int = 8001
    # Required for addresses of its own beyond this machine (e.g. 0.0.0.0). Addresses shared
    # with the web UI are covered by BOT_ALLOW_REMOTE_BIND, like the web UI itself.
    embed_allow_public: bool = False
    # The address people use to reach embeds (e.g. https://embed.example.com behind a
    # tunnel). Used to build links and Discord previews. Empty: http://<embed host>:<port>.
    embed_public_url: str = ""
    embed_allowed_networks: str = "*"
    embed_rate_per_minute: int = 120

    @property
    def embed_follows_main(self) -> bool:
        return self.embed_host.strip().lower() == "main"

    @property
    def embed_hosts_value(self) -> str:
        """The embed server's address list, with "main" resolved to BOT_HOST."""
        return self.host if self.embed_follows_main else self.embed_host
