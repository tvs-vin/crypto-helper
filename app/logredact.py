"""Keep secrets that travel in URLs out of the access log (the systemd journal).

Two kinds of URL carry one: an embed link (`/embed/<token>`, a bearer link stored only hashed
and encrypted in the database) and the terminal's one-time WebSocket ticket (`?ticket=`). The
access log keeps the method, the path with embed tokens hidden, and no query string at all.
"""

import logging
import re

EMBED_TOKEN = re.compile(r"(/embed/)[^/?.\s]+")


def redact(path: str) -> str:
    path = path.split("?", 1)[0] + ("?…" if "?" in path else "")
    return EMBED_TOKEN.sub(r"\1…", path)


class RedactAccessLog(logging.Filter):
    """For uvicorn's access logger: its record args are (client, method, path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact(args[2]), *args[3:])
        return True


def install() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactAccessLog) for f in access.filters):
        access.addFilter(RedactAccessLog())
