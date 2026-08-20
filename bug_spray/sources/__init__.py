"""Source adapters — one module per bug bounty platform.

Every adapter exposes a single function:

    fetch_programs() -> list[Program]

using only that platform's public, unauthenticated (or Keychain-token-backed)
API. No adapter here performs recon or touches a program's actual assets —
that's a separate, scope-gated concern (see SUGGESTIONS.md, "Recon
automation"). This package only reads program *metadata*.

None of the adapters below are implemented yet — see TODO.md v1.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import Program

# Populated as each adapter module is implemented and registered below.
REGISTRY: dict[str, Callable[[], list[Program]]] = {}


def register(platform: str, fetch_fn: Callable[[], list[Program]]) -> None:
    REGISTRY[platform] = fetch_fn


def fetch_all(platforms: list[str]) -> dict[str, list[Program]]:
    """Fetch programs for each requested platform that has a registered adapter."""
    results: dict[str, list[Program]] = {}
    for platform in platforms:
        fetch_fn = REGISTRY.get(platform)
        if fetch_fn is None:
            continue
        results[platform] = fetch_fn()
    return results
