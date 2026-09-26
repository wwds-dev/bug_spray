"""Bug Spray CLI.

    python main.py --selftest                 check config/store/adapters wire up, no network
    python main.py scan [--platform P] [--full] [--all] [--json]
                                              fetch platforms, store, print what changed
    python main.py list [--platform P] [--all] [--limit N] [--json]
                                              stored programs, highest payout first
    python main.py show PLATFORM SLUG [--json]
                                              one program's scope and reward table
    python main.py feed [--json]               saved program feed for Sentinel

No command here performs recon or touches a program's actual assets — see
the honest-boundary section in README.md.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime

from . import __version__, config, secrets, sources, store, watchlist
from .changes import ProgramChanges, diff_program
from .feed import read_feed
from .models import Program

# If a platform suddenly omits more than this share of the programs it listed
# last time, assume its API changed shape rather than that half the platform
# closed overnight, and do not mark them gone.
GONE_GUARD_RATIO = 0.5

CURRENCY_SIGNS = {"USD": "$", "EUR": "€", "GBP": "£"}


def money(amount: float | None, currency: str) -> str:
    if amount is None:
        return "?"
    sign = CURRENCY_SIGNS.get(currency.upper())
    number = f"{amount:,.0f}"
    return f"{sign}{number}" if sign else f"{number} {currency.upper()}"


def scope_summary(program: Program) -> str:
    count = len(program.scope.in_scope)
    return f"{count} in scope" if count else "scope not public"


def reward_summary(program: Program) -> str:
    best = program.max_reward()
    return f"up to {money(*best)}" if best else "no amount published"


def _load_settings() -> config.Settings | None:
    settings = config.load()
    problems = settings.validate()
    if problems:
        print("Config problems:")
        for problem in problems:
            print(f"  - {problem}")
        return None
    return settings


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    settings = config.load()
    problems = settings.validate()

    print(f"bug_spray {__version__} self-test")
    print(f"  config path:      {config.CONFIG_PATH}")
    print(f"  db path:          {settings.db_path}")
    print(f"  enabled platforms: {settings.enabled_platforms or '(none configured)'}")
    print(f"  registered adapters: {sorted(sources.REGISTRY)}")
    print(f"  watchlist filters: {'on' if watchlist.is_active(settings) else 'off'}")
    print(f"  keyring backend:  {secrets.backend_name()}")

    missing = sorted(set(config.ALL_PLATFORMS) - set(sources.REGISTRY))
    if missing:
        problems.append(f"No adapter registered for: {missing}")

    db = store.Store(settings.db_path)
    db.close()
    print("  sqlite store:     ok (created/opened)")

    if problems:
        print("\nFAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\nOK")
    return 0


# ---------------------------------------------------------------- scan


def _describe(change: ProgramChanges) -> list[str]:
    p = change.program
    head = f"[{p.platform}] {p.name}"
    lines = []
    if change.new:
        lines.append(f"NEW       {head} — {reward_summary(p)}, {scope_summary(p)}")
    if change.returned:
        lines.append(f"BACK      {head} — listed again")
    if change.gone:
        lines.append(f"GONE      {head} — no longer publicly listed")
    if change.status:
        lines.append(f"{change.status.upper():<9} {head}")
    if change.scope_added:
        lines.append(f"SCOPE +{len(change.scope_added):<3} {head}: {', '.join(change.scope_added[:8])}"
                     + (" …" if len(change.scope_added) > 8 else ""))
    if change.scope_removed:
        lines.append(f"SCOPE -{len(change.scope_removed):<3} {head}: {', '.join(change.scope_removed[:8])}"
                     + (" …" if len(change.scope_removed) > 8 else ""))
    for r in change.rewards:
        lines.append(f"REWARD    {head}: {r.severity} {money(r.before, r.currency)} → {money(r.after, r.currency)}")
    if lines:
        lines.append(f"          {p.url}")
    return lines


def _scan_impl(platforms: list[str] | None = None, full: bool = False, show_all: bool = False,
               as_json: bool = False) -> int:
    settings = _load_settings()
    if settings is None:
        return 1

    platforms = platforms or settings.enabled_platforms
    if not platforms:
        print("No platforms enabled in config.json — nothing to scan.")
        print(f"Enable some there, or pass --platform. Available: {sorted(sources.REGISTRY)}")
        return 0

    db = store.Store(settings.db_path)
    try:
        known = {p: db.known_programs(p) for p in platforms}
        results = sources.fetch_all(platforms, {} if full else known)

        summary: dict[str, dict] = {}
        changes: list[ProgramChanges] = []
        now = datetime.now(UTC).isoformat()
        with db.batch():
            for platform in platforms:
                result = results.get(platform) or sources.PlatformResult(error="no adapter registered")
                if result.error:
                    summary[platform] = {"error": result.error}
                    continue
                baseline = not known[platform]
                found: list[ProgramChanges] = []
                for program in result.programs:
                    previous, was_gone = db.record(program, now)
                    if not baseline:
                        change = diff_program(program, previous, returned=was_gone)
                        if change:
                            found.append(change)

                seen = {p.slug for p in result.programs}
                listed = db.listed_slugs(platform)
                missing = len(listed - seen)
                note = None
                if missing > len(listed) * GONE_GUARD_RATIO:
                    note = f"{missing} programs missing from this fetch — not marking them gone"
                else:
                    found += [ProgramChanges(p, gone=True) for p in db.mark_gone(platform, seen, now)]

                changes += found
                summary[platform] = {
                    "programs": len(result.programs),
                    "changed": len(found),
                    "baseline": baseline,
                    "note": note,
                }
            db.record_scan(now, summary, changes)
    finally:
        db.close()

    shown = changes if show_all else [c for c in changes if watchlist.matches(c.program, settings)]

    if as_json:
        print(json.dumps({"scanned_at": now, "platforms": summary,
                          "changes": [c.to_dict() for c in shown]}, indent=2))
    else:
        for platform, info in summary.items():
            if "error" in info:
                print(f"{platform:<10} ERROR  {info['error']}")
                continue
            state = "baseline stored" if info["baseline"] else f"{info['changed']} changed"
            print(f"{platform:<10} {info['programs']:>4} programs  {state}")
            if info["note"]:
                print(f"{'':<10} warning: {info['note']}")
        if changes:
            filtered = "" if show_all or not watchlist.is_active(settings) else \
                f" ({len(shown)} of {len(changes)} match the watchlist; --all shows every change)"
            print(f"\nChanges{filtered}:")
            for change in shown:
                for line in _describe(change):
                    print(f"  {line}")
        elif any(not info.get("error") and not info["baseline"] for info in summary.values()):
            print("\nNo changes since the last scan.")

    return 1 if any("error" in info for info in summary.values()) else 0


def scan(platforms: list[str] | None = None, full: bool = False, show_all: bool = False,
         as_json: bool = False) -> int:
    """Avoid overlapping GUI and CLI scans of the same database."""
    settings = _load_settings()
    if settings is None:
        return 1
    if not (platforms or settings.enabled_platforms):
        return _scan_impl(platforms, full, show_all, as_json)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(settings.db_path.parent / "scan.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            message = "A Bug Spray scan is already running."
            print(json.dumps({"error": message}) if as_json else message)
            return 1
        return _scan_impl(platforms, full, show_all, as_json)
    finally:
        os.close(fd)


# ---------------------------------------------------------------- list / show


def feed(as_json: bool = False) -> int:
    """Read the saved feed; this command never contacts a platform."""
    settings = _load_settings()
    if settings is None:
        return 1
    data = read_feed(settings)
    if as_json:
        print(json.dumps(data))
    else:
        print(f"{len(data['programs'])} watched programs; {len(data['changes'])} recent changes")
        if data["last_scan"]:
            print(f"Last scan: {data['last_scan']['scanned_at']}")
    return 0


def list_programs(platform: str | None = None, show_all: bool = False, limit: int = 50,
                  as_json: bool = False) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    db = store.Store(settings.db_path)
    try:
        programs = db.current_programs(platform)
    finally:
        db.close()

    total = len(programs)
    if not show_all:
        programs = [p for p in programs if watchlist.matches(p, settings)]
    programs.sort(key=lambda p: (p.active, p.max_reward_usd() or 0), reverse=True)
    if limit > 0:
        programs = programs[:limit]

    if as_json:
        print(json.dumps([asdict(p) for p in programs], indent=2))
        return 0
    if not total:
        print("No programs stored yet — run `scan` first.")
        return 0
    for p in programs:
        flag = " " if p.active else "⏸"
        print(f"{flag} {p.platform:<10} {p.name[:40]:<40} {reward_summary(p):>22}  "
              f"{scope_summary(p):>16}  {p.slug}")
    hidden = total - len(programs)
    if hidden:
        print(f"\n{len(programs)} shown of {total} stored"
              + ("" if show_all else " (watchlist and --limit apply; --all --limit 0 shows everything)"))
    return 0


def show(platform: str, slug: str, as_json: bool = False) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    db = store.Store(settings.db_path)
    try:
        payload = db.latest(platform, slug)
    finally:
        db.close()
    if payload is None:
        print(f"No stored program {platform}/{slug}. `list --all` shows what is stored.")
        return 1
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0

    p = Program.from_dict(payload)
    print(f"{p.name}  ({p.platform}/{p.slug})")
    print(f"  {p.url}")
    print(f"  status:  {'open' if p.active else 'paused'}   updated: {p.last_updated or '?'}")
    if p.tags:
        print(f"  tags:    {', '.join(p.tags)}")
    print("  rewards:")
    for r in p.rewards or []:
        if r.min_amount is None or r.max_amount is None:
            span = f"up to {money(r.top(), r.currency)}" if r.min_amount is None else f"from {money(r.min_amount, r.currency)}"
        elif r.min_amount == r.max_amount:
            span = money(r.max_amount, r.currency)
        else:
            span = f"{money(r.min_amount, r.currency)} – {money(r.max_amount, r.currency)}"
        print(f"    {r.severity:<14} {span}")
    if not p.rewards:
        print("    (no amount published)")
    print(f"  in scope ({len(p.scope.in_scope)}):")
    for asset in p.scope.in_scope:
        print(f"    + {asset}")
    if p.scope.out_of_scope:
        print(f"  out of scope ({len(p.scope.out_of_scope)}):")
        for asset in p.scope.out_of_scope:
            print(f"    - {asset}")
    print("\n  Always re-read the live program page before testing: a stored scope is not authorization.")
    return 0


# ---------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bug-spray", description="Bug bounty program radar.")
    parser.add_argument("--selftest", action="store_true", help="check wiring and exit (no network)")
    parser.add_argument("--version", action="version", version=f"bug-spray {__version__}")
    commands = parser.add_subparsers(dest="command")

    scan_p = commands.add_parser("scan", help="fetch platforms, store, print what changed")
    scan_p.add_argument("--platform", action="append", choices=config.ALL_PLATFORMS,
                        help="scan this platform (repeatable); default: enabled_platforms in config.json")
    scan_p.add_argument("--full", action="store_true",
                        help="re-fetch every program's detail, even if its platform says it is unchanged")
    scan_p.add_argument("--all", action="store_true", help="report every change, ignoring watchlist filters")
    scan_p.add_argument("--json", action="store_true", help="machine-readable output")

    list_p = commands.add_parser("list", help="stored programs, highest payout first")
    list_p.add_argument("--platform", choices=config.ALL_PLATFORMS)
    list_p.add_argument("--all", action="store_true", help="ignore watchlist filters")
    list_p.add_argument("--limit", type=int, default=50, help="0 = no limit (default 50)")
    list_p.add_argument("--json", action="store_true")

    show_p = commands.add_parser("show", help="one program's scope and rewards")
    show_p.add_argument("platform", choices=config.ALL_PLATFORMS)
    show_p.add_argument("slug")
    show_p.add_argument("--json", action="store_true")

    feed_p = commands.add_parser("feed", help="saved programs and recent changes (no network)")
    feed_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="  warning: %(message)s")

    if args.selftest:
        return selftest()
    if args.command == "list":
        return list_programs(args.platform, args.all, args.limit, args.json)
    if args.command == "show":
        return show(args.platform, args.slug, args.json)
    if args.command == "feed":
        return feed(args.json)
    if args.command == "scan":
        return scan(args.platform, args.full, args.all, args.json)
    return scan()


if __name__ == "__main__":
    sys.exit(main())
