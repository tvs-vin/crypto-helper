---
title: Check runner
---

# Check runner

Runs the project's checks with progress you can follow, laid out like Arch Linux's `pacman`: a
`::` header per stage, then one line with its own bar per item (a test file, a tester suite, a
mutation), failures right under the item they belong to, and a summary with each stage's time.

```bash
.venv/bin/python -m toolchain.checks                  # lint, unit tests, JS tests, tester
.venv/bin/python -m toolchain.checks --ui             # ...and the browser tests
.venv/bin/python -m toolchain.checks --only unit ui   # some stages: lint unit ui js tester
.venv/bin/python -m toolchain.checks --mutations FILE.py
.venv/bin/python -m toolchain.checks -j 4             # 4 at a time (default: every core)
```

What it looks like:

```
:: Unit tests (1126 tests in 54 files, 8 at a time)
( 1/54) test_permissions.py                      3/3    7.1 s  [##############################] 100%
( 2/54) test_agent.py                          31/31     21 s  [##############################] 100%
( 3/54) test_alerts.py                           8/9     12 s  [##############################] 100%  1 failed
    ✗ failed: test_who_may_have_which_alert
      AssertionError: assert 200 == 403
   612/1126 tests     1:41  [################--------------]  54%  test_settings.py, test_shell.py, …
```

## Running in parallel
Test files (and mutations) run **side by side on every core** (`-j N` to choose; `-j 1` runs
one at a time). Each test file gets its own `pytest` process, so files can't affect each other;
each test already has its own temporary folders and free ports. The slowest files start first
(their times from the last run are kept in `toolchain/.check-times.json`, not in git), so one
long file doesn't end up running alone at the end. On the 8-core VM the unit tests take about
3½ minutes instead of 10, and the browser tests about 2 instead of 8.

A file's line is printed **when it finishes**, numbered in finishing order, with its own time
and any failures (and pytest's one-line reason) under it. In a terminal, the line under them
shows the whole stage: tests done, time, a bar, and which files are running now. In a log
(not a terminal) only the finished lines are printed. The exit code is 0 only if every stage
passed, and the stages that didn't are listed with what failed.

| Stage | Runs | One line per |
|---|---|---|
| Lint | `ruff check .` and `ruff format --check .` | (one) |
| Unit tests | `pytest --ignore=tests/ui` | test file |
| Browser tests (`--ui`) | `pytest tests/ui` ([Browser tests]({{ site.baseurl }}/tools/ui-tests)) | test file |
| JS tests | `node --test tests/js/*.test.mjs` (skipped without Node.js) | (one) |
| Tester | `crypto-helper test` ([End-to-end tester]({{ site.baseurl }}/tools/tester)) | suite |
| Mutations | see below | mutation |

## Mutation checks
A mutation check breaks one guard on purpose and expects the tests to notice; a mutation they
don't catch means a missing test. `FILE.py` lists them:

```python
MUTATIONS = [
    # (name, file, text to replace (found exactly once), replacement, pytest arguments)
    (
        "0.0.0.0 allowed",
        "app/netconfig.py",
        "        if ip.is_unspecified:",
        "        if False:",
        "tests/test_netconfig.py",
    ),
]
```

Mutations run in parallel too: each worker has its own **throwaway copy of the repository**
(in a temporary folder, removed afterwards), changes the file there, and runs the tests there
(`PYTHONPATH` points at the copy; the runner checks that the copy's code is what gets imported
before it starts). The checkout itself is never changed. A path outside the repository is
refused.

A mutation counts as **caught** only when the tests run and fail (or the change stops them
being collected). If pytest can't run the given tests at all (a wrong path, no tests found),
the mutation is shown as **bad tests** and fails the stage: it proves nothing. Never point a mutation at code that could then touch real system files
(tests run as root on the VM).

The pytest progress comes from a small plugin, `toolchain/pytest_progress.py`
(`-p toolchain.pytest_progress`): one line per finished test.
