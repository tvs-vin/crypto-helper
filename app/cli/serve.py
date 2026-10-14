"""`crypto-helper serve`: run the web server (what the systemd unit starts)."""

import ipaddress

from app.cli.common import CliError, load_settings


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_bind(host: str, allow_remote: bool) -> str | None:
    """Return a warning for a non-loopback bind, or raise if it isn't allowed."""
    if is_loopback(host):
        return None
    if host in ("0.0.0.0", "::", ""):
        raise CliError(
            f"Refusing to listen on every network interface ({host!r}): that's a bare open "
            "port. Keep BOT_HOST=127.0.0.1 and use an SSH tunnel, Tailscale, NetBird or "
            "Cloudflare Access. See WIKI/guides/remote-access.md."
        )
    if not allow_remote:
        raise CliError(
            f"BOT_HOST={host} isn't this machine only. If that address is on a private network "
            "you trust (e.g. your NetBird/Tailscale IP), set BOT_ALLOW_REMOTE_BIND=true. "
            "See WIKI/guides/remote-access.md."
        )
    return (
        f"Listening on {host}, not just this machine. Anyone who can reach that "
        "address can reach the login page."
    )


def serve() -> int:
    import uvicorn

    settings = load_settings()
    warning = check_bind(settings.host, settings.allow_remote_bind)
    if warning:
        print(f"WARNING: {warning}", flush=True)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        # Trust X-Forwarded-For only from this machine (tailscale serve / a local proxy),
        # so the audit log shows the real client address.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
        log_level="info",
    )
    return 0
