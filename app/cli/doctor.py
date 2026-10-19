"""`crypto-helper doctor`: check the install end to end and say how to fix what's wrong."""

import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from app import migrate
from app.cli import system
from app.cli.common import PROG, CliError, bad, dim, is_root, load_settings, ok, run, warn
from app.cli.layout import Layout, current_layout
from app.cli.serve import is_loopback
from app.netaccess import host_covered, parse_hosts, parse_networks, probe_host

OK, INFO, WARN, FAIL, SKIP = "ok", "info", "warn", "fail", "skip"
SYMBOL = {OK: ok("✓"), INFO: dim("i"), WARN: warn("!"), FAIL: bad("✗"), SKIP: dim("-")}


@dataclass
class Result:
    level: str
    title: str
    fix: str = ""


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _owner(path: Path) -> str:
    import pwd

    try:
        return pwd.getpwuid(path.stat().st_uid).pw_name
    except KeyError:
        return str(path.stat().st_uid)


# ---- individual checks -------------------------------------------------------------------


def check_python() -> Result:
    v = sys.version_info
    if v >= (3, 12):
        return Result(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    return Result(FAIL, f"Python {v.major}.{v.minor} is too old", "Install Python 3.12 or newer.")


def check_clock() -> Result:
    if not system.have("timedatectl"):
        return Result(SKIP, "Clock sync: timedatectl not available")
    synced = run(
        ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], check=False
    ).stdout.strip()
    if synced == "yes":
        return Result(OK, "Clock is synchronized (2FA codes depend on it)")
    return Result(
        FAIL,
        "Clock is NOT synchronized: 2FA codes will be rejected",
        "sudo timedatectl set-ntp true",
    )


def check_service(layout: Layout) -> list[Result]:
    if not layout.is_installed():
        return [
            Result(
                INFO,
                "Not installed as a service (running from a checkout)",
                "To install: sudo ./install.sh",
            )
        ]
    from app.cli.service import SERVICE, TIMER

    p = system.unit_properties(SERVICE, "ActiveState", "UnitFileState", "NRestarts")
    out = []
    if p.get("ActiveState") == "active":
        out.append(Result(OK, "Service is running"))
    else:
        out.append(
            Result(
                FAIL,
                f"Service is {p.get('ActiveState')}",
                f"sudo {PROG} service start, then sudo {PROG} service logs",
            )
        )
    if p.get("UnitFileState") == "enabled":
        out.append(Result(OK, "Service starts at boot"))
    else:
        out.append(Result(WARN, "Service won't start at boot", f"sudo systemctl enable {SERVICE}"))
    if int(p.get("NRestarts", "0") or 0) > 0:
        out.append(
            Result(
                WARN,
                f"Service has crashed and restarted {p['NRestarts']} time(s)",
                f"sudo {PROG} service logs",
            )
        )
    t = system.unit_properties(TIMER, "ActiveState")
    if t.get("ActiveState") == "active":
        out.append(Result(OK, "Daily backup timer is active"))
    else:
        out.append(
            Result(WARN, "Daily backup timer isn't active", f"sudo systemctl enable --now {TIMER}")
        )
    return out


def check_web(settings) -> list[Result]:
    host = probe_host(settings.host)
    url = f"http://{host}:{settings.port}/api/setup/status"
    try:
        status, headers, _ = system.http_get(url, timeout=3)
    except OSError as e:
        return [
            Result(
                FAIL,
                f"Web server doesn't answer at {url} ({e.__class__.__name__})",
                f"sudo {PROG} service status",
            )
        ]
    out = [Result(OK, f"Web server answers on http://{host}:{settings.port}")]
    missing = [
        h
        for h in ("content-security-policy", "x-frame-options", "x-content-type-options")
        if h not in headers
    ]
    if missing:
        out.append(
            Result(
                FAIL,
                f"Security headers missing: {', '.join(missing)}",
                "Something in front of the app is stripping them.",
            )
        )
    else:
        out.append(Result(OK, "Security headers are present"))
    if "server" in headers:
        out.append(Result(INFO, f"Server header reveals: {headers['server']}"))
    return out


