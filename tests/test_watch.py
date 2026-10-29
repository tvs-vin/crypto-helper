"""The checks' live status and the full-screen viewer (`python -m toolchain.watch`): what the
runner writes, and what the screen shows for a run going, finished, failed or gone."""

import json
import os
import time

from toolchain import watch
from toolchain.checkstatus import Live


def text(lines):
    return "\n".join(t for t, _ in lines)


def running_status(now):
    return {
        "pid": os.getpid(),
        "started": now - 75,
        "updated": now,
        "done": False,
        "stages": [
            {
                "name": "Lint",
                "state": "ok",
                "result": "clean",
                "started": now - 75,
                "seconds": 0.1,
                "previous": 0.1,
            },
            {
                "name": "Unit tests",
                "state": "running",
                "result": "",
                "started": now - 70,
                "seconds": None,
                "previous": 200,
            },
            {
                "name": "Browser tests",
                "state": "waiting",
                "result": "",
                "started": None,
                "seconds": None,
                "previous": 170,
            },
        ],
        "progress": {"done": 250, "total": 1000, "unit": "tests"},
        "running": {"test_shell.py": {"done": 12, "total": 26, "started": now - 30}},
        "finished": [{"name": "test_wallets.py", "ok": True, "count": "56/56", "seconds": 35}],
        "failures": [],
    }


def test_a_run_in_progress():
    now = time.time()
    out = text(watch.render(running_status(now), 100, 30, now))
    assert "● running" in out and "elapsed 1:15" in out
    assert "▶ Unit tests" in out and "250/1000 tests" in out and "[#####" in out
    assert "test_shell.py" in out and "12/26" in out and "Browser tests  waiting" in out
    assert "(last run 2:50)" in out and "✓ test_wallets.py" in out
    # left: the stage's own pace (70 s for 250 of 1000: 210 s more) + the waiting stage (170 s)
    assert watch.left(running_status(now), now) == 380


def test_finished_failed_and_gone():
    now = time.time()
    done = {**running_status(now), "done": True, "ok": False, "failures": ["test_x.py::test_y"]}
    out = text(watch.render(done, 100, 30, now))
    assert "✗ something failed" in out and "Failures (1)" in out and "test_x.py::test_y" in out
    gone = {**running_status(now), "pid": 2**22 + 12345}  # no such process
    assert "stopped unexpectedly" in text(watch.render(gone, 100, 30, now))
    assert "No check run yet" in text(watch.render(None, 100, 30, now))


def test_the_screen_fits_any_size():
    now = time.time()
    for w, h in ((40, 8), (100, 30), (200, 60)):
        lines = watch.render(running_status(now), w, h, now)
        assert len(lines) <= h and all(len(t) < w for t, _ in lines)
        assert "q quit" in lines[-1][0]


def test_the_runner_writes_its_status(tmp_path):
    live = Live(tmp_path / "status.json")
    live.begin(["Lint", "Unit tests"], {"Unit tests": 200})
    live.stage_start("Unit tests")
    live.item("test_a.py", 3, 10)
    live.progress(3, 10)
    live.failure("test_a.py::test_b")
    live.item_end("test_a.py", False, "10/10", 4.2)
    live.stage_end("Unit tests", False, "9 passed, 1 failed", 5)
    live.end(False)
    data = json.loads((tmp_path / "status.json").read_text())
    assert data["done"] is True and data["ok"] is False and data["pid"] == os.getpid()
    st = {s["name"]: s for s in data["stages"]}
    assert st["Unit tests"]["state"] == "fail" and st["Unit tests"]["previous"] == 200
    assert st["Lint"]["state"] == "waiting"
    assert data["finished"][0]["name"] == "test_a.py" and data["failures"] == ["test_a.py::test_b"]
    assert not list(tmp_path.glob("*.tmp"))  # written atomically, nothing left behind
