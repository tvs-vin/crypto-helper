"""The one way exchange clients talk to the network: a time limit, no redirects (a key's
signature is only for the address it was made for), numbers parsed straight into Decimal, and
errors turned into short messages that never contain a key, a signature or a full address."""

import json
import urllib.error
import urllib.request
from decimal import Decimal

from app.sync import SourceError

TIMEOUT = 15
USER_AGENT = "CryptoHelper (self-hosted; read-only)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _reason(raw: bytes) -> str:
    """A short reason from an error answer (the exchange's own words), if there is one."""
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return ""
    if isinstance(data, dict):
        for k in ("message", "msg", "reason", "error_details", "error"):
            v = data.get(k)
            if isinstance(v, list):
                v = ", ".join(map(str, v))
            if isinstance(v, str) and v:
                return v[:160]
    return ""


def call(
    name: str,
    method: str,
    url: str,
    *,
    headers=None,
    body: bytes | None = None,
    final_on: tuple[int, ...] = (401, 403),
):
    """Make one request and return the parsed JSON. Raises SourceError (final for answers
    meaning the key itself is refused)."""
    req = urllib.request.Request(
        url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            raw = r.read()
            if r.status not in (200, 201):
                raise SourceError(f"{name} answered {r.status}")
    except urllib.error.HTTPError as e:
        reason = _reason(e.read())
        suffix = f": {reason}" if reason else ""
        if e.code in (418, 429):
            raise SourceError(f"{name} asked to slow down; it will try again later") from None
        if e.code in final_on:
            raise SourceError(f"{name} refused the key ({e.code}){suffix}", final=True) from None
        raise SourceError(f"{name} answered {e.code}{suffix}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceError(f"Couldn't reach {name} ({getattr(e, 'reason', e)})") from None
    try:
        return json.loads(raw, parse_float=Decimal)
    except ValueError:
        raise SourceError(f"{name} sent something that isn't JSON") from None


def amount(value) -> Decimal:
    """An exchange's number (text or Decimal) as an exact Decimal."""
    try:
        d = Decimal(str(value))
    except Exception:
        raise SourceError(
            f"An amount from the exchange isn't a number: {str(value)[:20]!r}"
        ) from None
    if not d.is_finite():
        raise SourceError("An amount from the exchange isn't a finite number")
    return d
