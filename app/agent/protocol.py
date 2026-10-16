"""What can be asked of the agent. One JSON object per line, one request per connection."""

import ipaddress
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.console import COMMANDS

MAX_BYTES = 16 * 1024
# Services the Services window can see. "web" can be restarted but not switched off (that
# would cut off the window asking), "agent" is shown but managed with the CLI only.
SWITCHABLE = ("embed", "backups", "console", "terminal")
RESTARTABLE = ("web", "embed")


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal[
        "status", "service.set", "service.restart", "backup.run", "console.run", "terminal.open"
    ]
    # The account that asked (for the agent's log only; the web app decided it may).
    actor: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.<>-]+$")
    service: Literal["web", "embed", "backups", "console", "terminal"] | None = None
    on: bool | None = None
    # console.run: which command (an id, never a command line) and how many log lines.
    command: Literal[tuple(COMMANDS)] | None = None
    lines: int | None = Field(default=None, ge=20, le=1000)
    # terminal.open: the window's size and the browser's address (for `login -h`).
    cols: int | None = Field(default=None, ge=20, le=500)
    rows: int | None = Field(default=None, ge=5, le=200)
    client_ip: str | None = Field(default=None, max_length=45)

    @field_validator("client_ip")
    @classmethod
    def _ip(cls, v):
        if v is not None:
            ipaddress.ip_address(v)  # only an address can reach `login -h`
        return v


def encode(obj: dict) -> bytes:
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("message too large")
    return data
