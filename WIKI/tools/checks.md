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
```

What it looks like:

```
:: Unit tests (1073 tests in 74 files)
( 1/74) test_account_rules.py                  7/7    3.1 s  [##############################] 100%
( 2/74) test_agent.py                        19/19    8.4 s  [##############################] 100%
( 3/74) test_alerts.py                         4/9    1.2 s  [#############-----------------]  44%
    ✗ failed: test_who_may_have_which_alert
   ✓ 1073 passed in 9:01

:: Summary
Stage          Result                    Time
---------------------------------------------
Lint           clean                    0.1 s  ✓
Unit tests     1073 passed               9:01  ✓
...
```

In a terminal the current line fills in place; in a log each line is printed when its item is
done. The exit code is 0 only if every stage passed, and the stages that didn't are listed with
what failed.

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

Each file is always put back, even if the run is interrupted mid-test; a path outside the
repository is refused. Never point a mutation at code that could then touch real system files
(tests run as root on the VM).

The pytest progress comes from a small plugin, `toolchain/pytest_progress.py`
(`-p toolchain.pytest_progress`): one line per finished test.
