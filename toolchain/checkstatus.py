"""The check runner's live status, for `python -m toolchain.watch` (a full-screen view of a run
in progress, like nano takes over the screen).

`toolchain/checks.py` reports what it does here; this writes it to `toolchain/.check-status.json`
(atomically, a few times a second at most). Nothing secret is in it: stage names, test file
names, counts, times and failing test names.
"""

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "toolchain" / ".check-status.json"
RECENT = 12  # finished items kept for the view
MIN_WRITE = 0.25  # seconds between writes


class Live:
    def __init__(self, path: Path = STATUS):
        self.path = path
        self.lock = threading.Lock()
        self.data: dict = {}
        self._written = 0.0
        self._on = False

    # ---- the run -------------------------------------------------------------------------

    def begin(self, stages: list[str], previous: dict[str, float]) -> None:
        """A run starts. `previous`: each stage's time on the last run (for "time left")."""
        self._on = True
        now = time.time()
        self.data = {
            "pid": os.getpid(),
            "started": now,
            "updated": now,
            "done": False,
            "ok": None,
            "stage": None,
            "stages": [
                {
                    "name": s,
                    "state": "waiting",
                    "result": "",
                    "started": None,
                    "seconds": None,
                    "previous": previous.get(s),
                }
                for s in stages
            ],
            "progress": None,  # {"done", "total", "unit"} for the running stage
            "running": {},  # item name -> {"done", "total", "started"}
            "finished": [],
            "failures": [],
        }
        self._write(force=True)

    def stage_start(self, name: str) -> None:
        with self.lock:
            st = self._stage(name)
            if st:
                st["state"], st["started"] = "running", time.time()
            self.data["stage"], self.data["progress"], self.data["running"] = name, None, {}
        self._write(force=True)

    def stage_end(self, name: str, ok: bool, result: str, seconds: float) -> None:
        with self.lock:
            st = self._stage(name)
            if st:
                st["state"], st["result"], st["seconds"] = ("ok" if ok else "fail"), result, seconds
            self.data["progress"], self.data["running"] = None, {}
        self._write(force=True)

    def end(self, ok: bool) -> None:
        with self.lock:
            self.data["done"], self.data["ok"], self.data["stage"] = True, ok, None
        self._write(force=True)

    # ---- items (a test file, a tester suite, a mutation) ----------------------------------

    def item(self, name: str, done: int, total: int | None) -> None:
        with self.lock:
            r = self.data.setdefault("running", {}).setdefault(name, {"started": time.time()})
            r["done"], r["total"] = done, total
        self._write()

    def item_end(self, name: str, ok: bool, count: str, seconds: float) -> None:
        with self.lock:
            self.data.get("running", {}).pop(name, None)
            fin = self.data.setdefault("finished", [])
            fin.insert(
                0,
                {
                    "name": name,
                    "ok": ok,
                    "count": count,
                    "seconds": round(seconds, 1),
                    "stage": self.data.get("stage"),
                },
            )
            del fin[RECENT:]
        self._write()

    def progress(self, done: int, total: int, unit: str = "tests") -> None:
        with self.lock:
            self.data["progress"] = {"done": done, "total": total, "unit": unit}
        self._write()

    def failure(self, text: str) -> None:
        with self.lock:
            self.data.setdefault("failures", []).append(text[:200])
            del self.data["failures"][:-20]
        self._write()

    # ---- writing ---------------------------------------------------------------------------

    def _stage(self, name):
        return next((s for s in self.data.get("stages", []) if s["name"] == name), None)

    def _write(self, force: bool = False) -> None:
        if not self._on:
            return
        now = time.monotonic()
        if not force and now - self._written < MIN_WRITE:
            return
        with self.lock:
            self._written = now
            self.data["updated"] = time.time()
            text = json.dumps(self.data)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text)
            os.replace(tmp, self.path)  # the viewer never reads half a file
        except OSError:
            pass


LIVE = Live()
