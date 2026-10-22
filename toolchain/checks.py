"""Run the project's checks with progress you can follow, laid out like pacman: a `::` header
per stage, then one line with its own bar per item (a test file, a tester suite, a mutation),
failures right under the item they belong to, and a summary table with times at the end.

    .venv/bin/python -m toolchain.checks                 # lint, unit, JS, tester
    .venv/bin/python -m toolchain.checks --ui            # ...and the browser tests
    .venv/bin/python -m toolchain.checks --only unit ui  # some stages
    .venv/bin/python -m toolchain.checks --mutations FILE.py   # mutation checks (see below)
    .venv/bin/python -m toolchain.checks -j 4            # 4 at a time (default: every core)

Test files run in parallel, one pytest process each, on every core (`-j`); the slowest files
(timed on the last run, kept in toolchain/.check-times.json) start first. Each file's line is
printed when it finishes, numbered in finishing order; in a terminal a bar under them shows the
whole stage and what's running. Exit code 0 only if every stage passed.

Mutation checks: FILE.py defines MUTATIONS = [(name, path, old, new, tests), ...]: each `old`
text (found exactly once) in `path` is replaced by `new`, `tests` (pytest arguments) must then
fail. A mutation the tests don't catch is a missing test. They run in parallel too, each worker
in its own throwaway copy of the repository (so the checkout itself is never changed).
"""

import argparse
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv" / "bin"
TTY = sys.stdout.isatty()
BAR = 30  # characters inside [ ]
NAME = 34  # the item name column
TIMES = ROOT / "toolchain" / ".check-times.json"  # seconds per test file, from the last run
JOBS = os.cpu_count() or 1
LOGS = ROOT / "toolchain" / ".check-logs"  # the full output of each file that failed


def clock(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.1f} s"
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}" if m < 60 else f"{m // 60} h {m % 60:02d} min"


@dataclass
class Stage:
    name: str
    result: str = "not run"
    ok: bool = True
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)


class Item:
    """One pacman-style line: (n/N) name  count  time  [####----] pct."""

    def __init__(self, n: int, of: int, name: str, total: int | None = None):
        self.n, self.of, self.name, self.total = n, of, name, total
        self.done, self.bad = 0, 0
        self.start = time.monotonic()
        self.status: str | None = None  # e.g. "caught" / "MISSED" instead of a count
        self.ended = False

    def line(self, final: bool = False) -> str:
        w = len(str(self.of))
        head = f"({self.n:>{w}}/{self.of}) "
        name = self.name if len(self.name) <= NAME else "…" + self.name[-(NAME - 1) :]
        if self.total:
            frac = min(1.0, self.done / self.total)
        else:
            frac = 1.0 if final else 0.0
        count = self.status or (f"{self.done}/{self.total}" if self.total else f"{self.done}")
        bar = "#" * int(frac * BAR) + "-" * (BAR - int(frac * BAR))
        mark = "" if not self.bad else f"  {self.bad} failed"
        took = clock(time.monotonic() - self.start)
        return f"{head}{name:<{NAME}} {count:>9}  {took:>7}  [{bar}] {frac:>4.0%}{mark}"

    def draw(self) -> None:
        if TTY:
            print("\r" + self.line(), end="", flush=True)

    def end(self) -> None:
        self.ended = True
        print(("\r" if TTY else "") + self.line(final=True), flush=True)


def under(text: str) -> None:
    """A note under the current item (a failure), without breaking its line in a terminal."""
    if TTY:
        print("\r" + " " * 120 + "\r", end="")
    print(f"    {text}", flush=True)


# ---- stages --------------------------------------------------------------------------------


def _load_times() -> dict[str, float]:
    try:
        return json.loads(TIMES.read_text())
    except (OSError, ValueError):
        return {}


def _collect(args: list[str]) -> tuple[dict[str, int], list[str]]:
    """Test files and how many tests each has (the progress plugin's @@file lines)."""
    r = subprocess.run([str(VENV / "pytest"), "-q", "--collect-only", "-p", "no:warnings",
                        "-p", "toolchain.pytest_progress", *args], cwd=ROOT,
                       capture_output=True, text=True)  # fmt: skip
    files = {}
    for line in r.stdout.splitlines():
        if line.startswith("@@file "):
            _, path, n = line.rsplit(" ", 2)
            files[path] = int(n)
    errors = [ln for ln in r.stdout.splitlines() if ln.startswith("ERROR")]
    return files, errors


