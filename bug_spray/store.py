"""SQLite snapshot cache for program metadata, with diffing between runs.

Each scan writes one row per program per run. Diffing compares the latest
row for a program against the one before it — no external state, no
migrations yet (single table, additive only).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .models import Program

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    slug TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_platform_slug ON snapshots (platform, slug, fetched_at);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def save(self, program: Program) -> None:
        self._conn.execute(
            "INSERT INTO snapshots (platform, slug, fetched_at, payload) VALUES (?, ?, ?, ?)",
            (
                program.platform,
                program.slug,
                datetime.now(UTC).isoformat(),
                json.dumps(asdict(program)),
            ),
        )
        self._conn.commit()

    def latest_two(self, platform: str, slug: str) -> tuple[dict | None, dict | None]:
        """Return (current, previous) snapshot payloads for a program, newest first."""
        rows = self._conn.execute(
            "SELECT payload FROM snapshots WHERE platform = ? AND slug = ? "
            "ORDER BY fetched_at DESC LIMIT 2",
            (platform, slug),
        ).fetchall()
        payloads = [json.loads(row[0]) for row in rows]
        current = payloads[0] if len(payloads) > 0 else None
        previous = payloads[1] if len(payloads) > 1 else None
        return current, previous

    def known_slugs(self, platform: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT slug FROM snapshots WHERE platform = ?", (platform,)
        ).fetchall()
        return [row[0] for row in rows]


def diff_scope(current: dict, previous: dict | None) -> dict[str, list[str]]:
    """Compare in-scope asset lists between two snapshots. First run = no diff."""
    if previous is None:
        return {"added": [], "removed": []}
    before = set(previous.get("scope", {}).get("in_scope", []))
    after = set(current.get("scope", {}).get("in_scope", []))
    return {
        "added": sorted(after - before),
        "removed": sorted(before - after),
    }
