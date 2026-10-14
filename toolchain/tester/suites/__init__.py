# Importing a suite module registers its checks. Add new suite modules to this list
# and give them a switch under [suites] in config.toml.
from toolchain.tester.suites import audit, auth, health, lockout, twofa, users  # noqa: F401

ALL_SUITES = ["health", "auth", "lockout", "users", "audit", "twofa"]
