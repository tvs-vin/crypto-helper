"""Notifications between throwaway users only: never sends to real accounts on a live server."""

from toolchain.tester.framework import check, expect, expect_status


@check("notifications", "401 anonymous, 403 sending without notifications.send")
def access(ctx):
    expect_status(ctx.client().get("/api/notifications"), 401, "anonymous")
    expect_status(ctx.client().get("/api/notifications/stream"), 401, "anonymous stream")
    name, _ = ctx.make_user([])
    c = ctx.as_user(name)
    expect_status(c.post("/api/notifications/send", {"to": "all", "title": "x"}), 403, "send")


@check("notifications", "send to one throwaway user: read, mark read, clear")
def one(ctx):
    sender, _ = ctx.make_user(["notifications.send"])
    name, uid = ctx.make_user([])
    s, c = ctx.as_user(sender), ctx.as_user(name)
    r = s.post(
        "/api/notifications/send", {"to": uid, "title": "t_hello", "body": "hi", "level": "warning"}
    )
    expect_status(r, 201, "send")
    data = c.get("/api/notifications").json()
    expect(data["unread"] == 1 and data["items"][0]["title"] == "t_hello", f"{data}")
    expect(c.post("/api/notifications/read", {}).json()["unread"] == 0, "mark read")
    expect_status(c.delete("/api/notifications"), 204, "clear read")
    expect(c.get("/api/notifications").json()["items"] == [], "cleared")


@check("notifications", "someone who turned messages off doesn't get them")
def muted(ctx):
    sender, _ = ctx.make_user(["notifications.send"])
    name, uid = ctx.make_user([])
    c = ctx.as_user(name)
    off = {"notifications": {"channels": {"messages": {"inapp": False}}}}
    expect_status(c.patch("/api/me/preferences", off), 200, "turn off")
    r = ctx.as_user(sender).post("/api/notifications/send", {"to": uid, "title": "t_muted"})
    expect(r.json().get("sent") == 0, f"delivered anyway: {r.json()}")
