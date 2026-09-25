"""User settings: everything the scanner needs that isn't a secret.

Secrets (platform API tokens) live in the Keychain — see secrets.py. This
file holds only non-sensitive preferences, and it ships empty: no platform
is enabled and no watchlist filter is set until someone configures one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"

ALL_PLATFORMS = ["hackerone", "bugcrowd", "intigriti", "yeswehack", "immunefi"]


@dataclass
class Settings:
    # Which source adapters to poll. Empty means "run selftest only" — a
    # fresh checkout should not silently start hitting every platform.
    enabled_platforms: list[str] = field(default_factory=list)

    # Watchlist filters — narrow what `scan` reports and `list` prints, never
    # what is stored. Empty/0 = filter not applied. See watchlist.py.
    watchlist_keywords: list[str] = field(default_factory=list)
    watchlist_tags: list[str] = field(default_factory=list)
    min_reward_usd: float = 0.0

    poll_interval_minutes: int = 60
    data_dir: str = "data"

    @property
    def db_path(self) -> Path:
        path = Path(self.data_dir).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path / "programs.sqlite3"

    def validate(self) -> list[str]:
        problems: list[str] = []
        unknown = set(self.enabled_platforms) - set(ALL_PLATFORMS)
        if unknown:
            problems.append(f"Unknown platform(s) in enabled_platforms: {sorted(unknown)}")
        if self.poll_interval_minutes < 1:
            problems.append("poll_interval_minutes must be at least 1.")
        for name in ("enabled_platforms", "watchlist_keywords", "watchlist_tags"):
            value = getattr(self, name)
            if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                problems.append(f"{name} must be a list of non-empty strings.")
        if not isinstance(self.min_reward_usd, (int, float)) or self.min_reward_usd < 0:
            problems.append("min_reward_usd must be a number, 0 or more.")
        return problems


def load(path: Path | None = None) -> Settings:
    path = path or CONFIG_PATH
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n")
