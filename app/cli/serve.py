"""`crypto-helper serve`: run the web server (what the systemd unit starts)."""

import ipaddress
import socket

from app.cli.common import CliError, load_settings
from app.netaccess import parse_hosts, parse_networks


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


def bind_socket(host: str, port: int) -> socket.socket:
    """A listening socket. IP_FREEBIND lets it bind an address that isn't up yet, e.g. the
    NetBird address while NetBird is still connecting at boot."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "IP_FREEBIND"):
        level = socket.IPPROTO_IPV6 if family == socket.AF_INET6 else socket.IPPROTO_IP
        sock.setsockopt(level, socket.IP_FREEBIND, 1)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    try:
        sock.bind((host, port))
    except OSError as e:
        sock.close()
        raise CliError(f"Can't listen on {host}:{port}: {e.strerror}") from None
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


def serve() -> int:
    import uvicorn

    try:
        settings = load_settings()
    except CliError as e:
        raise CliError(
            f"{e} `serve` is what the background service runs; to start it, use: "
            "crypto-helper service start"
        ) from None
    hosts = parse_hosts(settings.host)
    try:
        parse_networks(settings.allowed_networks)
    except ValueError as e:
        raise CliError(str(e)) from None
    for host in hosts:
        warning = check_bind(host, settings.allow_remote_bind)
        if warning:
            print(f"WARNING: {warning}", flush=True)
    sockets = [bind_socket(h, settings.port) for h in hosts]
    print(
        f"Listening on {', '.join(f'{h}:{settings.port}' for h in hosts)}; clients allowed "
        f"from {settings.allowed_networks}",
        flush=True,
    )
    config = uvicorn.Config(
        "app.main:create_app",
        factory=True,
        # Trust X-Forwarded-For only from this machine (tailscale serve / a local proxy),
        # so the audit log shows the real client address.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
        log_level="info",
    )
    uvicorn.Server(config).run(sockets=sockets)
    return 0