class Board:
    """The stage's shared state while files run in parallel, and the line under them."""

    def __init__(self, total_tests: int, files: int):
        self.lock = threading.Lock()
        self.total, self.files = total_tests, files
        self.done = self.finished = 0
        self.running: dict[str, int] = {}  # file name -> tests done in it
        self.start = time.monotonic()

    def status(self) -> None:
        if not TTY:
            return
        frac = self.done / self.total if self.total else 0.0
        bar = "#" * int(frac * BAR) + "-" * (BAR - int(frac * BAR))
        names = ", ".join(sorted(self.running))
        names = names if len(names) <= 46 else names[:45] + "…"
        took = clock(time.monotonic() - self.start)
        line = f"   {self.done}/{self.total} tests  {took:>7}  [{bar}] {frac:>4.0%}  {names}"
        print("\r" + line[:150].ljust(150), end="", flush=True)

    def clear(self) -> None:
        if TTY:
            print("\r" + " " * 150 + "\r", end="", flush=True)


def run_pytest(stage: Stage, args: list[str], jobs: int = JOBS) -> None:
    files, errors = _collect(args)
    if not files:
        stage.ok, stage.result = False, "nothing ran"
        stage.failures = errors[-5:] or ["no tests collected"]
        return
    for f in files:  # this stage runs these files again: their old logs go
        (LOGS / f"{f.replace('/', '__')}.log").unlink(missing_ok=True)
    times = _load_times()
    # The slowest first, so one long file doesn't start last and hold the stage up.
    order = sorted(files, key=lambda f: (-times.get(f, 0.0), -files[f], f))
    total = sum(files.values())
    jobs = max(1, min(jobs, len(order)))
    print(f":: {stage.name} ({total} tests in {len(order)} files, {jobs} at a time)", flush=True)
    board = Board(total, len(order))
    counts: dict[str, int] = {}
    took: dict[str, float] = {}

    def one(path: str) -> None:
        name = Path(path).name
        item = Item(0, len(order), name, files[path])
        with board.lock:
            board.running[name] = 0
            board.status()
        cmd = [str(VENV / "pytest"), "-q", "-p", "no:warnings", "-p", "toolchain.pytest_progress",
               path]  # fmt: skip
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)  # fmt: skip
        failed, tail, reasons, everything = [], [], {}, []
        section = None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            everything.append(raw)
            if line.startswith("@@done "):
                _, outcome, nodeid = line.split(" ", 2)
                with board.lock:
                    item.done += 1
                    board.done += 1
                    board.running[name] = item.done
                    counts[outcome] = counts.get(outcome, 0) + 1
                    if outcome in ("failed", "error"):
                        item.bad += 1
                        failed.append((outcome, nodeid))
                    board.status()
            elif m := re.match(r"^_{3,} (?:ERROR at \w+ of )?(\S+) _{3,}$", line):
                section = m.group(1)  # a failure's report starts: its test's name
            elif line.startswith("E ") and section and section not in reasons:
                reasons[section] = line[1:].strip()  # its first error line says what went wrong
            elif line.strip() and not line.startswith("@@"):
                tail = (tail + [line])[-40:]
        proc.wait()
        with board.lock:
            board.running.pop(name, None)
            board.finished += 1
            item.n = board.finished
            took[path] = time.monotonic() - item.start
            if proc.returncode not in (0, 5) and not failed:  # e.g. it couldn't be collected
                item.bad += 1
                failed.append(("error", [ln for ln in tail if "rror" in ln][-1:] or tail[-1:]))
            board.clear()
            item.end()
            if failed:
                LOGS.mkdir(exist_ok=True)
                log = LOGS / f"{path.replace('/', '__')}.log"  # tests/ui/x.py and tests/x.py
                log.write_text("".join(everything))
                under(f"full output: {log.relative_to(ROOT)}")
            for outcome, what in failed:
                text = what if isinstance(what, str) else " ".join(what)
                why = reasons.get(text.split("::")[-1], "")
                under(
                    f"✗ {outcome}: {text.split('::', 1)[-1]}"
                    + (f"\n      {why[:200]}" if why else "")
                )
                stage.failures.append(text + (f" ({why[:120]})" if why else ""))
            board.status()

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(one, order))
    board.clear()
    try:
        TIMES.write_text(json.dumps({**times, **{k: round(v, 1) for k, v in took.items()}},
                                    indent=0, sort_keys=True))  # fmt: skip
    except OSError:
        pass
    passed = counts.get("passed", 0)
    stage.ok = not stage.failures and passed + counts.get("skipped", 0) == total
    parts = [f"{passed} passed"] + [f"{n} {k}" for k, n in counts.items() if k != "passed"]
    stage.result = ", ".join(parts) if counts else "nothing ran"
    if not stage.ok and not stage.failures:
        stage.failures = [f"{total - sum(counts.values())} tests didn't report a result"]


