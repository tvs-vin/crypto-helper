---
title: Home
---

# Crypto Helper

A self-hosted web dashboard that will grow into a track-and-alert crypto bot. It runs on
your own VM, and you use it from a browser through a private tunnel.

**Status:** phase 2 is complete and released as **v1.1.0**: on top of phase 1 (accounts with
2FA, wallets and simulated transfers, prices and price alerts, the web desktop, embeds,
notifications and the tools to run it as a service), balances sync read-only from Coinbase,
Kraken, Gemini, Binance.US and Bitcoin/Ethereum-family addresses, with a trade log for taxes and
balance history. What's in each release:
`CHANGELOG.md` in the repository. Start here: [Install as a service]({{ site.baseurl }}/guides/install-as-a-service).
No real funds are involved in phases 1 to 3. Next: phase 3 ([Roadmap]({{ site.baseurl }}/project/roadmap)).

## Sections

| Section | What's there | Pages |
|---|---|---|
| [Guides]({{ site.baseurl }}/guides/) | Step-by-step how-tos for using and running it | [First steps]({{ site.baseurl }}/guides/first-steps) · [Using the desktop]({{ site.baseurl }}/guides/using-the-desktop) · [Install as a service]({{ site.baseurl }}/guides/install-as-a-service) · [Getting started]({{ site.baseurl }}/guides/getting-started) · [Remote access]({{ site.baseurl }}/guides/remote-access) · [Updating]({{ site.baseurl }}/guides/updating) · [Backups]({{ site.baseurl }}/guides/backups) · [Wallets and transfers]({{ site.baseurl }}/guides/wallets-and-transfers) · [Exchange connections]({{ site.baseurl }}/guides/exchange-connections) · [On-chain wallets]({{ site.baseurl }}/guides/onchain-wallets) · [Trade log]({{ site.baseurl }}/guides/trade-log) · [Balance history]({{ site.baseurl }}/guides/balance-history) · [Alerts]({{ site.baseurl }}/guides/alerts) · [Backtester]({{ site.baseurl }}/guides/backtester) · [Paper trading]({{ site.baseurl }}/guides/paper-trading) · [Prices and portfolio]({{ site.baseurl }}/guides/prices-and-portfolio) · [App manager]({{ site.baseurl }}/guides/app-manager) · [Services]({{ site.baseurl }}/guides/services) · [Console and Terminal]({{ site.baseurl }}/guides/console-and-terminal) · [Notifications]({{ site.baseurl }}/guides/notifications) · [Embeds]({{ site.baseurl }}/guides/embeds) · [Set up 2FA]({{ site.baseurl }}/guides/set-up-2fa) · [Recovery codes]({{ site.baseurl }}/guides/recovery-codes) |
| [Reference]({{ site.baseurl }}/reference/) | Exact facts: every endpoint, command, setting and rule | [API]({{ site.baseurl }}/reference/api) · [CLI]({{ site.baseurl }}/reference/cli) · [Themes]({{ site.baseurl }}/reference/themes) · [Service]({{ site.baseurl }}/reference/service) · [Prices]({{ site.baseurl }}/reference/prices) · [Networks]({{ site.baseurl }}/reference/networks) · [Configuration]({{ site.baseurl }}/reference/configuration) · [Security model]({{ site.baseurl }}/reference/security) · [Database migrations]({{ site.baseurl }}/reference/database-migrations) · [Dependencies]({{ site.baseurl }}/reference/dependencies) |
| [Project]({{ site.baseurl }}/project/) | Where it's going and why | [Roadmap]({{ site.baseurl }}/project/roadmap) · [Features by milestone]({{ site.baseurl }}/project/features-by-milestone) · [Decisions]({{ site.baseurl }}/project/decisions) · [Milestone 12 plan]({{ site.baseurl }}/project/milestone-12) · [Milestone 6 plan]({{ site.baseurl }}/project/milestone-6) |
| [Tools]({{ site.baseurl }}/tools/) | Testing tools we build for this project | [Check runner]({{ site.baseurl }}/tools/checks) · [End-to-end tester]({{ site.baseurl }}/tools/tester) · [Browser tests]({{ site.baseurl }}/tools/ui-tests) · [Service test]({{ site.baseurl }}/tools/service-test) |
| [Glossary]({{ site.baseurl }}/glossary) | Crypto terms in plain words | |

## Where pages go
- **guides/**: "how do I…" pages, written as numbered steps.
- **reference/**: complete, exact descriptions; one page per area.
- **project/**: plans, phases and decisions made with the owner.
- **tools/**: only docs for the testing tools we build (not the app's own CLI).
- **glossary.md**: crypto and security terms.

Every section has an `index.md` listing its pages. Add new pages to it and to the table above.
