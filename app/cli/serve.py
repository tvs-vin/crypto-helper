"""`crypto-helper serve`: run the web server (what the systemd unit starts)."""

import ipaddress
import socket

from app import logredact
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


def check_embed_bind(host: str, allow_public: bool) -> str | None:
    if is_loopback(host):
        return None
    if not allow_public:
        raise CliError(
            f"BOT_EMBED_HOST includes {host!r}, which isn't this machine only. Embeds are "
            "meant to be reached through a tunnel (Cloudflare Tunnel, Tailscale Funnel) that "
            "connects to 127.0.0.1. To listen on other addresses anyway, set "
            "BOT_EMBED_ALLOW_PUBLIC=true. See WIKI/guides/embeds.md."
        )
    return (
        f"The embed server listens on {host}: anyone who can reach it can load embeds "
        "whose link they know (only what each embed shows; nothing else is served)."
    )


def check_embed_hosts(settings) -> list[str]:
    """Raise if the embed server may not listen where it's set to; return any warnings.
    Following the web UI ("main"), the web UI's own rules apply: those addresses were
    already approved for it (BOT_ALLOW_REMOTE_BIND), and 0.0.0.0 is still refused."""
    warnings = []
    for host in parse_hosts(settings.embed_hosts_value):
        if settings.embed_follows_main:
            if check_bind(host, settings.allow_remote_bind):
                warnings.append(
                    f"The embed server listens on {host} too, like the web UI: anyone who "
                    "can reach that address can load embeds whose link they know."
                )
        else:
            warning = check_embed_bind(host, settings.embed_allow_public)
            if warning:
                warnings.append(warning)
    return warnings


def serve_embed() -> int:
    import uvicorn

    try:
        settings = load_settings()
    except CliError:
        raise CliError(
            "`serve --embed` is what the embed service runs, as its own user. To "
            "turn embeds on, use: crypto-helper embed enable"
        ) from None
    if not settings.embed_enabled:
        raise CliError("Embeds are off. Turn them on with: crypto-helper embed enable")
    hosts = parse_hosts(settings.embed_hosts_value)
    try:
        parse_networks(settings.embed_allowed_networks)
    except ValueError as e:
        raise CliError(
            str(e).replace("BOT_ALLOWED_NETWORKS", "BOT_EMBED_ALLOWED_NETWORKS")
        ) from None
    for warning in check_embed_hosts(settings):
        print(f"WARNING: {warning}", flush=True)
    sockets = [bind_socket(h, settings.embed_port) for h in hosts]
    same = " (same addresses as the web UI)" if settings.embed_follows_main else ""
    print(
        f"Embed server on {', '.join(f'{h}:{settings.embed_port}' for h in hosts)}{same}",
        flush=True,
    )
    from app.embeds.server import create_embed_app

    # Hand over the settings checked above, so the app can't read different ones.
    config = uvicorn.Config(
        create_embed_app(settings),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logredact.install()  # after uvicorn set up its loggers: no embed tokens or tickets in the log
    server.run(sockets=sockets)
    return 0


def serve() -> int:
    import uvicorn

    try:
        settings = load_settings()
    except CliError:
        raise CliError(
            "`serve` is what the background service runs, as its own user, and can't read "
            "the service's config as you. To start it, use: crypto-helper service start"
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
    from app.main import create_app

    # Hand over the settings checked above, so the app can't read different ones.
    config = uvicorn.Config(
        create_app(settings),
        # Trust X-Forwarded-For only from this machine (tailscale serve / a local proxy),
        # so the audit log shows the real client address.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
        log_level="info",
    )
    server = uvicorn.Server(config)
    logredact.install()  # after uvicorn set up its loggers: no embed tokens or tickets in the log
    server.run(sockets=sockets)
    return 0
