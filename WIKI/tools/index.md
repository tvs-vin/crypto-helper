---
title: Tools
---

# Tools

Docs for the **testing tools** we build for this project. The app's own command-line tool
is documented in [Reference: CLI]({{ site.baseurl }}/reference/cli).

| Tool | Covers |
|---|---|
| [Check runner]({{ site.baseurl }}/tools/checks) | Every check with pacman-style progress bars and times; mutation checks |
| [End-to-end tester]({{ site.baseurl }}/tools/tester) | Config-driven HTTP checks against a real server (`crypto-helper test`) |
| [Browser tests]({{ site.baseurl }}/tools/ui-tests) | Real Chromium tests of the web app, with screenshots |
| [Service test]({{ site.baseurl }}/tools/service-test) | Destructive full lifecycle: install, broken update + rollback, purge |
