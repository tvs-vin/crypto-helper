"""Where the web UI listens and who may connect: the rules for changing it from the browser
(12a onboarding). Shared by the web app (which can see this machine's addresses) and the agent
(which writes the root-owned config file, and checks the same rules again).

The rules:
- never every interface (0.0.0.0 or ::): hard rule #8;
- 127.0.0.1 always stays (the server's own checks and `crypto-helper doctor` use it), and so
  does 127.0.0.0/8 among the allowed networks;
- no "everyone" network (a /0); at most 8 addresses and 16 networks.
"""

import array
import fcntl
import ipaddress
import socket
import struct
from pathlib import Path

MAX_HOSTS = 8
MAX_NETWORKS = 16
LOOPBACK = "127.0.0.1"
LOOPBACK_NET = ipaddress.ip_network("127.0.0.0/8")
REVERT_SECONDS = 120  # the browser must confirm within this, or the old settings come back


class NetConfigError(ValueError):
    pass


def check(hosts: list[str], networks: list[str]) -> tuple[list[str], list[str]]:
    """Normalised (hosts, networks), or NetConfigError saying what's wrong."""
    if not hosts or len(hosts) > MAX_HOSTS:
        raise NetConfigError(f"Between 1 and {MAX_HOSTS} listen addresses.")
    if not networks or len(networks) > MAX_NETWORKS:
        raise NetConfigError(f"Between 1 and {MAX_NETWORKS} allowed networks.")
    out_hosts: list[str] = []
    for h in hosts:
        try:
            ip = ipaddress.ip_address(str(h).strip())
        except ValueError:
            raise NetConfigError(f"{h!r} isn't an IP address.") from None
        if ip.is_unspecified:
            raise NetConfigError(
                f"{ip} means every network interface, which this app never does: list the "
                "addresses you use (e.g. 127.0.0.1 and your NetBird or Tailscale address)."
            )
        if ip.is_multicast or ip.is_link_local:
            raise NetConfigError(f"{ip} can't be listened on.")
        if str(ip) not in out_hosts:
            out_hosts.append(str(ip))
    if LOOPBACK not in out_hosts:
        raise NetConfigError("Keep 127.0.0.1: the server's own checks use it.")
    out_nets: list[str] = []
    for n in networks:
        try:
            net = ipaddress.ip_network(str(n).strip(), strict=False)
        except ValueError:
            raise NetConfigError(
                f"{n!r} isn't an address or network (like 100.64.0.0/10)."
            ) from None
        if net.prefixlen == 0:
            raise NetConfigError(
                f"{net} would let everyone connect. List your own networks instead."
            )
        if str(net) not in out_nets:
            out_nets.append(str(net))
    if not any(
        n.version == 4 and LOOPBACK_NET.subnet_of(n) for n in map(ipaddress.ip_network, out_nets)
    ):
        raise NetConfigError("Keep 127.0.0.0/8: the server's own checks connect from there.")
    return out_hosts, out_nets


def config_updates(hosts: list[str], networks: list[str]) -> dict[str, str]:
    """The BOT_* lines for these settings. Any address beyond this machine needs
    BOT_ALLOW_REMOTE_BIND, which choosing it here approves."""
    remote = any(not ipaddress.ip_address(h).is_loopback for h in hosts)
    return {
        "BOT_HOST": ",".join(hosts),
        "BOT_ALLOWED_NETWORKS": ",".join(networks),
        "BOT_ALLOW_REMOTE_BIND": "true" if remote else "false",
    }


# ---- this machine's addresses (the web app only: the agent has no network) ------------------

SIOCGIFCONF = 0x8912


def _ipv4_interfaces() -> list[tuple[str, str]]:
    """(interface, address) for every IPv4 address, via SIOCGIFCONF (no netlink needed)."""
    out = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        size = 40  # struct ifreq on 64-bit Linux
        buf = array.array("B", b"\0" * size * 64)
        addr, length = buf.buffer_info()
        got = struct.unpack(
            "iL", fcntl.ioctl(s.fileno(), SIOCGIFCONF, struct.pack("iL", length, addr))
        )[0]
        data = buf.tobytes()[:got]
        for i in range(0, got, size):
            name = data[i : i + 16].split(b"\0", 1)[0].decode(errors="replace")
            ip = socket.inet_ntoa(data[i + 20 : i + 24])
            out.append((name, ip))
    return out


def _ipv6_interfaces(path: str = "/proc/net/if_inet6") -> list[tuple[str, str]]:
    out = []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 6:
            continue
        ip = ipaddress.IPv6Address(int(parts[0], 16))
        if not ip.is_link_local:
            out.append((parts[5], str(ip)))
    return out


def kind_of(ip: str, interface: str) -> str:
    """A plain-words label for an address."""
    a = ipaddress.ip_address(ip)
    if a.is_loopback:
        return "this machine only"
    if interface.startswith(("wt", "netbird")):
        return "NetBird"
    if interface.startswith("tailscale"):
        return "Tailscale"
    if interface.startswith(("wg", "zt")):
        return "VPN"
    if a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10"):
        return "VPN (100.64.0.0/10)"
    if a.is_private:
        return "local network"
    return "public internet"


def local_addresses() -> list[dict]:
    try:
        found = _ipv4_interfaces()
    except OSError:
        found = [("lo", LOOPBACK)]
    found += _ipv6_interfaces()
    return [{"address": ip, "interface": name, "kind": kind_of(ip, name)} for name, ip in found]


def is_local(ip: str) -> bool:
    """Can this machine listen on it? (A bind to a free port says.)"""
    a = ipaddress.ip_address(ip)
    family = socket.AF_INET if a.version == 4 else socket.AF_INET6
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.bind((ip, 0))
        return True
    except OSError:
        return False
