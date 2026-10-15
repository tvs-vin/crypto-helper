"""Which addresses the server listens on, and which clients may talk to it.

Two layers, on purpose. Binding decides which of this machine's addresses accept
connections; the client allowlist then checks where each connection came *from*. The second
layer matters because Linux accepts packets addressed to any of its IPs on any interface:
binding to the NetBird address alone wouldn't stop a device on the home network that routes
traffic for that address through this machine.
"""

import ipaddress

ANY = "*"


def parse_hosts(value: str) -> list[str]:
    hosts = [h.strip() for h in value.split(",") if h.strip()]
    return list(dict.fromkeys(hosts)) or ["127.0.0.1"]


def parse_networks(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
    """None means "any client" (only used by tests and explicit opt-outs)."""
    if value.strip() == ANY:
        return None
    nets = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError(
                f"BOT_ALLOWED_NETWORKS: {part!r} isn't an address or network like 100.64.0.0/16"
            ) from None
    return nets


def client_allowed(host: str | None, networks) -> bool:
    if networks is None:
        return True
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in net for net in networks)


def host_covered(host: str, networks) -> bool:
    """Whether a bound address is itself inside the allowlist (a sanity check for doctor)."""
    if networks is None or host in ("localhost",):
        return True
    try:
        return client_allowed(str(ipaddress.ip_address(host)), networks)
    except ValueError:
        return False


def probe_host(value: str) -> str:
    """The address the CLI should use to reach the server itself: a loopback one if listed
    (it's always allowed), else the first. BOT_HOST can list several, so never use it raw."""
    hosts = parse_hosts(value)
    for host in hosts:
        if host == "localhost" or host.startswith("127.") or host == "::1":
            return host
    return hosts[0]


def urls(value: str, port: int) -> list[str]:
    return [
        f"http://[{h}]:{port}" if ":" in h else f"http://{h}:{port}" for h in parse_hosts(value)
    ]
