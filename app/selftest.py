"""The self-test: the end-to-end tester (toolchain/tester) run against a throwaway copy of the
server, started from the Services window. It never touches this install's data: target
`spawn` starts its own server on a temporary database (and strips every BOT_* setting).

One run at a time, in the background; the last result is kept in <state_dir>/selftest.json.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from app.timeutil import utcnow

TIMEOUT_SECONDS = 300
LOG_LINES = 60


class SelfTest:
    def __init__(self, state_dir: str | Path, command: list[str] | None = None):
        self.file = Path(state_dir) / "selftest.json"
        # Tests swap in a quick fake; the real one is the tester module.
        self.command = command or [sys.executable, "-m", "toolchain.tester", "--target", "spawn"]
        self._lock = threading.Lock()
        self.running = False
        self.started_at = None

    def last(self) -> dict | None:
        try:
            return json.loads(self.file.read_text())
        except (OSError, ValueError):
            return None

    def status(self) -> dict:
        return {
            "running": self.running,
            "started_at": self.started_at,
            "last": self.last(),
        }

    def start(self, who: str) -> bool:
        """Start a run; False if one is already running."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.started_at = utcnow().isoformat(timespec="seconds")
        threading.Thread(target=self._run, args=(who,), daemon=True).start()
        return True

    def _run(self, who: str) -> None:
        result: dict = {"started_at": self.started_at, "started_by": who}
        try:
            with tempfile.TemporaryDirectory(prefix="selftest-") as tmp:
                report = Path(tmp) / "report.json"
                try:
                    proc = subprocess.run(
                        [*self.command, "--report", str(report)],
                        cwd=tmp,
                        env={**os.environ, "NO_COLOR": "1", "PYTHONUNBUFFERED": "1"},
                        capture_output=True,
                        text=True,
                        timeout=TIMEOUT_SECONDS,
                    )
                    result["exit_code"] = proc.returncode
                    result["log"] = (proc.stdout + proc.stderr).splitlines()[-LOG_LINES:]
                except subprocess.TimeoutExpired:
                    result["exit_code"] = None
                    result["error"] = f"didn't finish within {TIMEOUT_SECONDS} seconds"
                if report.exists():
                    data = json.loads(report.read_text())
                    result["passed"] = data["passed"]
                    result["failed"] = data["failed"]
                    result["failures"] = [
                        {"suite": r["suite"], "check": r["check"], "message": r["message"]}
                        for r in data["results"]
                        if not r["ok"]
                    ]
                    result["checks"] = len(data["results"])
                elif "error" not in result:
                    result["error"] = "the tester didn't write a report (see the log)"
        except Exception as e:  # never leave "running" stuck
            result["error"] = f"{type(e).__name__}: {e}"
        result["finished_at"] = utcnow().isoformat(timespec="seconds")
        result["ok"] = (
            result.get("exit_code") == 0 and "error" not in result and not result.get("failed")
        )
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(result, indent=2))
        finally:
            self.running = False
