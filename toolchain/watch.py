"""Watch the checks run: a full-screen view (like nano takes over the screen) of the run in
progress, redrawn twice a second.

    .venv/bin/python -m toolchain.watch          # full screen; q to quit
    .venv/bin/python -m toolchain.watch --once   # one plain snapshot (for scripts)

It reads `toolchain/.check-status.json`, which `python -m toolchain.checks` keeps up to date:
elapsed time and an estimate of what's left (from the last run's times), each stage, the files
running now with their own bars, what just finished and what failed. With no run going, it
shows the last one and waits for the next.
"""

import argparse
import json
import os
import sys
import time

from toolchain.checkstatus import STATUS

BAR = 20


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 10:
        return f"{max(0.0, seconds):.1f} s"
    if seconds < 60:
        return f"{int(round(seconds))} s"
    seconds = int(round(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def bar(done: int, total: int | None, width: int = BAR) -> str:
    if not total:
        return "[" + "-" * width + "]"
    filled = int(min(1.0, done / total) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process: it exists
    return True


def left(data: dict, now: float) -> float | None:
    """Seconds left: the running stage's share (from its progress, or its last time) plus the
    waiting stages' last times. None if there's nothing to go on."""
    total, known = 0.0, False
    for st in data.get("stages", []):
        if st["state"] == "running":
            elapsed = now - (st["started"] or now)
            p = data.get("progress")
            if p and p.get("done") and p.get("total"):
                total += elapsed / p["done"] * (p["total"] - p["done"])
                known = True
            elif st.get("previous"):
                total += max(0.0, st["previous"] - elapsed)
                known = True
        elif st["state"] == "waiting" and st.get("previous"):
            total += st["previous"]
            known = True
    return total if known else None


def render(data: dict | None, width: int, height: int, now: float | None = None) -> list:
    """The screen as [(text, style)], style one of: header, ok, fail, run, dim, plain."""
    now = now or time.time()
    out: list[tuple[str, str]] = []

    def add(text: str = "", style: str = "plain"):
        out.append((text[: max(0, width - 1)], style))

    if not data:
        add(" Crypto Helper checks ".ljust(width), "header")
        add()
        add("  No check run yet. Start one in the repository:", "dim")
        add("    .venv/bin/python -m toolchain.checks --ui", "dim")
        add("  This screen picks it up by itself.", "dim")
        return out[:height]
    running = not data.get("done") and alive(data.get("pid"))
    elapsed = (now if running else data.get("updated", now)) - data.get("started", now)
    if running:
        rest = left(data, now)
        state = (
            f"● running   elapsed {clock(elapsed)}   ~{clock(rest)} left"
            if rest is not None
            else f"● running   elapsed {clock(elapsed)}"
        )
    elif data.get("done"):
        ago = clock(now - data.get("updated", now))
        verdict = "✓ all passed" if data.get("ok") else "✗ something failed"
        state = f"{verdict} in {clock(elapsed)}, {ago} ago"
    else:
        state = "✗ the run stopped unexpectedly (its process is gone)"
    add(f" Crypto Helper checks   {state} ".ljust(width), "header")
    add()
    add(" Stages", "dim")
    name_w = max([len(s["name"]) for s in data.get("stages", [])] + [6])
    for st in data.get("stages", []):
        name = st["name"].ljust(name_w)
        last = f"  (last run {clock(st['previous'])})" if st.get("previous") else ""
        if st["state"] == "ok":
            add(f"  ✓ {name}  {st['result']:<28} {clock(st['seconds']):>7}", "ok")
        elif st["state"] == "fail":
            add(f"  ✗ {name}  {st['result']:<28} {clock(st['seconds']):>7}", "fail")
        elif st["state"] == "running":
            p = data.get("progress") or {}
            got = f"{p.get('done', 0)}/{p.get('total', '?')} {p.get('unit', '')}" if p else "…"
            since = clock(now - (st["started"] or now))
            add(
                f"  ▶ {name}  {got:<16} {bar(p.get('done', 0), p.get('total'))} {since:>7}{last}",
                "run",
            )
        else:
            add(f"  · {name}  waiting{last}", "dim")
    items = data.get("running") or {}
    if items:
        add()
        add(f" Running now ({len(items)})", "dim")
        for name, r in sorted(items.items(), key=lambda kv: kv[1].get("started", 0)):
            total = r.get("total")
            count = f"{r.get('done', 0)}/{total}" if total else f"{r.get('done', 0)}"
            since = clock(now - r.get("started", now))
            add(f"  {name[:34]:<34} {count:>9}  {bar(r.get('done', 0), total)} {since:>7}", "run")
    fin = data.get("finished") or []
    if fin:
        add()
        add(" Just finished", "dim")
        for f in fin:
            mark = "✓" if f["ok"] else "✗"
            add(
                f"  {mark} {f['name'][:34]:<34} {f['count']:>9}  {clock(f['seconds']):>7}",
                "ok" if f["ok"] else "fail",
            )
    fails = data.get("failures") or []
    if fails:
        add()
        add(f" Failures ({len(fails)})", "fail")
        for f in fails[-8:]:
            add(f"  ✗ {f}", "fail")
    footer = f" q quit · updated {clock(now - data.get('updated', now))} ago · {STATUS.name} "
    lines = out[: max(1, height - 1)]
    while len(lines) < height - 1:
        lines.append(("", "plain"))
    lines.append((footer[: max(0, width - 1)], "dim"))
    return lines


def load() -> dict | None:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return None


def _screen(stdscr) -> None:
    import curses

    curses.curs_set(0)
    stdscr.timeout(500)
    styles = {
        "plain": curses.A_NORMAL,
        "dim": curses.A_DIM,
        "header": curses.A_REVERSE,
        "ok": curses.A_NORMAL,
        "fail": curses.A_BOLD,
        "run": curses.A_BOLD,
    }
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        for i, color in enumerate((curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW), 1):
            curses.init_pair(i, color, -1)
        styles["ok"] = curses.color_pair(1)
        styles["fail"] = curses.color_pair(2) | curses.A_BOLD
        styles["run"] = curses.color_pair(3)
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        for y, (text, style) in enumerate(render(load(), w, h)):
            try:
                stdscr.addstr(y, 0, text, styles.get(style, curses.A_NORMAL))
            except curses.error:  # the last cell of the screen: harmless
                pass
        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27):
            return


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="print one snapshot and exit")
    args = ap.parse_args(argv)
    if args.once or not sys.stdout.isatty():
        size = os.get_terminal_size() if sys.stdout.isatty() else os.terminal_size((100, 40))
        lines = [t.rstrip() for t, _ in render(load(), size.columns, size.lines)]
        footer = lines.pop()
        while lines and not lines[-1]:  # a snapshot doesn't need the screen's empty rows
            lines.pop()
        print("\n".join([*lines, "", footer]))
        return 0
    import curses

    try:
        curses.wrapper(_screen)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
