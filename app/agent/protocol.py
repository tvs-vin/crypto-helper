"""What can be asked of the agent. One JSON object per line, one request per connection."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_BYTES = 16 * 1024
# Services the Services window can see. "web" can be restarted but not switched off (that
# would cut off the window asking), "agent" is shown but managed with the CLI only.
SWITCHABLE = ("embed", "backups")
RESTARTABLE = ("web", "embed")


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["status", "service.set", "service.restart", "backup.run"]
    # The account that asked (for the agent's log only; the web app decided it may).
    actor: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.<>-]+$")
    service: Literal["web", "embed", "backups"] | None = None
    on: bool | None = None


def encode(obj: dict) -> bytes:
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("message too large")
    return data
