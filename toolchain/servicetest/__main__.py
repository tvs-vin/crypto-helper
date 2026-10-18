"""Service lifecycle test: really install, break, update, roll back and remove the service.

    sudo .venv/bin/python -m toolchain.servicetest [--keep] [--replace-existing]

DESTRUCTIVE: it uses the real paths (/opt, /etc, /var/lib/crypto-helper) and finishes with
`service uninstall --purge`. Run it on a VM where the service isn't holding real data, or
pass --replace-existing to acknowledge that an existing install will be destroyed.
Docs: WIKI/tools/service-test.md
"""

import argparse
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = "/usr/local/bin/crypto-helper"
SRC = Path("/opt/crypto-helper/src")
DB = Path("/var/lib/crypto-helper/bot.db")
SITE = "/opt/crypto-helper/venv/lib"
GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


class StepFailed(Exception):
    pass


def color(text, code):
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


# Admin tools (useradd, userdel, runuser) live in sbin, which isn't always on root's PATH.
PATH = os.pathsep.join([os.environ.get("PATH", ""), "/usr/local/sbin", "/usr/sbin", "/sbin"])


def sh(*cmd, check=True, env=None, input=None) -> subprocess.CompletedProcess:
    r = subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": PATH, **(env or {})},
        input=input,
    )
    if check and r.returncode != 0:
        raise StepFailed(
            f"`{' '.join(map(str, cmd))}` exited {r.returncode}:\n{(r.stdout + r.stderr)[-2000:]}"
        )
    return r


def expect(cond, msg):
    if not cond:
        raise StepFailed(msg)


def db_state() -> tuple[str, set[str], list[str]]:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rev = c.execute("select version_num from alembic_version").fetchone()[0]
        tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        users = [r[0] for r in c.execute("select username from users order by id")]
    finally:
        c.close()
    return rev, tables, users


def installed_commit() -> str:
    return sh("git", "-C", SRC, "rev-parse", "HEAD").stdout.strip()


