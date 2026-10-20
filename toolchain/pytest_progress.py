"""A pytest plugin for toolchain/checks.py: one machine-readable line per finished test, so the
runner can draw a progress bar. Load with `-p toolchain.pytest_progress`."""

import sys


def pytest_collection_finish(session):
    files: dict[str, int] = {}
    for item in session.items:
        path = item.nodeid.split("::")[0]
        files[path] = files.get(path, 0) + 1
    for path, n in files.items():  # in run order: one line (and bar) per file
        print(f"\n@@file {path} {n}", flush=True)
    print(f"\n@@total {len(session.items)}", flush=True)


def pytest_runtest_logreport(report):
    # One line per test: its "call" phase, or the phase that failed or skipped it before that.
    if report.when == "call" or (report.when == "setup" and not report.passed):
        outcome = "skipped" if report.skipped else report.outcome
        print(f"\n@@done {outcome} {report.nodeid}", flush=True)
    elif report.when == "teardown" and report.failed:
        print(f"\n@@done error {report.nodeid}", flush=True)
    sys.stdout.flush()
