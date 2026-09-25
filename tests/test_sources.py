"""Adapter tests against trimmed copies of real platform responses (tests/fixtures/).

No network: each module's PoliteClient is swapped for a fake that serves the
fixture for a URL and records which URLs were asked for, so the tests also
cover the "reuse the stored copy when unchanged" path.
"""

import json
from pathlib import Path

import pytest

from bug_spray import sources
from bug_spray.models import Program, RewardTier, Scope
from bug_spray.sources import bugcrowd, hackerone, immunefi, intigriti, yeswehack
from bug_spray.sources._http import SourceError

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def _serve(self, url):
        self.calls.append(url)
        for fragment, response in self.routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response
        raise SourceError(f"unexpected URL in test: {url}")

    def get_json(self, url, **params):
        return self._serve(url)

    def post_json(self, url, payload):
        return self._serve(url)


@pytest.fixture
def fake(monkeypatch):
    def install(module, routes):
        client = FakeClient(routes)
        monkeypatch.setattr(module, "PoliteClient", lambda: client)
        return client

    return install


def test_every_platform_has_an_adapter():
    from bug_spray.config import ALL_PLATFORMS

    assert set(sources.REGISTRY) == set(ALL_PLATFORMS)


# ---------------------------------------------------------------- HackerOne


def test_hackerone_parses_scope_and_bounty_table(fake):
    fake(hackerone, {"graphql": fixture("hackerone_directory.json")})
    [program] = hackerone.fetch_programs({})
    assert program.platform == "hackerone" and program.slug == "common_codes"
    assert program.active and program.offers_bounties
    assert "d-you Wallet iOS Test" in program.scope.in_scope
    assert all(a.startswith("OOS:") for a in program.scope.out_of_scope)
    critical = next(r for r in program.rewards if r.severity == "critical")
    assert (critical.min_amount, critical.max_amount, critical.currency) == (10000, 15000, "USD")


def test_hackerone_without_table_falls_back_to_base_bounty():
    node = {"handle": "x", "name": "X", "submission_state": "paused", "currency": "usd",
            "base_bounty": 100, "offers_bounties": True, "bounty_table": None}
    program = hackerone.parse_team(node, [])
    assert not program.active
    assert [(r.severity, r.min_amount, r.max_amount) for r in program.rewards] == [("any", 100.0, None)]


def test_hackerone_graphql_error_is_a_source_error(fake):
    fake(hackerone, {"graphql": {"errors": [{"message": "field renamed"}]}})
    with pytest.raises(SourceError, match="field renamed"):
        hackerone.fetch_programs({})


# ---------------------------------------------------------------- Bugcrowd


def _bugcrowd_routes():
    return {
        "engagements.json": fixture("bugcrowd_engagements.json"),
        "changelog.json": fixture("bugcrowd_changelog.json"),
        "/changelog/": fixture("bugcrowd_brief.json"),
    }


def test_bugcrowd_parses_brief(fake):
    client = fake(bugcrowd, _bugcrowd_routes())
    programs = bugcrowd.fetch_programs({})
    assert len(programs) == 2
    program = programs[0]
    assert "app.web.com" in program.scope.in_scope
    assert program.scope.out_of_scope, "out-of-scope target group should be kept"
    critical = next(r for r in program.rewards if r.severity == "critical")
    assert (critical.min_amount, critical.max_amount) == (2000, 3000)
    assert program.last_updated == fixture("bugcrowd_changelog.json")["changelogs"][0]["publishedAt"]
    assert sum("/changelog/" in url for url in client.calls) == 2


def test_bugcrowd_reuses_known_program_when_brief_unchanged(fake):
    fake(bugcrowd, _bugcrowd_routes())
    known = {p.slug: p for p in bugcrowd.fetch_programs({})}
    client = fake(bugcrowd, _bugcrowd_routes())
    again = bugcrowd.fetch_programs(known)
    assert [p.slug for p in again] == list(known)
    assert not any("/changelog/" in url for url in client.calls), "brief should not be re-fetched"


def test_bugcrowd_failed_detail_keeps_known_and_skips_unknown(fake):
    routes = _bugcrowd_routes()
    fake(bugcrowd, routes)
    known_one = bugcrowd.fetch_programs({})[0]
    routes["changelog.json"] = SourceError("HTTP 503")
    fake(bugcrowd, routes)
    programs = bugcrowd.fetch_programs({known_one.slug: known_one})
    assert programs == [known_one]


# ---------------------------------------------------------------- Intigriti


def _intigriti_routes():
    return {
        "programs/digitalocean/digitalocean": fixture("intigriti_detail.json"),
        "public/programs": fixture("intigriti_programs.json"),
    }


