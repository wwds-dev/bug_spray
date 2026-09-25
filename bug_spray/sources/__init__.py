"""Source adapters — one module per bug bounty platform.

Every adapter exposes a single function:

    fetch_programs(known: Mapping[str, Program]) -> list[Program]

using only that platform's public, unauthenticated program directory. `known`
is the last stored snapshot per slug; an adapter may reuse a known program's
scope and rewards instead of re-fetching its detail page when the platform
says nothing changed (same `last_updated`). Pass `{}` to force a full fetch.

Two rules every adapter follows:
- Only bounty-paying, publicly listed programs are returned. Invite-only and
  login-walled programs are skipped, not scraped.
- If a program's detail request fails, the adapter returns the known copy
  unchanged (or skips a program it has never seen) rather than a program with
  an empty scope — an empty scope would read as "every asset was removed".

No adapter here performs recon or touches a program's actual assets — that's
a separate, scope-gated concern (see SUGGESTIONS.md, "Recon automation").
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..models import Program
from ._http import SourceError

log = logging.getLogger(__name__)

FetchFn = Callable[[Mapping[str, Program]], list[Program]]
REGISTRY: dict[str, FetchFn] = {}


def register(platform: str, fetch_fn: FetchFn) -> None:
    REGISTRY[platform] = fetch_fn


def detail_or_known(
    platform: str, slug: str, known: Mapping[str, Program], build: Callable[[], Program]
) -> Program | None:
    """Build a program from its detail request; on failure fall back to the known copy.

    Returns None (skip) for a program that has never been stored — better to
    pick it up next run than to store it with a scope we failed to read.
    """
    try:
        return build()
    except (SourceError, KeyError, TypeError, ValueError) as exc:
        log.warning("%s/%s: detail fetch failed, keeping last known copy (%s)", platform, slug, exc)
        return known.get(slug)


@dataclass
class PlatformResult:
    programs: list[Program] = field(default_factory=list)
    error: str | None = None


def fetch_all(
    platforms: list[str], known: Mapping[str, Mapping[str, Program]] | None = None
) -> dict[str, PlatformResult]:
    """Fetch each requested platform that has a registered adapter.

    Platforms run in parallel (each against its own host), and one platform
    failing — network, rate limit, or an API that changed shape — is reported
    in its result instead of aborting the others.
    """
    known = known or {}
    wanted = [p for p in platforms if p in REGISTRY]

    def run(platform: str) -> PlatformResult:
        try:
            return PlatformResult(REGISTRY[platform](known.get(platform, {})))
        except Exception as exc:  # noqa: BLE001 — adapter boundary, reported per platform
            return PlatformResult(error=f"{type(exc).__name__}: {exc}")

    if not wanted:
        return {}
    with ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        return dict(zip(wanted, pool.map(run, wanted), strict=True))


# Imported last: each adapter module registers itself on import.
from . import bugcrowd, hackerone, immunefi, intigriti, yeswehack  # noqa: E402,F401
