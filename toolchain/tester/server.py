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
    def __init__(self, price_provider: str = "mock", embed: bool = False, extra_env=None,
                 cli: bool = False):  # fmt: skip
        self.tmp = tempfile.TemporaryDirectory(prefix="tester-")
        self.state = Path(self.tmp.name) / "state"
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.password = "spawn-" + secrets.token_urlsafe(18)
        self.proc: subprocess.Popen | None = None
        self.output: list[str] = []
        self.price_provider = price_provider
        # embed=True also runs the embed server (`serve --embed`) on its own port.
        self.embed = embed
        self.embed_port = _free_port() if embed else None
        self.embed_url = f"http://127.0.0.1:{self.embed_port}" if embed else None
        self.embed_proc: subprocess.Popen | None = None
        self.extra_env = dict(extra_env or {})
        # cli=True starts it the way the service does (`crypto-helper serve`, its logging
        # included) instead of plain uvicorn.
        self.cli = cli

    def _reader(self, proc=None):
        proc = proc or self.proc
        assert proc and proc.stdout
        for line in proc.stdout:
            self.output.append(line)

    def start(self, timeout: float = 20) -> None:
        # Start from the environment minus every BOT_* setting: run from inside the installed
        # service (the Services window's self-test), the real install's settings (public
        # embed URL, secure cookies, its key file...) must never leak into the throwaway one.
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("BOT_")},
            "BOT_DATABASE_URL": f"sqlite:///{self.tmp.name}/tester.db",
            "BOT_PRICE_PROVIDER": self.price_provider,
            "BOT_PRICE_BACKGROUND": "false",
            "BOT_ALLOWED_NETWORKS": "127.0.0.0/8",
            "BOT_STATE_DIR": str(self.state),
            # Throwaway key: never touch the real key file.
            "BOT_SECRET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            "PYTHONUNBUFFERED": "1",
            # Never the real agent: a throwaway server must not switch real services.
            "BOT_AGENT_SOCKET": str(Path(self.tmp.name) / "no-agent.sock"),
        }
        env |= self.extra_env
        if self.embed:
            env |= {"BOT_EMBED_ENABLED": "true", "BOT_EMBED_PORT": str(self.embed_port)}
        # Never let the throwaway server pick up the installed service's config file.
        env.pop("CRYPTO_HELPER_CONFIG", None)
        if self.cli:  # the CLI would read the installed config: give it an empty one
            empty = Path(self.tmp.name) / "empty.env"
            empty.touch()
            env |= {"CRYPTO_HELPER_CONFIG": str(empty), "BOT_HOST": "127.0.0.1",
                    "BOT_PORT": str(self.port)}  # fmt: skip
            cmd = [sys.executable, "-m", "app.cli", "serve"]
        else:
            cmd = [sys.executable, "-m", "uvicorn", "app.main:create_app", "--factory",
                   "--host", "127.0.0.1", "--port", str(self.port)]  # fmt: skip
        self.proc = subprocess.Popen(
            cmd,
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
                    if self.embed:
                        self._start_embed(env, deadline)
                    return
            except OSError:
                pass
            time.sleep(0.2)
        log = "".join(self.output)
        self.stop()
        raise RuntimeError("spawned server did not start:\n" + log)

    def _start_embed(self, env, deadline) -> None:
        # After the main server: it migrates the database, and the embed server refuses to
        # start on one that isn't up to date.
        cmd = (
            [sys.executable, "-m", "app.cli", "serve", "--embed"] if self.cli else
            [sys.executable, "-m", "uvicorn", "app.embeds.server:create_embed_app", "--factory",
             "--host", "127.0.0.1", "--port", str(self.embed_port)]
        )  # fmt: skip
        self.embed_proc = subprocess.Popen(
            cmd,
            cwd=self.tmp.name, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )  # fmt: skip
        threading.Thread(target=self._reader, args=(self.embed_proc,), daemon=True).start()
        while time.time() < deadline and self.embed_proc.poll() is None:
            try:
                urllib.request.urlopen(self.embed_url + "/embed-assets/embed.css", timeout=1)
                return
            except OSError:
                time.sleep(0.2)
        log = "".join(self.output)
        self.stop()
        raise RuntimeError("spawned embed server did not start:\n" + log)

    @property
    def token_file(self) -> Path:
        return self.state / "setup-token"

    @property
    def setup_token(self) -> str:
        return self.token_file.read_text().strip()

    def stop(self) -> None:
        for proc in (self.embed_proc, self.proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.tmp.cleanup()
