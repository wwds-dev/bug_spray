"""Intigriti adapter — public program listing, no API token.

    app.intigriti.com/api/core/public/programs                      every listed program
    app.intigriti.com/api/core/public/programs/<company>/<handle>   detail, public programs only

The listing covers every program's bounty range and status. Three kinds of
program answer the detail request with a login wall (HTTP 403): confidentiality
"registered researchers only", terms-and-conditions acceptance required, and
2FA required. For those the listing is all there is — they are stored with
their bounty range, an empty scope, and a tag saying why (`registered-only`,
`terms-required`, `2fa-required`), and no detail request is made.

Assets and bounty tables are versioned (a list with `createdAt`); the newest
version already in effect is the current one.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, datetime

from ..models import Program, Scope, merge_tiers
from . import detail_or_known, register
from ._http import PoliteClient

PLATFORM = "intigriti"
LIST_URL = "https://app.intigriti.com/api/core/public/programs"

STATUS_OPEN, STATUS_SUSPENDED = 3, 4
CONFIDENTIALITY_PUBLIC = 4
TIER_OUT_OF_SCOPE = 5  # tier 1 is "in scope, no bounty"; 2-4, 6, 7 pay

# Asset typeIds as observed in the public API. Unlisted ids get no tag rather
# than a guessed one.
ASSET_TYPES = {
    1: "url", 2: "android", 3: "ios", 4: "ip-range", 6: "other", 7: "wildcard", 8: "open-source",
}


def _iso(epoch) -> str | None:
    return datetime.fromtimestamp(epoch, UTC).isoformat() if epoch else None


def _severity(max_score: float | None) -> str:
    score = max_score or 0
    if score < 4:
        return "low"
    if score < 7:
        return "medium"
    if score < 9:
        return "high"
    return "critical"


def _current(versions: list[dict]) -> dict:
    """Newest version already in effect (a future-dated one is not live yet)."""
    if not versions:
        return {}
    now = time.time()
    live = [v for v in versions if (v.get("createdAt") or 0) <= now] or versions
    return max(live, key=lambda v: v.get("createdAt") or 0).get("content") or {}


def login_walled(entry: dict) -> list[str]:
    """Why this program's detail needs a login, as tags; empty = detail is public."""
    reasons = []
    if entry.get("confidentialityLevel") != CONFIDENTIALITY_PUBLIC:
        reasons.append("registered-only")
    if entry.get("tacRequired"):
        reasons.append("terms-required")
    if entry.get("twoFactorRequired"):
        reasons.append("2fa-required")
    return reasons


def is_listed(entry: dict) -> bool:
    paying = ((entry.get("maxBounty") or {}).get("value") or 0) > 0
    return paying and entry.get("status") in (STATUS_OPEN, STATUS_SUSPENDED)


def parse_listing(entry: dict) -> Program:
    company, handle = entry["companyHandle"], entry["handle"]
    low, high = entry.get("minBounty") or {}, entry.get("maxBounty") or {}
    currency = high.get("currency") or low.get("currency") or "EUR"
    tags = [entry.get("industry"), *login_walled(entry)]
    return Program(
        platform=PLATFORM,
        slug=f"{company}/{handle}",
        name=entry.get("name") or handle,
        url=f"https://app.intigriti.com/programs/{company}/{handle}/detail",
        active=entry.get("status") == STATUS_OPEN,
        scope=Scope(),
        rewards=merge_tiers([("any", low.get("value"), high.get("value"))], currency),
        last_updated=_iso(entry.get("lastUpdatedAt")),
        offers_bounties=True,
        tags=tags,
    )


def parse_detail(listed: Program, detail: dict) -> Program:
    in_scope, out_of_scope, tags = [], [], list(listed.tags)
    for item in _current(detail.get("assetsCollection") or []).get("assetsAndGroups") or []:
        for asset in item.get("assets") or [item]:  # a group holds assets; a bare asset is its own
            name = asset.get("name") or ""
            if asset.get("bountyTierId") == TIER_OUT_OF_SCOPE:
                out_of_scope.append(name)
            else:
                in_scope.append(name)
                tags.append(ASSET_TYPES.get(asset.get("typeId")))

    table = _current(detail.get("bountyTables") or [])
    entries = [
        (_severity(span.get("maxScore")), (span.get("minBounty") or {}).get("value"),
         (span.get("maxBounty") or {}).get("value"))
        for row in table.get("bountyRows") or []
        for span in row.get("bountyRanges") or []
    ]
    fallback_currency = listed.rewards[0].currency if listed.rewards else "EUR"
    rewards = merge_tiers(entries, table.get("currency") or fallback_currency) or listed.rewards
    return Program(
        platform=listed.platform,
        slug=listed.slug,
        name=listed.name,
        url=listed.url,
        active=listed.active,
        scope=Scope(in_scope=in_scope, out_of_scope=out_of_scope),
        rewards=rewards,
        last_updated=listed.last_updated,
        offers_bounties=True,
        tags=[t for t in tags if t],
    )


def fetch_programs(known: Mapping[str, Program] | None = None) -> list[Program]:
    known = known or {}
    programs: list[Program] = []
    with PoliteClient() as client:
        for entry in client.get_json(LIST_URL):
            if not is_listed(entry):
                continue
            listed = parse_listing(entry)
            if login_walled(entry):
                programs.append(listed)
                continue
            previous = known.get(listed.slug)
            if previous and previous.last_updated == listed.last_updated:
                programs.append(previous)
                continue
            program = detail_or_known(
                PLATFORM,
                listed.slug,
                known,
                lambda listed=listed: parse_detail(
                    listed, client.get_json(f"{LIST_URL}/{listed.slug}")
                ),
            )
            if program:
                programs.append(program)
    return programs


register(PLATFORM, fetch_programs)
