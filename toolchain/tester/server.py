"""Start a throwaway server on a temp database and complete first-launch setup."""

import base64
import os
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SpawnedServer:
    def __init__(self, price_provider: str = "mock"):
        self.tmp = tempfile.TemporaryDirectory(prefix="tester-")
        self.state = Path(self.tmp.name) / "state"
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.password = "spawn-" + secrets.token_urlsafe(18)
        self.proc: subprocess.Popen | None = None
        self.output: list[str] = []
        self.price_provider = price_provider

    def _reader(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self.output.append(line)

    def start(self, timeout: float = 20) -> None:
        env = {
            **os.environ,
            "BOT_DATABASE_URL": f"sqlite:///{self.tmp.name}/tester.db",
            "BOT_PRICE_PROVIDER": self.price_provider,
            "BOT_PRICE_BACKGROUND": "false",
            "BOT_STATE_DIR": str(self.state),
            # Throwaway key: never touch the real key file.
            "BOT_SECRET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            "PYTHONUNBUFFERED": "1",
        }
        # Never let the throwaway server pick up the installed service's config file.
        env.pop("CRYPTO_HELPER_CONFIG", None)
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
            cwd=self.tmp.name,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base_url + "/api/setup/status", timeout=1)
                if self.token_file.exists():
                    return
            except OSError:
                pass
            time.sleep(0.2)
        log = "".join(self.output)
        self.stop()
        raise RuntimeError("spawned server did not start:\n" + log)

    @property
    def token_file(self) -> Path:
        return self.state / "setup-token"

    @property
    def setup_token(self) -> str:
        return self.token_file.read_text().strip()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.tmp.cleanup()
