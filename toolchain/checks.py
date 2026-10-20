"""Run the project's checks with progress you can follow, laid out like pacman: a `::` header
per stage, then one line with its own bar per item (a test file, a tester suite, a mutation),
failures right under the item they belong to, and a summary table with times at the end.

    .venv/bin/python -m toolchain.checks                 # lint, unit, JS, tester
    .venv/bin/python -m toolchain.checks --ui            # ...and the browser tests
    .venv/bin/python -m toolchain.checks --only unit ui  # some stages
    .venv/bin/python -m toolchain.checks --mutations FILE.py   # mutation checks (see below)

In a terminal the current line fills in place; in a log (not a terminal) each line is printed
once its item is done. Exit code 0 only if every stage passed.

Mutation checks: FILE.py defines MUTATIONS = [(name, path, old, new, tests), ...]: each `old`
text (found exactly once) in `path` is replaced by `new`, `tests` (pytest arguments) must then
fail, and the file is always put back. A mutation the tests don't catch is a missing test.
"""

import argparse
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv" / "bin"
TTY = sys.stdout.isatty()
BAR = 30  # characters inside [ ]
NAME = 34  # the item name column


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


def run_pytest(stage: Stage, args: list[str]) -> None:
    cmd = [str(VENV / "pytest"), "-q", "-p", "no:warnings", "-p", "toolchain.pytest_progress",
           *args]  # fmt: skip
    files: dict[str, int] = {}
    order: list[str] = []
    item: Item | None = None
    counts: dict[str, int] = {}
    tail: list[str] = []
    mark = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)  # fmt: skip
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.startswith("@@file "):
            _, path, n = line.rsplit(" ", 2) if line.count(" ") >= 2 else (None, None, 0)
            files[path] = int(n)
            order.append(path)
        elif line.startswith("@@total "):
            print(f":: {stage.name} ({line.split()[1]} tests in {len(order)} files)", flush=True)
            mark = time.monotonic()  # a file's time runs from the end of the one before
        elif line.startswith("@@done "):
            _, outcome, nodeid = line.split(" ", 2)
            path = nodeid.split("::")[0]
            if item is None or item.name != Path(path).name:
                if item is not None and not item.ended:
                    item.end()
                    mark = time.monotonic()
                idx = order.index(path) + 1 if path in order else 0
                item = Item(idx, len(order), Path(path).name, files.get(path))
                item.start = mark  # from the end of the file before (setup counts too)
            item.done += 1
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome in ("failed", "error"):
                item.bad += 1
                stage.failures.append(nodeid)
                under(f"✗ {outcome}: {nodeid.split('::', 1)[-1]}")
            item.draw()
            if item.total and item.done >= item.total:  # its last test: the line is final
                item.end()
                mark = time.monotonic()
        elif line.strip():
            tail = (tail + [line])[-40:]
    proc.wait()
    if item is not None and not item.ended:
        item.end()
    passed = counts.get("passed", 0)
    stage.ok = proc.returncode == 0
    parts = [f"{passed} passed"] + [f"{n} {k}" for k, n in counts.items() if k != "passed"]
    stage.result = ", ".join(parts) if counts else "nothing ran"
    if not stage.ok and not stage.failures:
        stage.failures = [ln for ln in tail if "rror" in ln][-5:] or tail[-5:]


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


def run_mutations(stage: Stage, file: str) -> None:
    mutations = runpy.run_path(file)["MUTATIONS"]
    print(f":: {stage.name} ({len(mutations)} from {Path(file).name})", flush=True)
    caught = 0
    for i, (name, path, old, new, tests) in enumerate(mutations, 1):
        item = Item(i, len(mutations), name, total=1)
        item.draw()
        p = (ROOT / path).resolve()
        if ROOT not in p.parents:
            raise SystemExit(f"refusing a path outside the repository: {path}")
        src = p.read_text()
        if src.count(old) != 1:
            item.status, item.bad = "not found", 1
            item.done = 1
            item.end()
            stage.failures.append(f"{name}: the text to change is found {src.count(old)} times")
            continue
        p.write_text(src.replace(old, new))
        try:
            r = subprocess.run([str(VENV / "pytest"), "-q", "-x", "-p", "no:warnings",
                                *tests.split()], cwd=ROOT, capture_output=True, text=True,
                               timeout=1800)  # fmt: skip
        finally:
            p.write_text(src)  # always put the file back
        item.done = 1
        if r.returncode != 0:
            caught += 1
            item.status = "caught"
        else:
            item.status, item.bad = "MISSED", 1
            stage.failures.append(f"missed: {name}")
        item.end()
    stage.ok = not stage.failures
    stage.result = f"{caught}/{len(mutations)} caught"


STAGES = {
    "lint": ("Lint", run_lint),
    "unit": ("Unit tests", lambda s: run_pytest(s, ["--ignore=tests/ui"])),
    "ui": ("Browser tests", lambda s: run_pytest(s, ["tests/ui"])),
    "js": ("JS tests", run_node),
    "tester": ("Tester", run_tester),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ui", action="store_true", help="also run the browser tests")
    ap.add_argument("--only", nargs="+", choices=list(STAGES), help="just these stages")
    ap.add_argument("--mutations", metavar="FILE", help="run mutation checks from FILE")
    args = ap.parse_args(argv)
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
        plan.append(("Mutations", lambda st: run_mutations(st, args.mutations)))
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
