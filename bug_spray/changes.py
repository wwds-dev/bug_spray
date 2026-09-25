"""What changed about a program since its last stored snapshot.

The scan's whole output is a list of these: new programs, scope additions and
removals, reward changes per severity, paused/resumed, and programs that left
(or came back to) their platform's public listing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .models import Program
from .store import diff_scope


@dataclass
class RewardChange:
    severity: str
    before: float | None
    after: float | None
    currency: str


@dataclass
class ProgramChanges:
    program: Program
    new: bool = False
    returned: bool = False
    gone: bool = False
    scope_added: list[str] = field(default_factory=list)
    scope_removed: list[str] = field(default_factory=list)
    rewards: list[RewardChange] = field(default_factory=list)
    status: str | None = None  # "paused" | "resumed"

    def __bool__(self) -> bool:
        return bool(
            self.new or self.returned or self.gone or self.scope_added
            or self.scope_removed or self.rewards or self.status
        )

    def kinds(self) -> list[str]:
        kinds = []
        for kind, present in [
            ("new", self.new), ("returned", self.returned), ("gone", self.gone),
            ("scope", self.scope_added or self.scope_removed), ("rewards", self.rewards),
            ("status", self.status),
        ]:
            if present:
                kinds.append(kind)
        return kinds

    def to_dict(self) -> dict:
        data = asdict(self)
        data["program"] = {
            "platform": self.program.platform,
            "slug": self.program.slug,
            "name": self.program.name,
            "url": self.program.url,
        }
        data["kinds"] = self.kinds()
        return data


def diff_rewards(current: Program, previous: Program) -> list[RewardChange]:
    """Top payout per severity, before vs after. A currency switch counts as a change."""
    before = {r.severity: r for r in previous.rewards}
    after = {r.severity: r for r in current.rewards}
    changes = []
    for severity in [*after, *(s for s in before if s not in after)]:
        old, new = before.get(severity), after.get(severity)
        old_top, new_top = old.top() if old else None, new.top() if new else None
        if old_top != new_top or (old and new and old.currency != new.currency):
            changes.append(RewardChange(severity, old_top, new_top, (new or old).currency))
    return changes


def diff_program(current: Program, previous: dict | None, returned: bool = False) -> ProgramChanges:
    """Compare a freshly fetched program with its last stored payload (None = never seen)."""
    if previous is None:
        return ProgramChanges(current, new=True)
    before = Program.from_dict(previous)
    scope = diff_scope(asdict(current), previous)
    status = None
    if before.active != current.active:
        status = "resumed" if current.active else "paused"
    return ProgramChanges(
        current,
        returned=returned,
        scope_added=scope["added"],
        scope_removed=scope["removed"],
        rewards=diff_rewards(current, before),
        status=status,
    )
