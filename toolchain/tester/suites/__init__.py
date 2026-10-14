# Importing a suite module registers its checks. Add new suite modules to this list
# and give them a switch under [suites] in config.toml.
from toolchain.tester.suites import (  # noqa: F401
    audit,
    auth,
    health,
    lockout,
    twofa,
    users,
    wallets,
)

ALL_SUITES = ["health", "auth", "lockout", "users", "audit", "twofa", "wallets"]
