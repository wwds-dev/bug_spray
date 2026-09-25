"""YesWeHack adapter — public program API, no API token.

    api.yeswehack.com/programs?page=N   listing, paged
    api.yeswehack.com/programs/<slug>   detail: scopes + reward grid

Only public, bounty-paying, live programs are kept. The detail is re-fetched
only when the listing's `last_update_at` differs from the stored copy.
YesWeHack's out-of-scope section is prose rules rather than assets, so it is
not copied into `out_of_scope`.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Program, Scope, merge_tiers
from . import detail_or_known, register
from ._http import PoliteClient

PLATFORM = "yeswehack"
API_URL = "https://api.yeswehack.com/programs"
MAX_PAGES = 50

GRID_SEVERITIES = ("critical", "high", "medium", "low")


def is_listed(entry: dict) -> bool:
    return (
        entry.get("public", False)
        and entry.get("bounty", False)
        and not entry.get("disabled")
        and not entry.get("archived")
        and not entry.get("demo")
    )


def parse_listing(entry: dict) -> Program:
    currency = ((entry.get("business_unit") or {}).get("currency") or "EUR").upper()
    return Program(
        platform=PLATFORM,
        slug=entry["slug"],
        name=entry.get("title") or entry["slug"],
        url=f"https://yeswehack.com/programs/{entry['slug']}",
        active=True,
        scope=Scope(),
        rewards=merge_tiers(
            [("any", entry.get("bounty_reward_min"), entry.get("bounty_reward_max"))], currency
        ),
        last_updated=entry.get("last_update_at"),
        offers_bounties=True,
        tags=[entry.get("activity_area"), entry.get("type")],
    )


def parse_detail(listed: Program, detail: dict) -> Program:
    scopes = detail.get("scopes") or []
    tags = list(listed.tags) + [s.get("scope_type") for s in scopes]
    for tag in detail.get("tags") or []:
        tags.append(tag.get("name") if isinstance(tag, dict) else tag)

    currency = listed.rewards[0].currency if listed.rewards else "EUR"
    grid = detail.get("reward_grid_default") or {}
    rewards = merge_tiers(
        [(sev, grid.get(f"bounty_{sev}"), grid.get(f"bounty_{sev}")) for sev in GRID_SEVERITIES],
        currency,
    ) or listed.rewards
    return Program(
        platform=listed.platform,
        slug=listed.slug,
        name=listed.name,
        url=listed.url,
        active=listed.active,
        scope=Scope(in_scope=[s.get("scope") or "" for s in scopes]),
        rewards=rewards,
        last_updated=listed.last_updated,
        offers_bounties=True,
        tags=[t for t in tags if isinstance(t, str)],
    )


def _listing(client: PoliteClient) -> list[dict]:
    entries: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        body = client.get_json(API_URL, page=page)
        entries += body.get("items") or []
        if page >= ((body.get("pagination") or {}).get("nb_pages") or 1):
            break
    return entries


def fetch_programs(known: Mapping[str, Program] | None = None) -> list[Program]:
    known = known or {}
    programs: list[Program] = []
    with PoliteClient() as client:
        for entry in _listing(client):
            if not is_listed(entry):
                continue
            listed = parse_listing(entry)
            previous = known.get(listed.slug)
            if previous and previous.last_updated == listed.last_updated:
                programs.append(previous)
                continue
            program = detail_or_known(
                PLATFORM,
                listed.slug,
                known,
                lambda listed=listed: parse_detail(
                    listed, client.get_json(f"{API_URL}/{listed.slug}")
                ),
            )
            if program:
                programs.append(program)
    return programs


register(PLATFORM, fetch_programs)
