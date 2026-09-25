"""Bugcrowd adapter — public engagement directory, no API token.

Three public JSON endpoints, the same ones bugcrowd.com's own pages call:

    /engagements.json?category=bug_bounty&page=N   the directory, 24 per page
    /engagements/<code>/changelog.json            brief versions, newest marked "Latest"
    /engagements/<code>/changelog/<id>.json       that brief: target groups + rewards

The changelog's publishedAt is the program's `last_updated`; when it matches the
stored copy the brief itself is not re-fetched. Private engagements never
appear in the public directory, so nothing here needs skipping for that.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..models import Program, Scope, merge_tiers
from . import detail_or_known, register
from ._http import PoliteClient, SourceError

PLATFORM = "bugcrowd"
BASE_URL = "https://bugcrowd.com"
MAX_PAGES = 100  # the directory is ~12 pages; this only stops a runaway loop

# Bugcrowd rates findings P1 (critical) .. P5 (informational, usually unpaid).
PRIORITY_SEVERITY = {"1": "critical", "2": "high", "3": "medium", "4": "low", "5": "informational"}


def parse_listing(engagement: dict) -> dict | None:
    """Pick the fields the adapter needs from a directory entry, or None to skip."""
    brief_url = engagement.get("briefUrl") or ""
    code = brief_url.rstrip("/").rsplit("/", 1)[-1]
    if not code or engagement.get("isPrivate") or engagement.get("isDemo"):
        return None
    return {
        "code": code,
        "name": engagement.get("name") or code,
        "url": BASE_URL + brief_url,
        "industry": engagement.get("industryName"),
    }


def latest_changelog(changelog: dict) -> dict:
    entries = changelog.get("changelogs") or []
    if not entries:
        raise SourceError("no published brief")
    return next((c for c in entries if c.get("changelogState") == "Latest"), entries[0])


def parse_brief(listing: dict, brief: dict, published_at: str | None) -> Program:
    data = brief.get("data") or {}
    in_scope, out_of_scope, tags, entries = [], [], [listing.get("industry")], []
    for group in data.get("scope") or []:
        targets = group.get("targets") or []
        names = [t.get("name") or t.get("uri") or "" for t in targets]
        if group.get("inScope"):
            in_scope += names
            tags += [t.get("category") for t in targets]
            tags += [tag.get("name") for t in targets for tag in t.get("tags") or []]
            for priority, span in (group.get("rewardRangeData") or {}).items():
                if priority in PRIORITY_SEVERITY and isinstance(span, dict):
                    entries.append((PRIORITY_SEVERITY[priority], span.get("min"), span.get("max")))
        else:
            out_of_scope += names

    engagement = data.get("engagement") or {}
    return Program(
        platform=PLATFORM,
        slug=listing["code"],
        name=listing["name"],
        url=listing["url"],
        active=engagement.get("state", "in_progress") == "in_progress" and not brief.get("pausedReason"),
        scope=Scope(in_scope=in_scope, out_of_scope=out_of_scope),
        rewards=merge_tiers(entries, "USD"),
        last_updated=published_at,
        offers_bounties=True,
        tags=[t for t in tags if t],
    )


def _directory(client: PoliteClient) -> list[dict]:
    engagements: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        body = client.get_json(f"{BASE_URL}/engagements.json", category="bug_bounty", page=page)
        batch = body.get("engagements") or []
        engagements += batch
        total = (body.get("paginationMeta") or {}).get("totalCount") or 0
        if not batch or len(engagements) >= total:
            break
    return engagements


def fetch_programs(known: Mapping[str, Program] | None = None) -> list[Program]:
    known = known or {}
    programs: list[Program] = []
    with PoliteClient() as client:
        for engagement in _directory(client):
            listing = parse_listing(engagement)
            if listing is None:
                continue

            def build(listing=listing) -> Program:
                code = listing["code"]
                entry = latest_changelog(
                    client.get_json(f"{BASE_URL}/engagements/{code}/changelog.json")
                )
                published = entry.get("publishedAt")
                previous = known.get(code)
                if previous and previous.last_updated == published:
                    return previous
                path = entry.get("changelogShowUrl") or f"/engagements/{code}/changelog/{entry['id']}"
                return parse_brief(listing, client.get_json(f"{BASE_URL}{path}.json"), published)

            program = detail_or_known(PLATFORM, listing["code"], known, build)
            if program:
                programs.append(program)
    return programs


register(PLATFORM, fetch_programs)
