"""10b: rules that hold for every route, checked against the app's own route table so a new
endpoint can't slip past them.

1. Nothing answers without a session except a short public list (asked of every route for real,
   anonymously: also catches routes that check the session themselves).
2. Every state-changing route writes an audit entry, or says why not.
"""

import importlib
import inspect
import re

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import H

# Answer without a session, on purpose.
PUBLIC = {
    ("GET", "/api/setup/status"): "the first-launch screen asks whether setup is done",
    ("POST", "/api/setup"): "creating super needs the one-time setup token instead",
    ("POST", "/api/auth/login"): "signing in",
    ("POST", "/api/auth/logout"): "signing out works (and does nothing) without a session",
    ("GET", "/"): "the page itself; everything it loads asks for a session",
}

# State-changing routes that write their audit entry in a helper (named here, and checked).
AUDITED_IN = {
    ("POST", "/api/themes/upload"): "_store_bundle",
    ("POST", "/api/wallpapers"): "_store",
    # Sync now: the engine records a wallet.sync entry when balances change.
    ("POST", "/api/wallets/{wallet_id}/sync"): "app.sync.engine.sync_wallet",
    # The kill switch: the same functions the CLI and the bot check use record it.
    ("POST", "/api/bots/kill"): "app.bots.trip",
    ("POST", "/api/bots/rearm"): "app.bots.rearm",
    ("POST", "/api/bots/drill"): "app.bots.trip",
}

# State-changing routes that don't write an audit entry, and why.
NOT_AUDITED = {
    ("POST", "/api/trading/keys/{key_id}/first-order/preview"): "shows what a first order would "
    "be; nothing is sent or changed",
    ("PUT", "/api/me/wallet-order"): "your own display order",
    ("PUT", "/api/me/preferences"): "your own display settings (layout saves constantly)",
    ("PATCH", "/api/me/preferences"): "your own display settings (layout saves constantly)",
    ("POST", "/api/notifications/read"): "marking your own notifications read",
    ("DELETE", "/api/notifications/{notification_id}"): "deleting one of your own notifications",
    ("DELETE", "/api/notifications"): "clearing your own read notifications",
    ("POST", "/api/notifications/channels/discord/test"): "a test message to your own webhook",
    ("POST", "/api/onboarding/finish"): "your own walkthrough progress",
    ("POST", "/api/backtests/run"): "a calculation: nothing is stored (saving is audited)",
    ("POST", "/api/onboarding/restart"): "your own walkthrough progress",
}

WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def routes(app):
    out = []
    for top in app.routes:
        for r in getattr(top, "effective_route_contexts", lambda: [])():
            # A WebSocket's context has no path of its own: it's on the original route.
            path = r.path or r.starlette_route.path
            for m in sorted(r.methods or {"WS"}):
                out.append((m, path, r))
    return out


def test_route_table_is_read(app):
    assert len(routes(app)) > 90  # the app's own list, not an empty one


def test_nothing_answers_without_a_session_except_the_public_list(app):
    anon = TestClient(app)
    answered = []
    for method, path, _ in routes(app):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        if method == "WS":
            with pytest.raises(WebSocketDisconnect) as e:
                with anon.websocket_connect(url, headers={"origin": "http://testserver"}):
                    pass
            assert e.value.code in (4401, 4403), (path, e.value.code)
            continue
        r = anon.request(method, url, headers=H, json={})
        if r.status_code != 401:
            answered.append(f"{method} {path} -> {r.status_code}")
    assert not answered, "answered without a session:\n" + "\n".join(answered)


def test_public_list_is_current(app):
    present = {(m, p) for m, p, _ in routes(app)}
    assert set(PUBLIC) | set(AUDITED_IN) | set(NOT_AUDITED) <= present


def test_every_change_is_audited_or_says_why_not(app):
    missing = []
    for method, path, r in routes(app):
        if method not in WRITES or (method, path) in PUBLIC or (method, path) in NOT_AUDITED:
            continue
        src = inspect.getsource(r.endpoint)
        helper = AUDITED_IN.get((method, path))
        if helper:
            module, _, name = helper.rpartition(".")
            assert name in src, (path, helper)
            owner = importlib.import_module(module) if module else inspect.getmodule(r.endpoint)
            src = inspect.getsource(getattr(owner, name))
        if not re.search(r"\b(write_audit|_audited_agent_call|record)\(", src):
            missing.append(f"{method} {path}")
    assert not missing, "audit these, or list them in NOT_AUDITED with the reason:\n" + "\n".join(
        missing
    )


def test_api_bodies_are_capped_except_uploads(logged_in):
    big = {"content": "x" * (3 * 1024 * 1024)}
    r = logged_in.post("/api/themes", json=big, headers=H)
    assert r.status_code == 413
    r = logged_in.patch("/api/me/preferences", json={"layout": "y" * (3 * 1024 * 1024)}, headers=H)
    assert r.status_code == 413
    # Uploads have their own, larger limit (and stream): not refused by size here.
    r = logged_in.post("/api/wallpapers?name=x", content=b"z" * (3 * 1024 * 1024),
                       headers={**H, "Content-Type": "application/octet-stream"})  # fmt: skip
    assert r.status_code == 422  # not a picture, but it got that far
