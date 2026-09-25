"""Program / Scope / RewardTier — the shape every source adapter returns.

Every field added after v0 has a default, so a snapshot stored by an older
version still loads through `Program.from_dict`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

# Severity labels adapters normalise to, most severe first. "any" is for
# platforms that publish a single range rather than a per-severity table.
SEVERITIES = ["critical", "high", "medium", "low", "informational", "any"]

# Rough conversion so `min_reward_usd` can compare a EUR program against a USD
# one. This is a watchlist filter, not accounting — approximate is fine, and a
# currency missing here makes the reward count as unknown rather than guessed.
APPROX_USD_RATE = {"USD": 1.0, "EUR": 1.1, "GBP": 1.3, "CHF": 1.15}


@dataclass
class RewardTier:
    severity: str
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"

    def top(self) -> float | None:
        return self.max_amount if self.max_amount is not None else self.min_amount


@dataclass
class Scope:
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Sorted and de-duplicated so two fetches of an unchanged program
        # compare equal whatever order the platform returned assets in.
        self.in_scope = sorted({a.strip() for a in self.in_scope if a and a.strip()})
        self.out_of_scope = sorted({a.strip() for a in self.out_of_scope if a and a.strip()})


@dataclass
class Program:
    platform: str
    slug: str
    name: str
    url: str
    active: bool
    scope: Scope
    rewards: list[RewardTier] = field(default_factory=list)
    last_updated: str | None = None
    offers_bounties: bool = True
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tags = sorted({t.strip().lower() for t in self.tags if t and t.strip()})
        order = {s: i for i, s in enumerate(SEVERITIES)}
        self.rewards = sorted(self.rewards, key=lambda r: order.get(r.severity, len(order)))

    @classmethod
    def from_dict(cls, payload: dict) -> Program:
        """Rebuild a Program from a stored snapshot payload."""
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in payload.items() if k in known}
        data["scope"] = Scope(**(payload.get("scope") or {}))
        data["rewards"] = [RewardTier(**r) for r in payload.get("rewards") or []]
        return cls(**data)

    def max_reward(self) -> tuple[float, str] | None:
        """Highest published payout and its currency, or None if none published."""
        tops = [(r.top(), r.currency) for r in self.rewards if r.top()]
        return max(tops, key=lambda t: t[0]) if tops else None

    def max_reward_usd(self) -> float | None:
        best = self.max_reward()
        if best is None:
            return None
        rate = APPROX_USD_RATE.get(best[1].upper())
        return best[0] * rate if rate else None


def merge_tiers(entries: list[tuple[str, float | None, float | None]], currency: str) -> list[RewardTier]:
    """Collapse (severity, min, max) rows into one tier per severity.

    Platforms publish reward tables per asset group; the program-level view
    keeps the widest range per severity. Rows with no amount at all (points,
    swag, "not eligible") are dropped.
    """
    def amount(value) -> float | None:
        return float(value) if value is not None and float(value) > 0 else None

    def pick(fn, a: float | None, b: float | None) -> float | None:
        present = [v for v in (a, b) if v is not None]
        return fn(present) if present else None

    ranges: dict[str, tuple[float | None, float | None]] = {}
    for severity, low, high in entries:
        low, high = amount(low), amount(high)
        if low is None and high is None:
            continue
        if severity in ranges:
            old_low, old_high = ranges[severity]
            low, high = pick(min, old_low, low), pick(max, old_high, high)
        ranges[severity] = (low, high)
    return [RewardTier(sev, lo, hi, currency) for sev, (lo, hi) in ranges.items()]
