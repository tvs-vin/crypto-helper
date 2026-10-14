---
title: Service test
---

# Service test

`toolchain/servicetest` really installs the service on the machine, breaks it, updates
it, rolls it back and removes it, checking every step. It's how the install, update and
rollback code is verified; the unit tests can only check the pieces.

> **Destructive.** It uses the real paths and ends with `service uninstall --purge`. Run it
> on a VM where the service doesn't hold real data.

```bash
sudo .venv/bin/python -m toolchain.servicetest                     # refuses if installed
sudo .venv/bin/python -m toolchain.servicetest --replace-existing  # destroy an existing install first
sudo .venv/bin/python -m toolchain.servicetest --keep              # leave it installed at the end
```
It installs the **last commit** of the checkout, not uncommitted changes.

## Steps
| # | Step | Proves |
|---|---|---|
| 1 | `install.sh` | Clean install starts and answers |
| 2 | `doctor` | No problems; sandbox is scored |
| 3 | Setup | Token works once, then is gone. The `super` password is random and never printed. |
| 4 | Live [tester]({{ site.baseurl }}/tools/tester) | All end-to-end checks against the installed service |
| 5 | Backup job | The systemd backup job writes a private file |
| 6 | Privilege drop | `sudo crypto-helper account …` leaves no root-owned files |
| 7 | Broken release | A release that adds a migration *and* crashes on start: `update` fails, then code, database, tables and accounts are exactly as before, no stray files, code readable |
| 8 | Tester again | Everything still works after the rollback |
| 9 | Good release | `update` installs a normal new commit |
| 10 | Uninstall + reinstall | Data survives |
| 11 | Purge | Everything is gone, the user too; a final copy was saved |

Releases in steps 7 and 9 are made in a throwaway local git repo. The install's `origin` is
pointed at it for the test and restored afterwards.

## Bugs it caught while being written
- The CLI's private umask leaked into `pip`, so the service couldn't read its own code
  after an update. Fixed: code is installed with umask 022, and a pre-flight check runs
  the new code as the service user before starting it.
- A rollback rebuilt from the checkout, whose leftover `build/` folder still held a
  migration from the broken release. Fixed: every install builds from a clean `git archive`.
- `useradd`/`runuser` weren't found because `/usr/sbin` wasn't on the PATH. Fixed.
- `crypto-helper test --target live` didn't pass `--target` through. Fixed.

Last run: all 11 steps passed in about 4 minutes.