def healthy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/setup/status", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def make_release(base: Path, workdir: Path, name: str, *, broken: bool) -> tuple[Path, str]:
    """A throwaway 'origin' repo with one extra commit on top of the installed version."""
    repo = workdir / name
    branch = sh("git", "-C", SRC, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    sh("git", "clone", "-q", "--branch", branch, base, repo)
    sh("git", "-C", repo, "config", "user.email", "servicetest@localhost")
    sh("git", "-C", repo, "config", "user.name", "servicetest")
    if broken:
        # The worst case: a schema migration *and* a server that dies on start.
        (repo / "app/migrations/versions/9999_servicetest_broken.py").write_text(
            '"""servicetest: deliberately broken release"""\n'
            "import sqlalchemy as sa\nfrom alembic import op\n\n"
            f"revision = '9999'\ndown_revision = {head_revision(repo)!r}\n"
            "branch_labels = None\ndepends_on = None\n\n\n"
            "def upgrade():\n"
            "    op.create_table('servicetest_canary', sa.Column('id', sa.Integer(), "
            "primary_key=True))\n\n\n"
            "def downgrade():\n    op.drop_table('servicetest_canary')\n"
        )
        main_py = repo / "app/main.py"
        text = main_py.read_text()
        marker = "        migrate.upgrade(engine)\n"
        expect(marker in text, "can't find the startup hook to break in app/main.py")
        main_py.write_text(
            text.replace(
                marker, marker + "        raise RuntimeError('servicetest: broken release')\n", 1
            )
        )
    else:
        (repo / "SERVICETEST.txt").write_text("a harmless change\n")
    sh("git", "-C", repo, "add", "-A")
    sh("git", "-C", repo, "commit", "-q", "-m", f"servicetest {name}")
    return repo, sh("git", "-C", repo, "rev-parse", "HEAD").stdout.strip()


def head_revision(repo: Path) -> str:
    versions = sorted(p.stem.split("_")[0] for p in (repo / "app/migrations/versions").glob("*.py"))
    return versions[-1]


# ---- the steps ---------------------------------------------------------------------------


class Run:
    def __init__(self, keep: bool):
        self.keep = keep
        self.work = Path(tempfile.mkdtemp(prefix="servicetest-"))
        self.password = secrets.token_urlsafe(24)  # never printed
        self.origin = None

    def install(self):
        r = sh(REPO / "install.sh")
        expect("Crypto Helper is running" in r.stdout, "install.sh didn't report success")
        expect(healthy(), "service doesn't answer after install")

    def doctor(self):
        r = sh(CLI, "doctor", check=False)
        expect(r.returncode == 0, f"doctor reported problems:\n{r.stdout}")
        expect("sandbox exposure score" in r.stdout, "doctor didn't score the sandbox")

    def setup_super(self):
        token = sh(CLI, "setup", "token").stdout.strip()
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/setup",
            method="POST",
            data=f'{{"token": "{token}", "password": "{self.password}"}}'.encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "fetch"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            expect(r.status == 201, f"setup returned {r.status}")
        expect(
            sh(CLI, "setup", "token", check=False).returncode == 1,
            "setup token still available after setup",
        )

    def live_tester(self):
        r = sh(
            CLI, "test", "--target", "live", env={"BOT_TESTER_PASSWORD": self.password}, check=False
        )
        last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr
        expect(r.returncode == 0, f"live tester failed: {last}")
        return last

    def backup_job(self):
        sh("systemctl", "start", "crypto-helper-backup.service")
        files = list(Path("/var/lib/crypto-helper/backups").glob("bot-*.db"))
        expect(files, "the backup job wrote no backup")
        expect(all(f.stat().st_mode & 0o077 == 0 for f in files), "a backup is not private")

    def privilege_drop(self):
        sh(CLI, "account", "super", "sessions", "revoke")
        stray = sh("find", "/var/lib/crypto-helper", "-user", "root").stdout.split()
        expect(not stray, f"root-owned files in the data folder: {stray}")

    def normal_user_gets_sudo(self):
        """A non-root user runs commands that need root: they ask sudo, then work. Uses two
        throwaway users (one with a passwordless sudo rule) that are removed right after."""
        rule = Path("/etc/sudoers.d/zz-crypto-helper-servicetest")
        users = ("chst_sudo", "chst_nosudo")
        try:
            for u in users:
                sh("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", u)
            rule.write_text("chst_sudo ALL=(root) NOPASSWD: ALL\n")
            rule.chmod(0o440)
            sh("visudo", "-cq", "-f", rule)
            for argv in (["service", "status"], ["account", "list"], ["doctor"]):
                r = sh("runuser", "-u", "chst_sudo", "--", CLI, *argv, check=False)
                expect("asking sudo" in r.stderr, f"{argv} didn't ask for sudo:\n{r.stderr}")
                expect("Traceback" not in r.stdout + r.stderr, f"{argv} crashed:\n{r.stderr}")
                expect(r.returncode in (0, 1), f"{argv} exited {r.returncode}")
            r = sh("runuser", "-u", "chst_nosudo", "--", CLI, "service", "restart", check=False)
            expect(r.returncode != 0 and "sudo" in r.stderr, "no-sudo user wasn't refused")
            r = sh("runuser", "-u", "chst_sudo", "--", "timeout", "5", CLI, "serve", check=False)
            expect(
                "asking sudo" not in r.stderr and "Traceback" not in r.stderr,
                f"serve misbehaved for a normal user:\n{r.stderr}",
            )
        finally:
            rule.unlink(missing_ok=True)
            for u in users:
                sh("userdel", u, check=False)
        return "asks sudo; serve never does"

    def broken_update(self):
        before_commit, (before_rev, before_tables, before_users) = installed_commit(), db_state()
        repo, bad = make_release(SRC, self.work, "broken", broken=True)
        self._point_origin(repo)
        r = sh(CLI, "update", "--yes", check=False)
        expect(r.returncode == 1, f"update of a broken release didn't fail (exit {r.returncode})")
        expect("Rolled back" in r.stdout + r.stderr, "update didn't report a rollback")
        expect(installed_commit() == before_commit, "code wasn't rolled back")
        rev, tables, users = db_state()
        expect(rev == before_rev, f"database left at revision {rev}, expected {before_rev}")
        expect("servicetest_canary" not in tables, "broken migration's table survived rollback")
        expect(tables == before_tables, f"tables changed: {sorted(tables ^ before_tables)}")
        expect(users == before_users, "accounts changed during rollback")
        stray = sh("find", SITE, "-name", "9999_*").stdout.split()
        expect(not stray, f"files from the broken release survived: {stray}")
        unreadable = sh(
            "find", f"{SITE}", "-path", "*site-packages/app*", "!", "-perm", "-o+r"
        ).stdout.split()
        expect(not unreadable, f"installed code isn't readable by the service: {unreadable[:3]}")
        expect(healthy(), "service isn't healthy after rollback")
        return f"rolled back from {bad[:7]} to {before_commit[:7]}"

    def good_update(self):
        repo, good = make_release(SRC, self.work, "good", broken=False)
        self._point_origin(repo)
        r = sh(CLI, "update", "--yes")
        expect(installed_commit() == good, "update didn't install the new commit")
        expect("Running and healthy" in r.stdout, "update didn't confirm health")
        return f"updated to {good[:7]}"

    def reinstall_keeps_data(self):
        sh(CLI, "service", "uninstall", "--yes")
        expect(not healthy(), "service still answers after uninstall")
        expect(DB.exists(), "uninstall (without --purge) deleted the database")
        sh(CLI, "service", "install")
        expect(db_state()[2] == ["super"], "accounts lost across uninstall/reinstall")

    def purge(self):
        r = sh(CLI, "service", "uninstall", "--purge", "--yes")
        for p in ("/opt/crypto-helper", "/etc/crypto-helper", "/var/lib/crypto-helper", CLI):
            expect(not Path(p).exists(), f"{p} survived --purge")
        expect(sh("id", "crypto-helper", check=False).returncode != 0, "service user survived")
        saved = [
            ln.split(" in ", 1)[1].split(" ")[0]
            for ln in r.stdout.splitlines()
            if "final copy" in ln
        ]
        expect(saved and Path(saved[0], "bot.db").exists(), "purge kept no final copy")
        shutil.rmtree(saved[0])

    def _point_origin(self, repo: Path):
        if self.origin is None:
            self.origin = sh("git", "-C", SRC, "remote", "get-url", "origin").stdout.strip()
        sh("git", "-C", SRC, "remote", "set-url", "origin", repo)

    def restore_origin(self):
        if self.origin and SRC.exists():
            sh("git", "-C", SRC, "remote", "set-url", "origin", self.origin, check=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m toolchain.servicetest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--keep",
        action="store_true",
        help="stop before the final purge and leave the service installed",
    )
    ap.add_argument(
        "--replace-existing",
        action="store_true",
        help="allow destroying an existing install (its data is lost)",
    )
    args = ap.parse_args(argv)

    if os.geteuid() != 0:
        print("Needs root: sudo .venv/bin/python -m toolchain.servicetest")
        return 2
    if not Path("/run/systemd/system").exists():
        print("Needs a machine running systemd.")
        return 2
    if Path("/etc/crypto-helper").exists() or Path("/opt/crypto-helper").exists():
        if not args.replace_existing:
            print(
                "An install already exists. This test DESTROYS it (data included).\n"
                "Re-run with --replace-existing if that's what you want."
            )
            return 2
        print(color("Removing the existing install first...", DIM))
        if Path(CLI).exists():
            sh(CLI, "service", "uninstall", "--purge", "--yes", check=False)
        for p in ("/opt/crypto-helper", "/etc/crypto-helper", "/var/lib/crypto-helper"):
            shutil.rmtree(p, ignore_errors=True)
        sh("userdel", "crypto-helper", check=False)
    dirty = sh("git", "-C", REPO, "status", "--porcelain", "--untracked-files=no").stdout
    if dirty:
        print(
            color("Note: uncommitted changes are NOT tested; install.sh uses the last commit.", DIM)
        )

    run = Run(args.keep)
    steps = [
        ("install.sh installs and starts the service", run.install),
        ("doctor finds no problems", run.doctor),
        ("create super with the setup token", run.setup_super),
        ("live end-to-end tester passes", run.live_tester),
        ("daily backup job writes a private backup", run.backup_job),
        ("root account commands leave no root-owned files", run.privilege_drop),
        ("a normal user is asked for sudo (temporary users)", run.normal_user_gets_sudo),
        ("broken release: update fails and rolls back code + data", run.broken_update),
        ("tester still passes after the rollback", run.live_tester),
        ("good release: update installs it", run.good_update),
        ("uninstall + reinstall keeps the data", run.reinstall_keeps_data),
    ]
    if not args.keep:
        steps.append(("uninstall --purge removes everything", run.purge))

    failed = 0
    started = time.monotonic()
    try:
        for title, fn in steps:
            t = time.monotonic()
            try:
                note = fn()
                extra = f" {color(f'({note})', DIM)}" if note else ""
                print(
                    f"  {color('PASS', GREEN)} {title}{extra} "
                    f"{color(f'{time.monotonic() - t:.0f}s', DIM)}",
                    flush=True,
                )
            except StepFailed as e:
                failed += 1
                print(
                    f"  {color('FAIL', RED)} {title}\n       " + str(e).replace("\n", "\n       "),
                    flush=True,
                )
                break  # later steps depend on earlier ones
    finally:
        run.restore_origin()
        shutil.rmtree(run.work, ignore_errors=True)
    total = time.monotonic() - started
    summary = f"{'FAILED' if failed else 'All steps passed'} in {total:.0f}s"
    print("\n" + color(summary, RED if failed else GREEN))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
