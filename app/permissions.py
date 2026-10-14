"""The permission catalog. Add new permissions here and nowhere else."""

PERMISSIONS: dict[str, str] = {
    "wallets.view": "See wallets, balances and transfer history",
    "wallets.edit": "Create, edit and delete wallets and set balances",
    "prices.view": "See the currency overview",
    "transfers.create": "Create (simulated) transfers",
    "audit.view": "Read the audit log",
    "users.manage": "Manage users",
}

ALL_PERMISSIONS: frozenset[str] = frozenset(PERMISSIONS)

# Presets only fill the form in the UI; users store an explicit permission list.
PRESETS: dict[str, list[str]] = {
    "viewer": ["wallets.view", "prices.view"],
    "trader": ["wallets.view", "prices.view", "wallets.edit", "transfers.create"],
    "admin": [
        "wallets.view",
        "prices.view",
        "wallets.edit",
        "transfers.create",
        "audit.view",
        "users.manage",
    ],
}

SUPER_USERNAME = "super"
