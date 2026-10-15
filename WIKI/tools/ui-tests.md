---
title: Browser tests
---

# Browser tests

`tests/ui/` drives the real web app in headless Chromium (Playwright) against a real
server process, the way you'd use it.

```bash
.venv/bin/pip install playwright && .venv/bin/playwright install --with-deps chromium   # once
.venv/bin/pytest tests/ui            # just the browser tests (~40 s)
.venv/bin/pytest                     # everything; browser tests skip if Chromium is missing
node --test tests/js/                # the window-layout maths, without a browser
```

Each test saves a screenshot of how it ended in `tests/ui/screens/` (gitignored) for a human
to look at. Any JavaScript error or Content-Security-Policy violation fails the test.

## What's covered
| Test | Proves |
|---|---|
| First launch | Setup box → create super → sign in → box closes on the same page; 2FA nudge |
| Mismatched / wrong password | Clear errors, the box stays, the password field clears |
| Two-factor | Code step appears; recovery code works |
| Permissions | The launcher only lists windows you're allowed |
| Drag and snap | Dragging to the edge shows the outline and snaps to half; the layout comes back in a new browser |
| Tiled mode | No overlaps; the mode is remembered |
| Keyboard, minimize, taskbar, maximize, close | The shortcuts and buttons |
| Themes | Apply at once; follow the user to another browser |
| Malicious theme | The browser refuses URLs, CSS and fonts outside the list |
| Session expiry | The box returns over the same windows; the action that hit the expiry still happens |
| Sign out and in | No second box; the last layout change is kept |
| Phone width | Windows stack, no sideways scrolling |
