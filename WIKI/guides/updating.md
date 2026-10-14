---
title: Updating
---

# Updating

```bash
sudo crypto-helper update --check   # what's new? (changes nothing)
sudo crypto-helper update           # install it
```

## What `update` does
1. Fetches the branch the install follows (e.g. `dev`) from GitHub.
2. Refuses if the new history isn't a straight continuation of what's installed
   (someone rewrote history), or if `/opt/crypto-helper/src` has local edits.
3. Shows the new commits and asks before going on (`--yes` skips the question).
4. **Backs up the database** to `/var/lib/crypto-helper/backups/pre-update-<old>-<time>.db`.
5. Stops the service, installs the new code from a clean copy of that exact commit, checks
   the service user can run it, applies migrations, and starts it again.
6. Waits up to 30 seconds for it to answer.

## If something goes wrong, it rolls back by itself
If any part of step 5 or 6 fails, `update`:
- puts the previous code back (exactly, from git),
- puts the database backup from step 4 back (undoing any migration the new version ran),
- starts the old version and checks it answers,
- tells you what failed and shows the last log lines.

You end up where you were before the update. This was tested by pushing a release that
both migrates the database and crashes on start: see [Service test]({{ site.baseurl }}/tools/service-test).

The newest 5 pre-update backups are kept; older ones are removed after a successful update.

## Following a different branch
The install follows whichever branch was checked out when you ran `install.sh`. To switch,
on the VM:
```bash
sudo git -C /opt/crypto-helper/src fetch origin main
sudo git -C /opt/crypto-helper/src checkout main
sudo crypto-helper update
```
