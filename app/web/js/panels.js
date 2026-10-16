// Every window the desktop can open. `perm` is checked here only to hide what you can't
// use; the server checks again on every request.

import { renderAudit } from "./panels/audit.js";
import { renderOverview } from "./panels/overview.js";
import { renderSettings } from "./panels/settings.js";
import { renderTransfers } from "./panels/transfers.js";
import { renderUsers } from "./panels/users.js";
import { renderWallets } from "./panels/wallets.js";

export const PANELS = {
  wallets: { title: "Wallets", icon: "wallet", perm: "wallets.view", size: [760, 560], render: renderWallets },
  overview: { title: "Overview", icon: "chart", perm: "prices.view", size: [680, 560], render: renderOverview },
  transfers: { title: "Transfers", icon: "transfer", perm: "wallets.view", size: [700, 560], render: renderTransfers },
  users: { title: "Users", icon: "users", perm: "users.manage", size: [760, 480], render: renderUsers },
  audit: { title: "Audit log", icon: "list", perm: "audit.view", size: [760, 500], render: renderAudit },
  settings: { title: "Settings", icon: "settings", perm: null, size: [760, 600], render: renderSettings },
};
