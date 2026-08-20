from dataclasses import dataclass, field


@dataclass
class RewardTier:
    severity: str
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str = "USD"


@dataclass
class Scope:
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)


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
