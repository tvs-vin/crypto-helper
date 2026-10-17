// Every window the desktop can open (`guide`: the Help page its "?" button opens). Each key is an app id from app/apps.py (or a core app
// like settings); which ones an account sees comes from the server (/api/auth/me `apps`).

import { renderApps } from "./panels/apps.js";
import { renderAudit } from "./panels/audit.js";
import { renderConsole } from "./panels/console.js";
import { renderHelp } from "./panels/help.js";
import { renderNotifications } from "./panels/notifications.js";
import { renderOverview } from "./panels/overview.js";
import { renderServices } from "./panels/services.js";
import { renderSettings } from "./panels/settings.js";
import { renderTerminal } from "./panels/terminal.js";
import { renderTransfers } from "./panels/transfers.js";
import { renderUsers } from "./panels/users.js";
import { renderWallets } from "./panels/wallets.js";

export const PANELS = {
  wallets: { guide: "guides/wallets-and-transfers", max: 4, title: "Wallets", icon: "wallet", size: [760, 560], render: renderWallets },
  overview: { guide: "guides/prices-and-portfolio", max: 4, title: "Overview", icon: "chart", size: [680, 560], render: renderOverview },
  transfers: { guide: "guides/wallets-and-transfers", max: 4, title: "Transfers", icon: "transfer", size: [700, 560], render: renderTransfers },
  users: { guide: "reference/security#who-can-manage-whom", title: "Users", icon: "users", size: [760, 480], render: renderUsers },
  audit: { guide: "reference/security#audit-log", max: 4, title: "Audit log", icon: "list", size: [760, 500], render: renderAudit },
  apps: { guide: "guides/app-manager", title: "App manager", icon: "appgrid", size: [860, 560], render: renderApps },
  services: { guide: "guides/services", title: "Services", icon: "server", size: [760, 640], render: renderServices },
  console: { guide: "guides/console-and-terminal", title: "Console", icon: "console", size: [760, 560], render: renderConsole },
  terminal: { guide: "guides/console-and-terminal", max: 3, title: "Terminal", icon: "terminal", size: [820, 520], render: renderTerminal },
  notifications: { guide: "guides/notifications", title: "Notifications", icon: "bell", size: [620, 560], render: renderNotifications },
  help: { title: "Help", icon: "help", size: [780, 620], render: renderHelp },
  settings: { guide: "guides/using-the-desktop", title: "Settings", icon: "settings", size: [760, 600], render: renderSettings },
};
