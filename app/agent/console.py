"""The Console's commands. Ids map to fixed argument lists; nothing typed by a person is ever
passed to the command line (the only variable is a validated number of log lines)."""

# id -> (arguments after `crypto-helper`, what it does)
COMMANDS: dict[str, tuple[list[str], str]] = {
    "status": (["service", "status"], "Is everything running? Last and next backup."),
    "doctor": (["doctor"], "Check the whole setup and suggest fixes."),
    "logs": (["service", "logs", "-n", "{lines}"], "The latest log lines."),
    "version": (["version"], "Installed version, branch and commit."),
    "update-check": (["update", "--check"], "Is a newer version available? (Doesn't install.)"),
    "prices": (["prices", "check"], "Ask the price source for live prices."),
    "embed": (["embed", "status"], "Embed server: on or off, where, which address links use."),
    "agent": (["agent", "status"], "The agent, and the services as it sees them."),
    "config": (["config", "show"], "The settings in use (secrets hidden)."),
    "backup": (["db", "backup"], "Make a database backup now."),
}
MAX_OUTPUT = 256 * 1024
TIMEOUT_SECONDS = 120


def argv(command: str, lines: int | None) -> list[str]:
    args, _ = COMMANDS[command]
    n = str(max(20, min(lines or 200, 1000)))
    return [a.replace("{lines}", n) for a in args]