def single(stage: Stage, label: str, run) -> None:
    """A stage that's one item: one line, filled when it's done."""
    print(f":: {stage.name}", flush=True)
    item = Item(1, 1, label)
    item.draw()
    run(stage, item)
    item.bad = len(stage.failures)
    item.end()
    for f in stage.failures[:10]:
        under(f"✗ {f}")


def run_lint(stage: Stage) -> None:
    def go(stage, item):
        a = subprocess.run([str(VENV / "ruff"), "check", "."], cwd=ROOT, capture_output=True,
                           text=True)  # fmt: skip
        b = subprocess.run([str(VENV / "ruff"), "format", "--check", "."], cwd=ROOT,
                           capture_output=True, text=True)  # fmt: skip
        stage.ok = a.returncode == 0 and b.returncode == 0
        stage.result = "clean" if stage.ok else "problems"
        item.status = stage.result
        if not stage.ok:
            stage.failures = (a.stdout + b.stdout).strip().splitlines()[-10:]

    single(stage, "ruff check, ruff format", go)


def run_node(stage: Stage) -> None:
    def go(stage, item):
        files = sorted(str(p) for p in (ROOT / "tests/js").glob("*.test.mjs"))
        r = subprocess.run(["node", "--test", *files], cwd=ROOT, capture_output=True, text=True)
        p = re.search(r"^# pass (\d+)", r.stdout, re.M)
        f = re.search(r"^# fail (\d+)", r.stdout, re.M)
        stage.ok = r.returncode == 0
        stage.result = f"{p.group(1) if p else '?'} passed, {f.group(1) if f else '?'} failed"
        item.status = f"{p.group(1) if p else '?'} passed"
        if not stage.ok:
            stage.failures = [ln for ln in r.stdout.splitlines() if ln.startswith("not ok")][:10]

    single(stage, "node --test tests/js", go)


def tester_suites() -> list[str]:
    """The tester's suites that are switched on, in order (for the (n/N) numbering)."""
    try:
        import tomllib

        cfg = tomllib.loads((ROOT / "toolchain/tester/config.toml").read_text())
        return [k for k, v in cfg.get("suites", {}).items() if v]
    except Exception:
        return []


def run_tester(stage: Stage) -> None:
    suites = tester_suites()
    print(f":: {stage.name} ({len(suites) or '?'} suites)", flush=True)
    proc = subprocess.Popen([str(VENV / "crypto-helper"), "test"], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)  # fmt: skip
    item: Item | None = None
    n = 0
    summary = ""
    for raw in proc.stdout:
        s = raw.strip()
        m = re.match(r"^\[(\w+)\]$", s)
        if m:
            if item is not None:
                item.total = item.done or None
                item.end()
            n += 1
            item = Item(n, max(len(suites), n), m.group(1))
            item.draw()
        elif s.startswith(("PASS ", "FAIL ")) and item is not None:
            item.done += 1
            if s.startswith("FAIL"):
                item.bad += 1
                stage.failures.append(f"{item.name}: {s[5:]}")
                under(f"✗ {s[5:]}")
            item.draw()
        elif re.match(r"^\d+ passed, \d+ failed", s):
            summary = s
    proc.wait()
    if item is not None:
        item.total = item.done or None
        item.end()
    stage.ok = proc.returncode == 0
    stage.result = summary.split(" (")[0] if summary else "no summary"


COPY_SKIP = shutil.ignore_patterns(
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "screens",
    "*.egg-info",
    "reports",
)


def _workspace(base: Path, n: int) -> Path:
    """A throwaway copy of the repository for one mutation worker. Its own code must be what
    gets imported (PYTHONPATH puts it before the editable install): checked, or no mutations."""
    dest = base / f"w{n}"
    shutil.copytree(ROOT, dest, ignore=COPY_SKIP, symlinks=True)
    r = subprocess.run([str(VENV / "python"), "-c", "import app; print(app.__file__)"],
                       cwd=dest, env={**os.environ, "PYTHONPATH": str(dest)},
                       capture_output=True, text=True)  # fmt: skip
    if not r.stdout.strip().startswith(str(dest)):
        raise SystemExit(f"a copy imports the checkout's code ({r.stdout.strip()}): stopping")
    return dest


