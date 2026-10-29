---
title: Phase 4 review
---

# Phase 4 review (milestone 13e, 2026-10-28)

A review of everything phase 4 added (milestone 13: trading keys and caps, placing orders, live
bots, the first tiny order) before the v1.3.0 release: a read-through of every new endpoint and
job, a dependency audit, and every phase 4 guard mutation-checked again on the final code. This
page lists what was checked, what was found, and what changed.

## Checks that now run with every test run
| Check | Test |
|---|---|
| Every route still refuses a caller without a session (except the public list), every change is audited or says why not, bodies are capped at 2 MB; every route refuses an account with a pending rule. Phase 4's routes are in both. | `tests/test_route_audit.py`, `tests/test_account_rules.py` |
| Order clients only call the paths in their `TRADE_ENDPOINTS`; nothing that withdraws, transfers, deposits, converts, cancels or leaves an order resting; every order immediate-or-cancel with our own id; signatures checked by local fakes of each exchange. | `tests/test_orders.py` |
| Trading keys: a key that can withdraw is refused (and deleted if it gains the right later); personal and shared keys only reach who they should; switches, caps and ceilings, 2FA codes for raising. | `tests/test_trading.py` |
| Live bots: every gate pauses with its reason; the cap; lost answers looked up, never resent; a restart mid-order; refusals; day-old orders; the hourly balance comparison; the first tiny order (and, after this review, a crash or a second press while it's being sent). | `tests/test_live_bots.py` |
| Phase 4's guards are **mutation-checked**: all 76 (13a–13d and this review's fixes) switched off one at a time; every one is caught by a test. | `python -m toolchain.checks --mutations` |

**Dependencies:** `pip-audit` on the exact pinned versions (runtime and test tools) and on the
live install's 34 packages: no known vulnerabilities. Phase 4 added no dependency (exchanges are
spoken to with plain HTTPS, signed like phase 2).

## Found and fixed
| # | What | Risk | Fix |
|---|---|---|---|
| 1 | **Deleting an account that had a live bot failed** ("FOREIGN KEY constraint failed"): its personal trading keys went with it, but its bots stay (unowned, as paper bots do) and still pointed at them. | Admins couldn't delete such an account at all. | Its keys now go the way a deleted key always does: their bots are paused and unlinked first, and the deletion is refused while one of their real orders is on its way. |
| 2 | **The first tiny order was only written down after the exchange answered.** | A restart mid-send, or a second press with a fresh 2FA code before the answer came, could buy twice. | Claimed before it's sent (as live bots do): our id is saved first; a second press is refused while it's on its way, and after 2 minutes it's looked up by that id, never bought again. |
| 3 | **"Check again" on a trading key forgot its first tiny order.** | The key's live bots paused ("its key hasn't had its first tiny order yet"), and an order being looked up could lose its id. | A re-check keeps the first order's record. |
| 4 | **Rows read before taking the database's write lock were not read again after it** (the app's sessions keep rows after a commit, so `begin_immediate` returned the old copies). Found by the test for #2: the check that a second press hadn't claimed first saw the row from before. | Any code that lets go of the lock to call an exchange and takes it again (trading keys, the first order) could act on what was true before someone else's change. | `begin_immediate` now forgets what was read before, so everything read under the lock comes from the database. Mutation-checked. |
| 5 | **No test covered** the first tiny order being refused on practice prices, or for someone who may see a shared key but not trade (`live.trade`). | The guards were there; nothing would notice if they went. | Tests added. |
| 6 | Two older mutation checks no longer applied (their text now appears twice, since 13d reuses it). | They'd silently stop checking anything. | Re-anchored; both caught. |

## Looked at and fine
- **Keys:** encrypted at rest, shown masked, never logged; a key's check only calls permission
  and balance endpoints, never an order. Free text (labels) is checked for pasted secrets.
- **Who may use what:** personal keys are their owner's only; shared keys need
  `live.keys.shared` to see and `live.trade` to trade; admins delete keys only of accounts they
  may manage. Live bots are their owner's (and super's) only.
- **Exchange errors** in notes, notifications and the audit log are the exchange's short
  answer: no headers, URLs or keys.
- **The cap** counts what live bots control *now*: deleting a live bot frees its share (its coins
  stay in the exchange account, no longer managed). Now said in the guide.
- **Live trading off** works from the command line without the web server (`live off`), and
  the kill switch stops live bots before every order.
- **Locks:** every exchange call happens with nothing locked; claim and record are locked.

## Real transfers: planned with the owner
See [Decisions]({{ site.baseurl }}/project/decisions#real-transfers-2026-10-28). To be built after
v1.3.0.
