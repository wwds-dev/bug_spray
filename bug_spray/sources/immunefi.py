"""Immunefi adapter — the public bounty feed, no API token.

    immunefi.com/public-api/bounties.json   every public bounty, assets and rewards inline

One request per scan. Invite-only programs are skipped; programs that hide
their assets are kept with an empty scope and an `assets-hidden` tag, so a
hidden scope never reads as "every asset was removed".
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from ..models import Program, Scope, merge_tiers
from . import register
from ._http import PoliteClient

PLATFORM = "immunefi"
FEED_URL = "https://immunefi.com/public-api/bounties.json"


def _ended(end_date: str | None) -> bool:
    if not end_date:
        return False
    try:
        return datetime.fromisoformat(end_date.replace("Z", "+00:00")) < datetime.now(UTC)
    except ValueError:
        return False


def parse_bounty(bounty: dict) -> Program | None:
    if bounty.get("inviteOnly"):
        return None
    slug = bounty.get("slug")
    if not slug:
        # One malformed entry must not raise and discard the whole single-request
        # feed; skip it and keep the rest.
        return None
    assets = bounty.get("assets") or []
    hidden = bool(bounty.get("hideAssetsInScope"))

    entries = []
    for reward in bounty.get("rewards") or []:
        if not reward.get("severity"):
            continue
        fixed = reward.get("fixedReward")
        low = reward.get("minReward", fixed if reward.get("rewardModel") == "fixed" else None)
        high = reward.get("maxReward", fixed)
        entries.append((reward["severity"].lower(), low, high))
    rewards = merge_tiers(entries, "USD") or merge_tiers([("any", None, bounty.get("maxBounty"))], "USD")

    tags = [a.get("type") for a in assets]
    for key in ("ecosystem", "language", "productType", "projectType"):
        tags += bounty.get(key) or []
    if hidden:
        tags.append("assets-hidden")

    return Program(
        platform=PLATFORM,
        slug=slug,
        name=bounty.get("project") or slug,
        url=f"https://immunefi.com/bug-bounty/{slug}/",
        active=not bounty.get("isPaused") and not _ended(bounty.get("endDate")),
        scope=Scope(in_scope=[] if hidden else [a.get("url") or "" for a in assets]),
        rewards=rewards,
        last_updated=bounty.get("updatedDate"),
        offers_bounties=True,
        tags=[t for t in tags if isinstance(t, str)],
    )


def fetch_programs(known: Mapping[str, Program] | None = None) -> list[Program]:
    # The feed is a single request carrying everything; nothing to reuse.
    with PoliteClient() as client:
        feed = client.get_json(FEED_URL)
    return [p for p in (parse_bounty(b) for b in feed) if p is not None]


register(PLATFORM, fetch_programs)
