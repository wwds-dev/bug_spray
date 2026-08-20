"""Bug Spray CLI.

    python main.py --selftest        check config/store/adapters wire up, no network
    python main.py scan              fetch enabled platforms, store, print what changed

No command here performs recon or touches a program's actual assets — see
the honest-boundary section in README.md.
"""

from __future__ import annotations

import argparse
import sys

from . import config, secrets, sources, store
from .sources import hackerone as _hackerone  # noqa: F401  (registers the adapter)


def selftest() -> int:
    settings = config.load()
    problems = settings.validate()

    print("bug_spray self-test")
    print(f"  config path:      {config.CONFIG_PATH}")
    print(f"  db path:          {settings.db_path}")
    print(f"  enabled platforms: {settings.enabled_platforms or '(none configured)'}")
    print(f"  registered adapters: {sorted(sources.REGISTRY)}")
    print(f"  keyring backend:  {secrets.backend_name()}")

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


def scan() -> int:
    settings = config.load()
    problems = settings.validate()
    if problems:
        print("Config problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if not settings.enabled_platforms:
        print("No platforms enabled in config.json — nothing to scan.")
        print(f"Available adapters: {sorted(sources.REGISTRY)}")
        return 0

    results = sources.fetch_all(settings.enabled_platforms)
    db = store.Store(settings.db_path)
    try:
        for platform, programs in results.items():
            for program in programs:
                current_payload = {"scope": {"in_scope": program.scope.in_scope}}
                _, previous = db.latest_two(platform, program.slug)
                db.save(program)
                diff = store.diff_scope(current_payload, previous)
                if diff["added"] or diff["removed"]:
                    print(f"[{platform}] {program.name}: scope changed {diff}")
    finally:
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bug-spray")
    parser.add_argument("--selftest", action="store_true", help="check wiring and exit")
    parser.add_argument("command", nargs="?", default="scan", choices=["scan"])
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.command == "scan":
        return scan()
    return 0


if __name__ == "__main__":
    sys.exit(main())
