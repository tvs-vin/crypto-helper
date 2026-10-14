"""Start a throwaway server on a temp database and complete first-launch setup."""

import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOKEN_RE = re.compile(r"^\s{2}(\S{20,})\s*$")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SpawnedServer:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tester-")
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.password = "spawn-" + secrets.token_urlsafe(18)
        self.proc: subprocess.Popen | None = None
        self.output: list[str] = []
        self._token: str | None = None
        self._token_seen = threading.Event()

    def _reader(self):
        assert self.proc and self.proc.stdout
        expecting_token = False
        for line in self.proc.stdout:
            self.output.append(line)
            if "one-time setup token" in line:
                expecting_token = True
                continue
            if expecting_token:
                m = TOKEN_RE.match(line)
                if m:
                    self._token = m.group(1)
                    self._token_seen.set()
                expecting_token = False

    def start(self, timeout: float = 20) -> None:
        env = {
            **os.environ,
            "BOT_DATABASE_URL": f"sqlite:///{self.tmp.name}/tester.db",
            "BOT_PRICE_PROVIDER": "mock",
            "PYTHONUNBUFFERED": "1",
        }
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        if not self._token_seen.wait(timeout):
            self.stop()
            raise RuntimeError(
                "spawned server never printed a setup token:\n" + "".join(self.output)
            )
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.base_url + "/api/setup/status", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            self.stop()
            raise RuntimeError("spawned server did not answer:\n" + "".join(self.output))

    @property
    def setup_token(self) -> str:
        assert self._token
        return self._token

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.tmp.cleanup()
