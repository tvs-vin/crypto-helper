"""The terminal bridge: one login session, started by the agent as its own systemd unit.

`crypto-helper agent terminal-bridge` makes a one-time socket, waits for the web app to
connect (only root or the service user, once, within 30 seconds), opens a pseudo-terminal and
runs the system's `login` on it. The Linux password is checked by `login` (PAM), never by
Crypto Helper. Everything typed goes straight to the pty; nothing is logged.

Frames on the socket, both ways: 1 byte type, 4 bytes big-endian length, payload.
  DATA   (0): terminal bytes
  RESIZE (1): web -> bridge, 4 bytes: columns, rows (uint16 each)
  EXIT   (2): bridge -> web, the session ended
"""

import fcntl
import os
import select
import signal
import socket
import struct
import termios
import time

DATA, RESIZE, EXIT = 0, 1, 2
MAX_FRAME = 64 * 1024
ACCEPT_SECONDS = 30
LOGIN = ["/bin/login"]


def frame(kind: int, payload: bytes = b"") -> bytes:
    return struct.pack(">BI", kind, len(payload)) + payload


class FrameReader:
    """Collects bytes from a stream and yields whole frames."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data
        while len(self.buf) >= 5:
            kind, size = struct.unpack(">BI", self.buf[:5])
            if size > MAX_FRAME or kind not in (DATA, RESIZE, EXIT):
                raise ValueError("bad frame")
            if len(self.buf) < 5 + size:
                return
            payload, self.buf = self.buf[5 : 5 + size], self.buf[5 + size :]
            yield kind, payload


def _set_size(fd: int, cols: int, rows: int) -> None:
    cols, rows = max(20, min(cols, 500)), max(5, min(rows, 200))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _listen(path: str, group_gid: int | None) -> tuple[socket.socket, int]:
    """Ready before it's visible: bind under a temporary name, set owner and mode, listen,
    then link it into place. Whoever sees `path` (the agent waits for it) can connect at
    once. A hard link never replaces anything (it fails if `path` exists), unlike rename:
    this runs as root, so it must never be able to overwrite a file it didn't make.
    Returns the socket and the inode of its file."""
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    tmp = f"{path}.{os.getpid()}.new"
    old = os.umask(0o177)
    try:
        srv.bind(tmp)  # fails if anything is there already
    finally:
        os.umask(old)
    try:
        if group_gid is not None:
            os.chown(tmp, 0, group_gid)
        os.chmod(tmp, 0o660)
        srv.listen(1)
        os.link(tmp, path)  # FileExistsError if `path` exists: nothing is replaced
        inode = os.stat(tmp).st_ino
    finally:
        os.unlink(tmp)  # only ever our own temporary socket
    return srv, inode


def _remove_own(path: str, inode: int) -> None:
    """Delete `path` only if it's still the socket this bridge made."""
    try:
        if os.lstat(path).st_ino == inode:
            os.unlink(path)
    except FileNotFoundError:
        pass


def accept_one(path: str, allowed_uids: set[int], group_gid: int | None) -> socket.socket | None:
    """The single connection this session takes; the socket file is gone afterwards."""
    from app.agent.server import peer_uid

    srv, inode = _listen(path, group_gid)
    try:
        deadline = time.monotonic() + ACCEPT_SECONDS
        while (left := deadline - time.monotonic()) > 0:
            srv.settimeout(left)
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                return None
            if peer_uid(conn) in allowed_uids:
                return conn
            conn.close()  # someone else: refuse and keep waiting
        return None
    finally:
        srv.close()
        _remove_own(path, inode)


def spawn(command: list[str], cols: int, rows: int) -> tuple[int, int]:
    """Start `command` on a new pty as a session leader. Returns (pid, master fd)."""
    master, slave = os.openpty()
    _set_size(master, cols, rows)
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            env = {"TERM": "xterm-256color", "LANG": os.environ.get("LANG", "C.UTF-8")}
            os.execve(command[0], command, env)
        finally:
            os._exit(127)
    os.close(slave)
    return pid, master


def relay(conn: socket.socket, pid: int, master: int) -> None:
    """Pass bytes both ways until either side ends; then end the other."""
    reader = FrameReader()
    conn.setblocking(False)
    try:
        while True:
            ready, _, _ = select.select([conn, master], [], [], 1.0)
            if master in ready:
                try:
                    data = os.read(master, 16384)
                except OSError:  # EIO: the session's last process exited
                    data = b""
                if not data:
                    break
                conn.sendall(frame(DATA, data))
            if conn in ready:
                data = conn.recv(65536)
                if not data:
                    break
                for kind, payload in reader.feed(data):
                    if kind == DATA:
                        os.write(master, payload)
                    elif kind == RESIZE and len(payload) == 4:
                        cols, rows = struct.unpack(">HH", payload)
                        _set_size(master, cols, rows)  # the kernel tells the program (SIGWINCH)
            if not _alive(pid):
                break
    except (OSError, ValueError):
        pass
    finally:
        try:
            conn.setblocking(True)
            conn.sendall(frame(EXIT))
        except OSError:
            pass
        conn.close()
        _end(pid)
        os.close(master)


def _alive(pid: int) -> bool:
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return False


def _end(pid: int) -> None:
    """Hang up the session (like closing a terminal), then make sure it's gone."""
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
        if not _alive(pid):
            return
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(20):
            if not _alive(pid):
                return
            time.sleep(0.05)


def run_bridge(
    path: str,
    cols: int,
    rows: int,
    host: str | None,
    allowed_uids: set[int],
    group_gid: int | None,
    command: list[str] | None = None,
) -> int:
    conn = accept_one(path, allowed_uids, group_gid)
    if conn is None:
        return 1
    argv = list(command or LOGIN)
    if command is None and host:
        argv += ["-h", host]  # shows where the login came from (last, auth log)
    pid, master = spawn(argv, cols, rows)
    relay(conn, pid, master)
    return 0
