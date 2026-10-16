// Every window the desktop can open. Each key is an app id from app/apps.py (or a core app
// like settings); which ones an account sees comes from the server (/api/auth/me `apps`).

import { renderApps } from "./panels/apps.js";
import { renderAudit } from "./panels/audit.js";
import { renderOverview } from "./panels/overview.js";
import { renderServices } from "./panels/services.js";
import { renderSettings } from "./panels/settings.js";
import { renderTransfers } from "./panels/transfers.js";
import { renderUsers } from "./panels/users.js";
import { renderWallets } from "./panels/wallets.js";

export const PANELS = {
  wallets: { title: "Wallets", icon: "wallet", size: [760, 560], render: renderWallets },
  overview: { title: "Overview", icon: "chart", size: [680, 560], render: renderOverview },
  transfers: { title: "Transfers", icon: "transfer", size: [700, 560], render: renderTransfers },
  users: { title: "Users", icon: "users", size: [760, 480], render: renderUsers },
  audit: { title: "Audit log", icon: "list", size: [760, 500], render: renderAudit },
  apps: { title: "App manager", icon: "appgrid", size: [860, 560], render: renderApps },
  services: { title: "Services", icon: "server", size: [760, 640], render: renderServices },
  settings: { title: "Settings", icon: "settings", size: [760, 600], render: renderSettings },
};
