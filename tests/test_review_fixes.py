"""Regression tests for the ultra code-review fixes."""

import httpx

from bug_spray.changes import ProgramChanges, diff_rewards
from bug_spray.cli import _describe
from bug_spray.models import Program, RewardTier, Scope
from bug_spray.sources._http import _retry_after
from bug_spray.sources.immunefi import parse_bounty


def _program(rewards, platform="hackerone", slug="acme"):
    return Program(platform=platform, slug=slug, name="Acme", url="https://x",
                   active=True, scope=Scope(), rewards=rewards)


def test_retry_after_clamps_negative_to_zero():
    # A negative Retry-After must not reach time.sleep() (ValueError).
    resp = httpx.Response(503, headers={"Retry-After": "-5"})
    assert _retry_after(resp, default=2.0) == 0.0
    # And it is still capped above.
    assert _retry_after(httpx.Response(503, headers={"Retry-After": "999"}), 2.0) == 60.0


def test_currency_switch_renders_both_currencies():
    previous = _program([RewardTier("critical", None, 1000, "USD")])
    current = _program([RewardTier("critical", None, 1000, "EUR")])
    changes = diff_rewards(current, previous)
    assert len(changes) == 1
    change = changes[0]
    assert change.before_currency == "USD" and change.after_currency == "EUR"
    text = "\n".join(_describe(ProgramChanges(current, rewards=changes)))
    assert "$1,000" in text and "€1,000" in text


def test_immunefi_missing_slug_is_skipped_not_raised():
    # One malformed entry must not raise and discard the whole feed.
    assert parse_bounty({"project": "no slug here"}) is None