def check_bind(settings) -> list[Result]:
    out = []
    hosts = parse_hosts(settings.host)
    for host in hosts:
        if host in ("0.0.0.0", "::"):
            out.append(
                Result(
                    FAIL,
                    f"BOT_HOST includes {host}: every interface",
                    "Use 127.0.0.1 plus specific addresses (WIKI/guides/remote-access.md)",
                )
            )
        elif is_loopback(host):
            out.append(Result(OK, f"Listening on this machine ({host})"))
        else:
            out.append(
                Result(
                    INFO,
                    f"Also listening on {host}",
                    "Fine on a private mesh like NetBird; see WIKI/guides/remote-access.md",
                )
            )
    try:
        networks = parse_networks(settings.allowed_networks)
    except ValueError as e:
        out.append(Result(FAIL, str(e), "Fix BOT_ALLOWED_NETWORKS in the config"))
        networks = []
    if networks is None:
        out.append(
            Result(
                WARN,
                "BOT_ALLOWED_NETWORKS=* lets any client address in",
                "List your networks, e.g. 127.0.0.0/8,100.64.0.0/16",
            )
        )
    else:
        out.append(Result(OK, f"Clients allowed only from {settings.allowed_networks}"))
        for host in hosts:
            if not is_loopback(host) and not host_covered(host, networks):
                out.append(
                    Result(
                        WARN,
                        f"{host} is listened on but its network isn't in "
                        "BOT_ALLOWED_NETWORKS, so clients there get 403",
                        "Add that network (e.g. 100.64.0.0/16 for NetBird)",
                    )
                )
    if system.have("ss"):
        lines = run(["ss", "-ltnH"], check=False).stdout.splitlines()
        exposed = [
            ln.split()[3]
            for ln in lines
            if len(ln.split()) > 3
            and ln.split()[3].endswith(f":{settings.port}")
            and re.match(r"^(0\.0\.0\.0|\*|\[::\]):", ln.split()[3])
        ]
        if exposed:
            out.append(
                Result(
                    FAIL,
                    f"Port {settings.port} is open on all interfaces ({', '.join(exposed)})",
                    "Check what is listening: ss -ltnp",
                )
            )
    if not settings.cookie_secure:
        out.append(
            Result(
                INFO,
                "Cookies aren't marked Secure (right for plain-HTTP tunnels)",
                "Set BOT_COOKIE_SECURE=true once you serve it over HTTPS",
            )
        )
    return out


def check_files(settings, layout: Layout) -> list[Result]:
    out = []
    from app.crypto import load_secret_box

    try:
        load_secret_box(settings)
        source = "BOT_SECRET_KEY" if settings.secret_key else settings.secret_key_file
        out.append(Result(OK, f"Encryption key is valid ({source})"))
    except (SystemExit, OSError) as e:
        out.append(
            Result(
                FAIL,
                f"Encryption key problem: {e}",
                "See WIKI/reference/configuration.md#secret-key",
            )
        )
    key = Path(settings.secret_key_file).expanduser()
    if not settings.secret_key and key.exists():
        if _mode(key) & 0o077 & ~0o040:
            out.append(
                Result(
                    FAIL,
                    f"{key} is readable or writable by others ({oct(_mode(key))})",
                    f"sudo chmod 640 {key}",
                )
            )
        else:
            out.append(Result(OK, f"Key file permissions are private ({oct(_mode(key))})"))
    if layout.is_installed():
        if _mode(layout.config) & 0o007:
            out.append(
                Result(
                    FAIL,
                    f"{layout.config} is readable by everyone",
                    f"sudo chmod 640 {layout.config}",
                )
            )
        else:
            out.append(Result(OK, "Config file isn't readable by other users"))
    db_path = Path(settings.database_url.removeprefix("sqlite:///"))
    if settings.database_url.startswith("sqlite:///") and db_path.exists():
        folder_open = _mode(db_path.parent) & 0o007
        file_open = _mode(db_path) & 0o007
        if folder_open and file_open:
            out.append(
                Result(
                    WARN,
                    f"Database {db_path} is readable by every user",
                    f"chmod 600 {db_path} (the installed service does this for you)",
                )
            )
        else:
            out.append(Result(OK, "Database isn't readable by other users"))
        if layout.is_installed() and _owner(db_path) != layout.user:
            out.append(
                Result(
                    FAIL,
                    f"Database is owned by {_owner(db_path)}, not {layout.user}",
                    f"sudo chown {layout.user}: {db_path}",
                )
            )
        free = shutil.disk_usage(db_path.parent).free
        gb = free / 1e9
        if free < 200e6:
            out.append(
                Result(
                    FAIL,
                    f"Only {gb:.2f} GB free for the database",
                    "Free up disk space (or ask for a bigger disk)",
                )
            )
        elif free < 1e9:
            out.append(Result(WARN, f"Only {gb:.2f} GB free for the database"))
        else:
            out.append(Result(OK, f"{gb:.1f} GB free disk space"))
    return out


