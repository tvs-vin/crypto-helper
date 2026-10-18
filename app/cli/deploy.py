"""Install the code of one exact git commit into the venv. Used by update and rollback.

Two lessons from testing a broken update on a real install:
- Build from a clean `git archive` of the commit, never from the checkout itself:
  setuptools leaves a gitignored build/ folder there, and a later rebuild silently
  packaged a leftover migration from a different version.
- Install with umask 022: the code must be readable by the service user. The CLI's own
  private umask (077) leaked into pip once and the service couldn't import itself.
"""

import tempfile
from pathlib import Path

from app.cli.common import CliError, run
from app.cli.layout import Layout

CODE_UMASK = 0o022


def install_commit(layout: Layout, commit: str) -> None:
    with tempfile.TemporaryDirectory(prefix="crypto-helper-build-") as tmp:
        tarball = Path(tmp) / "src.tar"
        tree = Path(tmp) / "tree"
        tree.mkdir()
        run(["git", "-C", str(layout.src), "archive", "--format=tar", "-o", str(tarball), commit])
        run(["tar", "-xf", str(tarball), "-C", str(tree)], umask=CODE_UMASK)
        run(
            [
                str(layout.venv / "bin" / "pip"),
                "install",
                "--quiet",
                "--no-cache-dir",
                "--force-reinstall",
                "--no-deps",
                str(tree),
            ],
            umask=CODE_UMASK,
        )
        # Dependencies may change between versions: install anything new or missing, at the
        # exact versions this commit was tested with (its requirements.txt).
        pins = tree / "requirements.txt"
        run(
            [str(layout.venv / "bin" / "pip"), "install", "--quiet",
             *(["-c", str(pins)] if pins.exists() else []), str(tree)],
            umask=CODE_UMASK,
        )  # fmt: skip


def preflight(layout: Layout) -> None:
    """Prove the service user can load the installed code before we rely on it."""
    result = run([str(layout.executable), "version"], user=layout.user, check=False)
    if result.returncode != 0:
        raise CliError(
            "the service user can't run the installed code: "
            + (result.stderr or result.stdout).strip().splitlines()[-1]
        )
