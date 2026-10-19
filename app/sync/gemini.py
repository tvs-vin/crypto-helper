"""Gemini, read-only.

A key and secret; each private request carries a base64 JSON payload and its HMAC-SHA384.
Gemini reports a key's roles: only an Auditor key (read-only, and Gemini doesn't let it be
combined with other roles) is accepted; Trader or Fund Manager is refused.

Only these calls exist here: the key's roles, and balances.
"""

import base64
import hashlib
import hmac
import json
import threading
import time

from app.sync import Check, Exchange, Fetched, Field, SourceError, http, register
from app.sync.http import amount

READ_ENDPOINTS = {"/v1/roles", "/v1/balances"}


def sign(payload_b64: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_b64, hashlib.sha384).hexdigest()


class Gemini(Exchange):
    base = "https://api.gemini.com"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._lock = threading.Lock()
        self._last_nonce = 0

    def _nonce(self) -> str:
        with self._lock:
            self._last_nonce = max(self._last_nonce + 1, int(time.time() * 1000))
            return str(self._last_nonce)

    def private(self, creds: dict, path: str):
        assert path in READ_ENDPOINTS
        payload = base64.b64encode(json.dumps({"request": path, "nonce": self._nonce()}).encode())
        headers = {
            "Content-Type": "text/plain",
            "Content-Length": "0",
            "Cache-Control": "no-cache",
            "X-GEMINI-APIKEY": creds.get("key", "").strip(),
            "X-GEMINI-PAYLOAD": payload.decode(),
            "X-GEMINI-SIGNATURE": sign(payload, creds.get("secret", "").strip()),
        }
        return http.call(self.name, "POST", self.base + path, headers=headers, body=b"")

    def check(self, creds: dict) -> Check:
        roles = self.private(creds, "/v1/roles")
        if not isinstance(roles, dict):
            raise SourceError("Gemini didn't say what the key may do")
        if roles.get("isTrader") or roles.get("isFundManager"):
            return Check(False, "Gemini says this key is a Trader or Fund Manager key")
        if roles.get("isAuditor") is True:
            return Check(True, "Auditor (read-only), checked with Gemini")
        return Check(None, "Gemini didn't say this key is an Auditor key")

    def fetch(self, creds: dict) -> Fetched:
        out = Fetched()
        for b in self.private(creds, "/v1/balances") or []:
            code = str(b.get("currency", "")).upper()
            total = amount(b.get("amount", "0"))
            if code and total:
                out.balances[code] = out.balances.get(code, 0) + total
        return out


GEMINI = register(
    Gemini(
        id="gemini",
        name="Gemini",
        fields=[
            Field("key", "API key", secret=False, help="Starts with account-"),
            Field("secret", "API secret"),
        ],
        guide="guides/exchange-connections#gemini",
        confirm_text="On Gemini, this key has only the Auditor role.",
    )
)