def check_database(settings) -> list[Result]:
    from app.db import make_engine, make_session_factory
    from app.models import RecoveryCode, User
    from app.timeutil import utcnow

    engine = make_engine(settings.database_url)
    current, head = migrate.current_revision(engine), migrate.head_revision()
    if current is None:
        return [Result(INFO, "Database is empty: the server hasn't started yet")]
    out = []
    if current == head:
        out.append(Result(OK, f"Database schema is current ({head})"))
    else:
        out.append(
            Result(
                FAIL, f"Database is at {current}, code expects {head}", f"sudo {PROG} db migrate"
            )
        )
        return out
    with make_session_factory(engine)() as db:
        sup = db.scalar(select(User).where(User.is_super.is_(True)))
        if sup is None:
            out.append(
                Result(
                    WARN,
                    "Setup isn't done: no super account yet",
                    f"sudo {PROG} setup token, then WIKI/guides/getting-started.md",
                )
            )
        elif not sup.totp_enabled:
            out.append(
                Result(
                    WARN, "super has no 2FA", "Log in as super and follow WIKI/guides/set-up-2fa.md"
                )
            )
        else:
            out.append(Result(OK, "super has 2FA"))
        counts = dict(
            db.execute(
                select(RecoveryCode.user_id, func.count()).group_by(RecoveryCode.user_id)
            ).all()
        )
        low = [
            u.username
            for u in db.scalars(select(User).where(User.totp_enabled.is_(True)))
            if counts.get(u.id, 0) < 3
        ]
        if low:
            out.append(
                Result(
                    WARN,
                    f"Few recovery codes left: {', '.join(low)}",
                    "They can make a new set: WIKI/guides/recovery-codes.md",
                )
            )
        locked = [
            u.username
            for u in db.scalars(select(User))
            if u.locked_until and u.locked_until > utcnow()
        ]
        if locked:
            out.append(
                Result(
                    INFO,
                    f"Locked out right now: {', '.join(locked)}",
                    f"sudo {PROG} account <name> unlock",
                )
            )
    from app.setup_token import setup_token_path

    if sup is not None and setup_token_path(settings).exists():
        out.append(
            Result(
                WARN,
                "A leftover setup token file exists after setup",
                f"rm {setup_token_path(settings)}",
            )
        )
    return out


def check_prices(settings) -> Result:
    from app.prices.providers import ProviderError, make_provider

    try:
        provider = make_provider(settings)
    except SystemExit as e:
        return Result(FAIL, str(e), "Set BOT_PRICE_PROVIDER to coingecko or mock")
    try:
        quotes = provider.fetch(["bitcoin"], ["usd"])
    except ProviderError as e:
        return Result(
            WARN,
            f"Price source unreachable: {e}",
            "Prices will show as stale until it's back; check internet access",
        )
    if "bitcoin" not in quotes:
        return Result(WARN, f"{provider.name} answered without a BTC price")
    return Result(
        OK if settings.price_provider != "mock" else WARN,
        f"Price source answers ({provider.name})",
        "BOT_PRICE_PROVIDER=mock shows practice prices, not real ones"
        if settings.price_provider == "mock"
        else "",
    )


