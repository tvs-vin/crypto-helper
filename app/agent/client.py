"""Calling the agent from the web app (or the CLI)."""

import json
import socket

from app.agent.protocol import MAX_BYTES, encode


class AgentUnavailable(Exception):
    """No agent answering (not installed, not running, or no access to its socket)."""


class AgentError(Exception):
    """The agent refused or failed; the message is safe to show."""


def call(path: str, op: str, actor: str, timeout: float = 40, **args) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(encode({"op": op, "actor": actor, **args}))
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise AgentError("the agent's answer was too large")
    except (FileNotFoundError, ConnectionRefusedError):
        raise AgentUnavailable("the agent isn't running") from None
    except PermissionError:
        raise AgentUnavailable("no access to the agent's socket") from None
    except TimeoutError:
        raise AgentError("the agent didn't answer in time") from None
    except OSError as e:
        raise AgentUnavailable(f"can't reach the agent: {e.strerror or e}") from None
    try:
        answer = json.loads(buf)
    except ValueError:
        raise AgentError("the agent sent a broken answer") from None
    if not answer.get("ok"):
        raise AgentError(answer.get("error") or "the agent refused")
    return answer
