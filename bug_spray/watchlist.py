"""Watchlist filters — which programs the feed shows.

Every program is stored whatever the filters say, so changing a filter later
still has full history to diff against. Filters only narrow what `scan`
reports and what `list` prints.

Each filter that is set must match (AND); within one filter any value may
match (OR). An empty filter is not applied.

- `watchlist_keywords` — case-insensitive substring of the program's name,
  slug, tags or any in-scope asset.
- `watchlist_tags` — exact tag, case-insensitive (see `list` output for tags).
- `min_reward_usd` — the program's top published payout, converted with
  `models.APPROX_USD_RATE`. A program with no published amount, or in a
  currency with no rate, does not pass a non-zero minimum.
"""

from __future__ import annotations

from .config import Settings
from .models import Program


def is_active(settings: Settings) -> bool:
    return bool(settings.watchlist_keywords or settings.watchlist_tags or settings.min_reward_usd > 0)


def matches(program: Program, settings: Settings) -> bool:
    if settings.min_reward_usd > 0:
        usd = program.max_reward_usd()
        if usd is None or usd < settings.min_reward_usd:
            return False

    if settings.watchlist_tags:
        wanted = {t.strip().lower() for t in settings.watchlist_tags}
        if not wanted & set(program.tags):
            return False

    if settings.watchlist_keywords:
        haystack = "\n".join(
            [program.name, program.slug, *program.tags, *program.scope.in_scope]
        ).lower()
        if not any(k.strip().lower() in haystack for k in settings.watchlist_keywords if k.strip()):
            return False

    return True