def check_history(settings) -> Result:
    from app.db import make_engine, make_session_factory
    from app.prices import history
    from app.timeutil import utcnow

    engine = make_engine(settings.database_url)
    if migrate.current_revision(engine) != migrate.head_revision():
        return Result(SKIP, "Price history: database not current")
    with make_session_factory(engine)() as db:
        s = history.load_settings(db)
        st = history.stats(db)
    if not s.enabled:
        return Result(
            INFO,
            "Price history recording is turned off",
            "PUT /api/prices/history/settings with enabled: true",
        )
    newest = st["newest_point"]
    if newest is None:
        return Result(
            INFO,
            "No price history recorded yet",
            "The service records one every few minutes once it's running",
        )
    age_min = (utcnow() - newest).total_seconds() / 60
    if age_min > 3 * s.fine_interval_minutes + 5:
        return Result(
            WARN,
            f"Price history stopped: newest point is {age_min:.0f} min old",
            f"Check the service log: sudo {PROG} service logs",
        )
    return Result(OK, f"Price history recording ({st['points']} points, {st['candles']} candles)")


def check_balance_history(settings) -> Result:
    from sqlalchemy import func, select

    from app import balance_history as bh
    from app.db import make_engine, make_session_factory
    from app.models import Wallet
    from app.timeutil import utcnow

    engine = make_engine(settings.database_url)
    if migrate.current_revision(engine) != migrate.head_revision():
        return Result(SKIP, "Balance history: database not current")
    with make_session_factory(engine)() as db:
        s = bh.load_settings(db)
        st = bh.stats(db)
        wallets = db.scalar(select(func.count()).select_from(Wallet))
    if not s.enabled:
        return Result(
            INFO,
            "Balance history recording is turned off",
            "Settings → Prices → Balance history, or the Services window",
        )
    if st["newest"] is None:
        return Result(
            INFO,
            "No balance history recorded yet",
            "The service takes a snapshot every hour once there are wallets and prices",
        )
    age_min = (utcnow() - st["newest"]).total_seconds() / 60
    if wallets and age_min > 3 * s.interval_minutes + 5:
        return Result(
            WARN,
            f"Balance history stopped: newest snapshot is {age_min:.0f} min old",
            f"Prices may be stale (see above), or check the service log: sudo {PROG} service logs",
        )
    return Result(OK, f"Balance history recording ({st['snapshots']} snapshots)")


def check_ffmpeg() -> Result:
    from app.wallpapers import have_ffmpeg

    if have_ffmpeg():
        return Result(OK, "ffmpeg is installed (video wallpapers)")
    return Result(
        INFO, "ffmpeg isn't installed: video wallpapers are off", "sudo apt install ffmpeg"
    )


def check_agent(settings, layout: Layout) -> list[Result]:
    if not layout.is_installed():
        return []
    from app.agent.client import AgentError, AgentUnavailable, call
    from app.cli.service import AGENT

    state = system.unit_properties(AGENT, "UnitFileState", "ActiveState")
    if state.get("UnitFileState") != "enabled":
        return [
            Result(
                INFO,
                "Agent is off: the Services window can't turn services on and off",
                f"sudo {PROG} agent enable",
            )
        ]
    try:
        call(settings.agent_socket, "status", "<doctor>", timeout=5)
    except (AgentUnavailable, AgentError) as e:
        return [
            Result(FAIL, f"Agent is enabled but not answering ({e})", f"sudo {PROG} agent status")
        ]
    out = [Result(OK, "Agent is running and answering")]
    try:
        mode = stat.S_IMODE(os.stat(settings.agent_socket).st_mode)
        if mode & 0o007:
            out.append(
                Result(
                    FAIL,
                    f"Agent socket is open to other users ({oct(mode)})",
                    f"sudo {PROG} agent enable",
                )
            )
    except OSError:
        pass
    return out


