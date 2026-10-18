"""Discord webhooks: checking an address, and posting a notification to it.

Only Discord's own webhook addresses are accepted, so this can't be pointed at another server.
Mentions are always switched off (nobody gets pinged by @everyone in a title). Redirects aren't
followed. The address itself is a secret and is never logged or shown in full.
"""

import json
import re
import urllib.error
import urllib.request

WEBHOOK_RE = re.compile(
    r"^https://(?:discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)"
    r"/api/webhooks/(\d{5,30})/([A-Za-z0-9_-]{20,100})$"
)
COLORS = {"info": 0x7545FC, "warning": 0xE3A23B, "critical": 0xF2606C}
CATEGORY = {
    "security": "Security",
    "system": "System",
    "prices": "Price alert",
    "messages": "Message",
}
TIMEOUT = 10


class WebhookError(Exception):
    """Sending failed. `retry_after` (seconds) when Discord asked us to slow down; `final` when
    retrying can't help (the webhook was deleted or is wrong)."""

    def __init__(self, message: str, *, retry_after: float | None = None, final: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        self.final = final


def check(url: str) -> str:
    url = (url or "").strip()
    if not WEBHOOK_RE.match(url):
        raise ValueError(
            "That isn't a Discord webhook address (it looks like "
            "https://discord.com/api/webhooks/123…/abc…). Make one in Discord: channel "
            "settings → Integrations → Webhooks."
        )
    return url


def mask(url: str) -> str:
    """Enough to recognise it, not enough to use it."""
    m = WEBHOOK_RE.match(url)
    return (
        f"Discord webhook …{m.group(1)[-4:]} (token …{m.group(2)[-4:]})" if m else "Discord webhook"
    )


def payload(category: str, level: str, title: str, body: str) -> dict:
    return {
        "username": "Crypto Helper",
        "allowed_mentions": {"parse": []},  # never ping anyone
        "embeds": [
            {
                "title": title[:256],
                "description": body[:2000],
                "color": COLORS.get(level, COLORS["info"]),
                "footer": {"text": f"{CATEGORY.get(category, category)} · Crypto Helper"},
            }
        ],
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def post(url: str, data: dict) -> None:
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "CryptoHelper (self-hosted)"},
    )  # fmt: skip
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            if r.status not in (200, 204):
                raise WebhookError(f"Discord answered {r.status}")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                retry = float(json.loads(e.read() or b"{}").get("retry_after", 5))
            except ValueError:
                retry = 5.0
            raise WebhookError("Discord asked to slow down", retry_after=retry) from None
        if e.code in (401, 403, 404):
            raise WebhookError(
                f"Discord refused the webhook ({e.code}): it was deleted or is wrong", final=True
            ) from None
        raise WebhookError(f"Discord answered {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WebhookError(f"Couldn't reach Discord ({getattr(e, 'reason', e)})") from None