def test_intigriti_public_registered_and_vdp(fake):
    client = fake(intigriti, _intigriti_routes())
    programs = {p.slug: p for p in intigriti.fetch_programs({})}

    assert not any(slug.endswith("/grafanalabsvdp") for slug in programs), "zero-bounty programs are skipped"

    do = programs["digitalocean/digitalocean"]
    assert "api.digitalocean.com" in do.scope.in_scope
    assert "*.snapshooter.com" in do.scope.out_of_scope  # tier 5 = out of scope
    assert {"wildcard", "ip-range", "url"} <= set(do.tags)
    assert {r.severity for r in do.rewards} >= {"low", "critical"}

    registered = next(p for p in programs.values() if "registered-only" in p.tags)
    assert registered.scope.in_scope == [] and registered.rewards[0].severity == "any"
    assert sum("/programs/" in url for url in client.calls) == 1, "only public programs get a detail request"


def test_intigriti_terms_or_2fa_programs_get_no_detail_request(fake):
    entry = dict(fixture("intigriti_programs.json")[0], tacRequired=True)
    client = fake(intigriti, {"public/programs": [entry]})
    [program] = intigriti.fetch_programs({})
    assert "terms-required" in program.tags and program.scope.in_scope == []
    assert len(client.calls) == 1


def test_intigriti_uses_newest_live_asset_version():
    detail = fixture("intigriti_detail.json")
    listed = intigriti.parse_listing(fixture("intigriti_programs.json")[0])
    future = {"createdAt": 4_000_000_000, "content": {"assetsAndGroups": [{"name": "future.example", "bountyTierId": 3}]}}
    detail["assetsCollection"].append(future)
    program = intigriti.parse_detail(listed, detail)
    assert "future.example" not in program.scope.in_scope


# ---------------------------------------------------------------- YesWeHack


def test_yeswehack_lists_paying_public_programs_only(fake):
    client = fake(yeswehack, {
        "programs/datadome-bot-bounty": fixture("yeswehack_detail.json"),
        "yeswehack.com/programs": fixture("yeswehack_programs.json"),
    })
    [program] = yeswehack.fetch_programs({})
    assert program.slug == "datadome-bot-bounty"
    assert "*.captcha-delivery.com" in program.scope.in_scope
    critical = next(r for r in program.rewards if r.severity == "critical")
    assert (critical.max_amount, critical.currency) == (5000, "EUR")
    assert sum(url.endswith("datadome-bot-bounty") for url in client.calls) == 1

    client = fake(yeswehack, client.routes)
    yeswehack.fetch_programs({program.slug: program})
    assert not any(url.endswith("datadome-bot-bounty") for url in client.calls)


# ---------------------------------------------------------------- Immunefi


def test_immunefi_rewards_and_invite_only(fake):
    fake(immunefi, {"bounties.json": fixture("immunefi_bounties.json")})
    programs = {p.slug: p for p in immunefi.fetch_programs({})}
    assert "tetu" not in programs  # invite-only
    oz = programs["openzeppelin"]
    tiers = {r.severity: (r.min_amount, r.max_amount) for r in oz.rewards}
    assert tiers["critical"] == (5000, 25000)
    assert tiers["medium"] == (2500, 2500)  # fixed reward
    arb = programs["arbitrum"]
    assert {r.severity: (r.min_amount, r.max_amount) for r in arb.rewards}["critical"] == (None, 2000000)


def test_immunefi_hidden_assets_are_tagged_not_emptied_silently():
    program = immunefi.parse_bounty({"slug": "h", "project": "H", "hideAssetsInScope": True,
                                     "assets": [{"url": "https://x", "type": "smart_contract"}],
                                     "rewards": [], "maxBounty": 1000})
    assert program.scope.in_scope == [] and "assets-hidden" in program.tags
    assert program.rewards == [RewardTier("any", None, 1000.0, "USD")]


def test_immunefi_ended_program_is_inactive():
    program = immunefi.parse_bounty({"slug": "e", "endDate": "2020-01-01T00:00:00.000Z", "assets": []})
    assert not program.active


# ---------------------------------------------------------------- fetch_all


def test_fetch_all_isolates_a_failing_platform(monkeypatch):
    ok = Program("hackerone", "a", "A", "u", True, Scope())
    monkeypatch.setitem(sources.REGISTRY, "hackerone", lambda known: [ok])
    monkeypatch.setitem(sources.REGISTRY, "bugcrowd", lambda known: (_ for _ in ()).throw(KeyError("teams")))
    results = sources.fetch_all(["hackerone", "bugcrowd"])
    assert results["hackerone"].programs == [ok] and results["hackerone"].error is None
    assert "KeyError" in results["bugcrowd"].error
