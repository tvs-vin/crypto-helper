"""Check registry and the shared context every check receives."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from toolchain.tester.client import Client

PW = "tester-passphrase-ok"  # password for throwaway t_* users


class CheckFailed(AssertionError):
    pass


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def expect_status(resp, status: int, what: str) -> None:
    expect(
        resp.status == status,
        f"{what}: expected HTTP {status}, got {resp.status} {resp.text[:200]}",
    )


@dataclass
class Check:
    suite: str
    name: str
    fn: Callable


REGISTRY: list[Check] = []


def check(suite: str, name: str):
    def deco(fn):
        REGISTRY.append(Check(suite, name, fn))
        return fn

    return deco


@dataclass
class Context:
    base_url: str
    admin_username: str
    admin_password: str
    mode: str
    created_user_ids: list[int] = field(default_factory=list)
    _admin: Client | None = None

    def client(self) -> Client:
        return Client(self.base_url)

    @property
    def admin(self) -> Client:
        """A logged-in super client, re-created if a check logged it out."""
        if self._admin is None or self._admin.get("/api/auth/me").status != 200:
            c = self.client()
            r = c.login(self.admin_username, self.admin_password)
            expect_status(r, 200, "admin login")
            self._admin = c
        return self._admin

    def make_user(self, permissions=(), password: str = PW) -> tuple[str, int]:
        name = "t_" + secrets.token_hex(4)
        r = self.admin.post(
            "/api/users",
            {"username": name, "password": password, "permissions": list(permissions)},
        )
        expect_status(r, 201, f"create throwaway user {name}")
        uid = r.json()["id"]
        self.created_user_ids.append(uid)
        return name, uid

    def as_user(self, name: str, password: str = PW) -> Client:
        c = self.client()
        expect_status(c.login(name, password), 200, f"login as {name}")
        return c

    def cleanup(self) -> list[str]:
        problems = []
        for uid in self.created_user_ids:
            r = self.admin.delete(f"/api/users/{uid}")
            if r.status not in (204, 404):
                problems.append(f"could not delete user {uid}: HTTP {r.status}")
        self.created_user_ids.clear()
        return problems
