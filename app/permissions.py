"""The permission catalog. Add new permissions here and nowhere else."""

PERMISSIONS: dict[str, str] = {
    "wallets.view": "See wallets, balances and transfer history",
    "wallets.edit": "Create, edit and delete wallets and set balances",
    "wallets.connect": "Add read-only exchange keys and addresses, and link wallets to them",
    "prices.view": "See the currency overview",
    "prices.manage": "Add or remove extra coins; change price and balance history settings",
    "themes.publish": "Publish an uploaded theme so everyone can use it",
    "embeds.create": "Create embed links that show wallet or price data outside the app",
    "transfers.create": "Create (simulated) transfers",
    "audit.view": "Read the audit log",
    "users.manage": "Manage users",
    "apps.manage": "Choose which apps each account can use, and turn apps off for everyone",
    "services.manage": "Turn services and features on and off; run the self-test",
    "notifications.send": "Send notifications to one user or everyone",
    "console.use": "Run the Console's fixed crypto-helper commands (status, doctor, logs...)",
    "terminal.use": "Open a Terminal: the VM's own login prompt (only super can grant this)",
}

ALL_PERMISSIONS: frozenset[str] = frozenset(PERMISSIONS)
# Only super may hand these out, even to someone who holds them and manages users.
SUPER_GRANTS_ONLY: frozenset[str] = frozenset({"terminal.use"})

# Presets only fill the form in the UI; users store an explicit permission list.
PRESETS: dict[str, list[str]] = {
    "viewer": ["wallets.view", "prices.view"],
    "trader": ["wallets.view", "prices.view", "wallets.edit", "transfers.create"],
    "admin": [
        "wallets.view",
        "prices.view",
        "wallets.edit",
        "wallets.connect",
        "transfers.create",
        "audit.view",
        "users.manage",
        "prices.manage",
        "themes.publish",
        "embeds.create",
        "apps.manage",
        "notifications.send",
    ],
}

SUPER_USERNAME = "super"
# Names nobody can register: `super` is the root account, `list` would clash with
# `crypto-helper account list`.
RESERVED_USERNAMES = frozenset({SUPER_USERNAME, "list"})
