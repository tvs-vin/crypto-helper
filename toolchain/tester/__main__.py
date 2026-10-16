"""Crypto Helper end-to-end tester. Settings live in toolchain/tester/config.toml."""

import argparse
import json
import os
import sys
import time
import tomllib
from pathlib import Path

from toolchain.tester.framework import REGISTRY, Context, Skip
from toolchain.tester.server import REPO, SpawnedServer
from toolchain.tester.suites import ALL_SUITES

DEFAULT_CONFIG = Path(__file__).with_name("config.toml")
GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="crypto-helper test", description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument(
        "--suite",
        action="append",
        choices=ALL_SUITES,
        help="run only this suite (repeatable); overrides [suites]",
    )
    ap.add_argument("--target", choices=["spawn", "live"], help="override [tester].target")
    args = ap.parse_args(argv)

    cfg = tomllib.loads(args.config.read_text())
    t = cfg.get("tester", {})
    if not t.get("enabled", False):
        print(f"Tester is disabled ([tester] enabled = false in {args.config}). Nothing to do.")
        return 0

    switches = cfg.get("suites", {})
    suites = args.suite or [s for s in ALL_SUITES if switches.get(s, False)]
    unknown = set(switches) - set(ALL_SUITES)
    if unknown:
        print(f"Unknown suites in config: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if not suites:
        print("Every suite is switched off in [suites]. Nothing to do.")
        return 0

    target = args.target or t.get("target", "spawn")
    server = None
    if target == "spawn":
        server = SpawnedServer(t.get("spawn_price_provider", "mock"), embed=True)
        print(color(f"Starting a throwaway server on {server.base_url} (temp database)...", DIM))
        server.start()
        from toolchain.tester.client import Client

        r = Client(server.base_url).post(
            "/api/setup", {"token": server.setup_token, "password": server.password}
        )
        if r.status != 201:
            server.stop()
            print(f"Setup of the throwaway server failed: HTTP {r.status} {r.text}")
            return 1
        ctx = Context(server.base_url, "super", server.password, "spawn")
    elif target == "live":
        env = t.get("password_env", "BOT_TESTER_PASSWORD")
        password = os.environ.get(env)
        if not password:
            print(f"Live mode needs the password in the {env} environment variable.")
            return 2
        ctx = Context(
            t.get("base_url", "http://127.0.0.1:8000"), t.get("username", "super"), password, "live"
        )
        print(color(f"Testing live server {ctx.base_url} as {ctx.admin_username}", DIM))
    else:
        print(f"Unknown target {target!r}: use 'spawn' or 'live'.")
        return 2

    verbose = t.get("verbose", True)
    results = []
    try:
        for suite in suites:
            checks = [c for c in REGISTRY if c.suite == suite]
            print(f"\n[{suite}]")
            for c in checks:
                start = time.perf_counter()
                skipped = False
                try:
                    c.fn(ctx)
                    ok, msg = True, ""
                except Skip as e:
                    ok, msg, skipped = True, str(e), True
                except AssertionError as e:
                    ok, msg = False, str(e)
                except Exception as e:  # a crash in a check is a failure, not a tester crash
                    ok, msg = False, f"{type(e).__name__}: {e}"
                ms = (time.perf_counter() - start) * 1000
                results.append(
                    {
                        "suite": suite,
                        "check": c.name,
                        "ok": ok,
                        "message": msg,
                        "ms": round(ms),
                        "skipped": skipped,
                    }
                )
                if skipped and verbose:
                    print(f"  {color('SKIP', DIM)} {c.name} {color(f'({msg})', DIM)}")
                elif ok and verbose:
                    print(f"  {color('PASS', GREEN)} {c.name} {color(f'({ms:.0f} ms)', DIM)}")
                elif not ok:
                    print(f"  {color('FAIL', RED)} {c.name}\n       {msg}")
                    if t.get("stop_on_fail", False):
                        raise StopIteration
            done = [r for r in results if r["suite"] == suite]
            if not verbose:
                print(f"  {sum(r['ok'] for r in done)}/{len(done)} passed")
    except StopIteration:
        print(color("\nStopped at the first failure (stop_on_fail = true).", DIM))
    finally:
        problems = ctx.cleanup() if ctx.mode == "live" else []
        for p in problems:
            print(color(f"cleanup: {p}", RED))
        if server:
            server.stop()

    skipped = sum(r.get("skipped", False) for r in results)
    passed = sum(r["ok"] for r in results) - skipped
    failed = len(results) - passed - skipped
    summary = (
        f"{passed} passed, {failed} failed"
        + (f", {skipped} skipped" if skipped else "")
        + f" ({len(results)} checks, target={target})"
    )
    print("\n" + color(summary, RED if failed else GREEN))

    report = t.get("report_file", "")
    if report:
        path = (REPO / report) if not Path(report).is_absolute() else Path(report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"target": target, "passed": passed, "failed": failed, "results": results}, indent=2
            )
        )
        print(color(f"Report written to {path}", DIM))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