def run_mutations(stage: Stage, file: str, jobs: int = JOBS) -> None:
    mutations = runpy.run_path(file)["MUTATIONS"]
    jobs = max(1, min(jobs, len(mutations)))
    print(f":: {stage.name} ({len(mutations)} from {Path(file).name}, {jobs} at a time)",
          flush=True)  # fmt: skip
    for _name, path, *_ in mutations:
        p = (ROOT / path).resolve()
        if ROOT not in p.parents:
            raise SystemExit(f"refusing a path outside the repository: {path}")
    lock = threading.Lock()
    caught = finished = 0
    board = Board(len(mutations), len(mutations))
    with tempfile.TemporaryDirectory(prefix="crypto-helper-mutations-") as tmp:
        free = [_workspace(Path(tmp), n) for n in range(jobs)]

        def one(m) -> None:
            nonlocal caught, finished
            name, path, old, new, tests = m
            with lock:
                ws = free.pop()
                board.running[name] = 0
                board.status()
            item = Item(0, len(mutations), name, total=1)
            target = ws / path
            src = target.read_text()
            r = None
            if src.count(old) == 1:
                target.write_text(src.replace(old, new))
                try:
                    r = subprocess.run([str(VENV / "pytest"), "-q", "-x", "-p", "no:warnings",
                                        *tests.split()], cwd=ws,
                                       env={**os.environ, "PYTHONPATH": str(ws)},
                                       capture_output=True, text=True, timeout=1800)  # fmt: skip
                finally:
                    target.write_text(src)  # the copy goes back too, for the next mutation
            with lock:
                free.append(ws)
                board.running.pop(name, None)
                finished += 1
                board.done = finished
                item.n, item.done = finished, 1
                if r is None:
                    item.status, item.bad = "not found", 1
                    stage.failures.append(
                        f"{name}: the text to change is found {src.count(old)} times"
                    )
                elif r.returncode != 0:
                    caught += 1
                    item.status = "caught"
                else:
                    item.status, item.bad = "MISSED", 1
                    stage.failures.append(f"missed: {name}")
                board.clear()
                item.end()
                board.status()

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(one, mutations))
    board.clear()
    stage.ok = not stage.failures
    stage.result = f"{caught}/{len(mutations)} caught"


STAGES = {
    "lint": ("Lint", run_lint),
    "unit": ("Unit tests", lambda s: run_pytest(s, ["--ignore=tests/ui"], JOBS)),
    "ui": ("Browser tests", lambda s: run_pytest(s, ["tests/ui"], JOBS)),
    "js": ("JS tests", run_node),
    "tester": ("Tester", run_tester),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ui", action="store_true", help="also run the browser tests")
    ap.add_argument("--only", nargs="+", choices=list(STAGES), help="just these stages")
    ap.add_argument("--mutations", metavar="FILE", help="run mutation checks from FILE")
    ap.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=os.cpu_count() or 1,
        help="how many test files (or mutations) at a time (default: every core)",
    )
    args = ap.parse_args(argv)
    global JOBS
    JOBS = max(1, args.jobs)
    if args.mutations:
        names = []
    elif args.only:
        names = args.only
    else:
        names = ["lint", "unit", *(["ui"] if args.ui else []), "js", "tester"]
    names = [n for n in names if n in STAGES]  # e.g. no Node.js here: no JS stage
    stages: list[Stage] = []
    start = time.monotonic()
    plan = [(STAGES[n][0], lambda st, n=n: STAGES[n][1](st)) for n in names]
    if args.mutations:
        plan.append(("Mutations", lambda st: run_mutations(st, args.mutations, JOBS)))
    for label, fn in plan:
        st = Stage(label)
        t0 = time.monotonic()
        fn(st)
        st.seconds = time.monotonic() - t0
        print(f"   {'✓' if st.ok else '✗'} {st.result} in {clock(st.seconds)}\n", flush=True)
        stages.append(st)
    total = time.monotonic() - start
    w = max(len(s.name) for s in stages)
    r = max(len(s.result) for s in stages)
    rule = "-" * (w + r + 16)
    print(f":: Summary\n{'Stage':<{w}}  {'Result':<{r}}  {'Time':>8}\n{rule}")
    for s in stages:
        print(f"{s.name:<{w}}  {s.result:<{r}}  {clock(s.seconds):>8}  {'✓' if s.ok else '✗'}")
    print(f"{rule}\n{'Total':<{w}}  {'':<{r}}  {clock(total):>8}")
    bad = [s for s in stages if not s.ok]
    for s in bad:
        print(f"\n{s.name}: what failed")
        for f in s.failures[:20]:
            print(f"  - {f}")
    return 1 if bad else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if not shutil.which("node"):
        STAGES.pop("js")
    sys.exit(main())