def check_embeds(settings, layout: Layout) -> list[Result]:
    from app.netaccess import parse_hosts

    if not settings.embed_enabled:
        return [Result(INFO, "Embeds are off", f"To share embeds: sudo {PROG} embed enable")]
    out = []
    if layout.is_installed():
        from app.cli.service import EMBED

        state = system.unit_properties(EMBED, "ActiveState").get("ActiveState")
        out.append(
            Result(OK, "Embed server is running")
            if state == "active"
            else Result(
                FAIL, f"Embeds are on but the embed server is {state}", f"sudo {PROG} service logs"
            )
        )
    public = [h for h in parse_hosts(settings.embed_hosts_value) if not is_loopback(h)]
    if public and settings.embed_follows_main:
        out.append(
            Result(
                INFO,
                f"Embed server listens where the web UI does ({', '.join(public)}), "
                f"port {settings.embed_port}",
            )
        )
    elif public:
        out.append(
            Result(
                WARN,
                f"Embed server listens beyond this machine ({', '.join(public)})",
                "Fine if intended; a tunnel to 127.0.0.1 is safer (WIKI/guides/embeds.md)",
            )
        )
    if not settings.embed_public_url:
        out.append(
            Result(
                INFO,
                "Embed links point at the embed server's own address",
                f"Behind a tunnel: sudo {PROG} embed enable --public-url https://…",
            )
        )
    return out


def check_backups(settings, layout: Layout) -> Result:
    from app.cli.database import latest_backup

    try:
        last = latest_backup(settings)
    except PermissionError:
        return Result(SKIP, "Backups: no permission to look", f"sudo {PROG} doctor")
    if last is None:
        level = WARN if layout.is_installed() else INFO
        return Result(level, "No automatic backups yet", f"sudo {PROG} db backup")
    age_h = (time.time() - last.stat().st_mtime) / 3600
    if age_h > 48:
        return Result(
            WARN,
            f"Newest backup is {age_h / 24:.0f} days old ({last.name})",
            f"sudo {PROG} db backup; check the timer with sudo {PROG} doctor",
        )
    return Result(OK, f"Newest backup is {age_h:.0f} h old ({last.name})")


def check_sandbox(layout: Layout) -> Result:
    if not layout.is_installed() or not system.have("systemd-analyze"):
        return Result(SKIP, "Sandbox score: service not installed")
    from app.cli.service import SERVICE

    out = run(["systemd-analyze", "security", "--no-pager", SERVICE], check=False).stdout
    m = re.search(r"Overall exposure level for \S+: ([\d.]+) (\S+)", out)
    if not m:
        return Result(SKIP, "Sandbox score: couldn't read systemd-analyze output")
    score = float(m.group(1))
    level = OK if score <= 3 else WARN
    return Result(
        level,
        f"systemd sandbox exposure score {score} {m.group(2)} (0 = locked down, 10 = wide open)",
    )


# ---- runner ------------------------------------------------------------------------------


def doctor() -> int:
    from app.cli.info import version_string

    layout = current_layout()
    print(f"{PROG} doctor  {dim(version_string())}\n")
    results: list[Result] = [check_python(), check_clock()]
    results += check_service(layout)
    try:
        settings = load_settings()
    except CliError as e:
        results.append(Result(FAIL, str(e)))
        settings = None
    if settings is not None:
        results += check_bind(settings)
        if (
            not layout.is_installed()
            or system.unit_properties("crypto-helper.service", "ActiveState").get("ActiveState")
            == "active"
        ):
            results += check_web(settings)
        if layout.is_installed() and not is_root() and not os.access(layout.key, os.R_OK):
            results.append(
                Result(SKIP, "File and database checks need root", f"sudo {PROG} doctor")
            )
        else:
            results += check_files(settings, layout)
            results += check_database(settings)
            results.append(check_history(settings))
            results.append(check_balance_history(settings))
            results.append(check_backups(settings, layout))
        results.append(check_prices(settings))
        results += check_embeds(settings, layout)
        results += check_agent(settings, layout)
        results.append(check_ffmpeg())
    results.append(check_sandbox(layout))

    for r in results:
        print(f"  {SYMBOL[r.level]} {r.title}")
        if r.fix and r.level in (WARN, FAIL, INFO):
            print(f"      {dim('-> ' + r.fix)}")
    n = {lvl: sum(r.level == lvl for r in results) for lvl in (OK, WARN, FAIL)}
    summary = f"{n[OK]} ok, {n[WARN]} warning(s), {n[FAIL]} problem(s)"
    print("\n" + (bad(summary) if n[FAIL] else warn(summary) if n[WARN] else ok(summary)))
    return 1 if n[FAIL] else 0
