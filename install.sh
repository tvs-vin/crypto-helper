#!/usr/bin/env bash
# Install Crypto Helper as a systemd service.
#
#   sudo ./install.sh              # from a git checkout of this repo
#   sudo ./install.sh --port 8001  # extra options go to `crypto-helper service install`
#
# What it does: clones this checkout into /opt/crypto-helper/src, builds a venv in
# /opt/crypto-helper/venv, links /usr/local/bin/crypto-helper, then runs
# `crypto-helper service install` (service user, config, key, systemd units, start).
# Safe to run again. Upgrades afterwards: sudo crypto-helper update
set -euo pipefail
# The installed code must be readable by the service user, whatever root's umask is.
umask 022

NAME=crypto-helper
PREFIX=/opt/$NAME
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=${PYTHON:-python3}

say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "needs root: sudo ./install.sh"
[[ -d /run/systemd/system ]] || die "systemd isn't running on this machine"
command -v git >/dev/null || die "git is required (apt install git)"
command -v "$PY" >/dev/null || die "python3 is required (apt install python3)"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 12))' \
  || die "Python 3.12 or newer is required (found $("$PY" -V))"
"$PY" -c 'import ensurepip, venv' 2>/dev/null \
  || die "the venv module is missing (apt install python3-venv)"
git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1 || die "run this from a git checkout"

BRANCH=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)
COMMIT=$(git -C "$REPO_DIR" rev-parse --short HEAD)
if [[ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]]; then
  echo "warning: $REPO_DIR has uncommitted changes. Only committed code ($COMMIT) is installed."
fi

install -d -m 755 "$PREFIX"
if [[ -d $PREFIX/src/.git ]]; then
  say "Existing install found in $PREFIX (upgrade code with: sudo $NAME update)"
else
  say "Copying $BRANCH @ $COMMIT to $PREFIX/src"
  git clone --quiet --branch "$BRANCH" "$REPO_DIR" "$PREFIX/src"
  # Point updates at the same place this checkout pulls from (e.g. GitHub).
  if ORIGIN=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null); then
    git -C "$PREFIX/src" remote set-url origin "$ORIGIN"
  fi
fi

if [[ ! -x $PREFIX/venv/bin/python ]]; then
  say "Creating the Python environment in $PREFIX/venv"
  "$PY" -m venv "$PREFIX/venv"
fi
say "Installing Python packages (this takes a minute the first time)"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
# Build from a clean export of the commit, never the checkout itself (a leftover build/
# folder there can sneak stale files into the package).
BUILD=$(mktemp -d)
git -C "$PREFIX/src" archive HEAD | tar -x -C "$BUILD"
"$PREFIX/venv/bin/pip" install --quiet --no-cache-dir "$BUILD"
rm -rf "$BUILD"

ln -sfn "$PREFIX/venv/bin/$NAME" "/usr/local/bin/$NAME"
say "Linked /usr/local/bin/$NAME"

exec "/usr/local/bin/$NAME" service install "$@"
