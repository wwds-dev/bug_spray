"""HackerOne adapter — the public program directory, no API token.

HackerOne's documented Hacker API (`api.hackerone.com/v1/hackers/...`) needs a
username + token even for public programs. The public directory at
hackerone.com/directory is served by the site's GraphQL endpoint, which answers
anonymously for public programs, so that is what this reads: one paged query
returns name, state, bounty table and structured scope for 100 programs at a
time. Programs with more than 100 scope entries get follow-up scope pages.

GraphQL here is the website's, not a versioned public API — if HackerOne
changes a field name the scan reports a HackerOne error and the other
platforms carry on.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Program, Scope, merge_tiers
from . import detail_or_known, register
from ._http import PoliteClient, SourceError

PLATFORM = "hackerone"
GRAPHQL_URL = "https://hackerone.com/graphql"
PAGE_SIZE = 100
# Ceiling on directory / scope pages, mirroring the other adapters' MAX_PAGES.
# At 100 programs per page this is far above the real directory size and only
# stops a runaway loop from an unversioned endpoint.
MAX_PAGES = 500

_SCOPE_FIELDS = "pageInfo { hasNextPage endCursor } edges { node { asset_identifier asset_type eligible_for_submission } }"

DIRECTORY_QUERY = (
    "query Directory($cursor: String) { teams(first: %d, after: $cursor, "
    "secure_order_by: {started_accepting_at: {_direction: DESC}}, "
    "where: {_and: [{_or: [{submission_state: {_eq: open}}, {submission_state: {_eq: paused}}]}, "
    "{state: {_eq: public_mode}}, {offers_bounties: {_eq: true}}]}) { "
    "pageInfo { hasNextPage endCursor } edges { node { "
    "handle name url offers_bounties submission_state last_updated_at currency base_bounty "
    "bounty_table { bounty_table_rows(first: 50) { nodes { low medium high critical } } } "
    "structured_scopes(first: %d, archived: false) { %s } } } } }"
) % (PAGE_SIZE, PAGE_SIZE, _SCOPE_FIELDS)

SCOPE_QUERY = (
    "query Scope($handle: String!, $cursor: String) { team(handle: $handle) { "
    "structured_scopes(first: %d, after: $cursor, archived: false) { %s } } }"
) % (PAGE_SIZE, _SCOPE_FIELDS)


def parse_team(node: dict, scope_nodes: list[dict]) -> Program:
    in_scope, out_of_scope, asset_types = [], [], []
    for scope in scope_nodes:
        asset = scope.get("asset_identifier") or ""
        (in_scope if scope.get("eligible_for_submission") else out_of_scope).append(asset)
        if scope.get("eligible_for_submission") and scope.get("asset_type"):
            asset_types.append(scope["asset_type"])

    currency = (node.get("currency") or "usd").upper()
    rows = ((node.get("bounty_table") or {}).get("bounty_table_rows") or {}).get("nodes") or []
    entries = [
        (severity, row.get(severity), row.get(severity))
        for row in rows
        for severity in ("critical", "high", "medium", "low")
    ]
    rewards = merge_tiers(entries, currency)
    if not rewards and node.get("base_bounty"):
        # No published table: the minimum bounty is the only figure there is.
        rewards = merge_tiers([("any", node["base_bounty"], None)], currency)

    handle = node["handle"]
    return Program(
        platform=PLATFORM,
        slug=handle,
        name=node.get("name") or handle,
        url=node.get("url") or f"https://hackerone.com/{handle}",
        active=node.get("submission_state") == "open",
        scope=Scope(in_scope=in_scope, out_of_scope=out_of_scope),
        rewards=rewards,
        last_updated=node.get("last_updated_at"),
        offers_bounties=bool(node.get("offers_bounties")),
        tags=asset_types,
    )


def _graphql(client: PoliteClient, query: str, variables: dict) -> dict:
    body = client.post_json(GRAPHQL_URL, {"query": query, "variables": variables})
    if body.get("errors"):
        raise SourceError(f"HackerOne GraphQL error: {body['errors'][0].get('message')}")
    return body["data"]


def _remaining_scopes(client: PoliteClient, handle: str, cursor: str) -> list[dict]:
    nodes: list[dict] = []
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        # The site GraphQL is unversioned; guard against a repeating or empty
        # endCursor with hasNextPage=true (an infinite loop otherwise).
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
        data = _graphql(client, SCOPE_QUERY, {"handle": handle, "cursor": cursor})
        page = data["team"]["structured_scopes"]
        nodes += [edge["node"] for edge in page["edges"]]
        cursor = page["pageInfo"]["endCursor"] if page["pageInfo"]["hasNextPage"] else None
    return nodes


def fetch_programs(known: Mapping[str, Program] | None = None) -> list[Program]:
    # The directory query already carries scope and rewards, so `known` is
    # only the fallback for a program whose extra scope pages fail.
    known = known or {}
    programs: list[Program] = []
    cursor = None
    seen_cursors: set[str] = set()
    with PoliteClient() as client:
        for _ in range(MAX_PAGES):
            teams = _graphql(client, DIRECTORY_QUERY, {"cursor": cursor})["teams"]
            for edge in teams["edges"]:
                node = edge["node"]
                scopes = node["structured_scopes"]
                scope_nodes = [e["node"] for e in scopes["edges"]]
                if not scopes["pageInfo"]["hasNextPage"]:
                    programs.append(parse_team(node, scope_nodes))
                    continue
                program = detail_or_known(
                    PLATFORM,
                    node["handle"],
                    known,
                    lambda node=node, first=scope_nodes, after=scopes["pageInfo"]["endCursor"]: parse_team(
                        node, first + _remaining_scopes(client, node["handle"], after)
                    ),
                )
                if program:
                    programs.append(program)
            info = teams["pageInfo"]
            cursor = info["endCursor"]
            # Stop on the last page, or if the unversioned endpoint reports
            # hasNextPage=true with a repeating/empty cursor (would loop forever).
            if not info["hasNextPage"] or not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
    return programs


register(PLATFORM, fetch_programs)
