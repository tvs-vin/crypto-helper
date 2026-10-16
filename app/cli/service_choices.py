"""Optional services chosen at install time (`service install --services ...`, or asked)."""

import sys

from app.cli.common import CliError

# name -> (default for a new install, what it is)
OPTIONAL_SERVICES: dict[str, tuple[bool, str]] = {
    "backups": (True, "Daily database backups (keeps the newest 14)"),
    "agent": (
        True,
        "The agent: lets the Services window turn services on and off "
        "(a small root helper that only does a fixed list of jobs)",
    ),
    "embed": (False, "The embed server: share views of your data in Discord or on a website"),
}


def parse(value: str) -> set[str]:
    if value.strip().lower() == "none":
        return set()
    chosen = {v.strip().lower() for v in value.split(",") if v.strip()}
    unknown = chosen - set(OPTIONAL_SERVICES)
    if unknown:
        raise CliError(
            f"Unknown services: {', '.join(sorted(unknown))}. "
            f"Choose from: {', '.join(OPTIONAL_SERVICES)} (or none)."
        )
    return chosen


def ask(current: dict[str, bool]) -> set[str]:
    """Ask about each optional service, defaulting to `current`."""
    print("\nOptional services (change any of them later in the Services window or the CLI):")
    chosen = set()
    for name, (_, text) in OPTIONAL_SERVICES.items():
        default = current[name]
        answer = input(f"  {text}?\n    Turn on {name}? [{'Y/n' if default else 'y/N'}] ")
        answer = answer.strip().lower()
        if answer in ("y", "yes") or (answer == "" and default):
            chosen.add(name)
    print()
    return chosen


def choose(value: str | None, current: dict[str, bool], new_install: bool) -> set[str]:
    if value is not None:
        return parse(value)
    if new_install and sys.stdin.isatty():
        return ask(current)
    return {name for name, on in current.items() if on}
