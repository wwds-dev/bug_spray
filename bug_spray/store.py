"""SQLite snapshot cache for program metadata, with diffing between runs.

Two tables:
- `snapshots` — one row per program *per change*: a scan only writes a row
  when the program differs from its latest stored copy, so an hourly scan of
  ~1,000 unchanged programs adds nothing.
- `programs` — one row per program ever seen: first/last seen, and `gone_at`
  once it drops out of its platform's public listing. Created on open and
  back-filled from `snapshots`, so databases from v0 upgrade in place.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
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
CREATE TABLE IF NOT EXISTS programs (
    platform TEXT NOT NULL,
    slug TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    gone_at TEXT,
    PRIMARY KEY (platform, slug)
);
INSERT OR IGNORE INTO programs (platform, slug, first_seen, last_seen)
    SELECT platform, slug, MIN(fetched_at), MAX(fetched_at) FROM snapshots GROUP BY platform, slug;
"""

_LATEST = """
SELECT s.payload FROM snapshots s
JOIN (SELECT MAX(id) AS id FROM snapshots GROUP BY platform, slug) latest ON s.id = latest.id
JOIN programs p ON p.platform = s.platform AND p.slug = s.slug
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._batching = False

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group many writes into one transaction (one fsync per scan, not per program)."""
        self._batching = True
        try:
            with self._conn:
                yield
        finally:
            self._batching = False

    def _commit(self) -> None:
        if not self._batching:
            self._conn.commit()

    def save(self, program: Program) -> None:
        """Append a snapshot unconditionally. `record` is what a scan uses."""
        self._conn.execute(
            "INSERT INTO snapshots (platform, slug, fetched_at, payload) VALUES (?, ?, ?, ?)",
            (program.platform, program.slug, _now(), json.dumps(asdict(program), sort_keys=True)),
        )
        self._commit()

    def record(self, program: Program, seen_at: str | None = None) -> tuple[dict | None, bool]:
        """Store `program` if it changed; mark it seen.

        Returns (previous payload or None, whether it had been marked gone).
        """
        seen_at = seen_at or _now()
        previous = self.latest(program.platform, program.slug)
        row = self._conn.execute(
            "SELECT gone_at FROM programs WHERE platform = ? AND slug = ?",
            (program.platform, program.slug),
        ).fetchone()
        was_gone = bool(row and row[0])
        if previous != asdict(program):
            self._conn.execute(
                "INSERT INTO snapshots (platform, slug, fetched_at, payload) VALUES (?, ?, ?, ?)",
                (program.platform, program.slug, seen_at, json.dumps(asdict(program), sort_keys=True)),
            )
        self._conn.execute(
            "INSERT INTO programs (platform, slug, first_seen, last_seen) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (platform, slug) DO UPDATE SET last_seen = excluded.last_seen, gone_at = NULL",
            (program.platform, program.slug, seen_at, seen_at),
        )
        self._commit()
        return previous, was_gone

    def mark_gone(self, platform: str, seen_slugs: set[str], gone_at: str | None = None) -> list[Program]:
        """Mark listed programs of `platform` not in `seen_slugs` as gone; return the newly gone."""
        gone_at = gone_at or _now()
        newly_gone = sorted(self.listed_slugs(platform) - seen_slugs)
        self._conn.executemany(
            "UPDATE programs SET gone_at = ? WHERE platform = ? AND slug = ?",
            [(gone_at, platform, slug) for slug in newly_gone],
        )
        self._commit()
        programs = [self.latest(platform, slug) for slug in newly_gone]
        return [Program.from_dict(p) for p in programs if p]

    def latest(self, platform: str, slug: str) -> dict | None:
        row = self._conn.execute(
            "SELECT payload FROM snapshots WHERE platform = ? AND slug = ? ORDER BY id DESC LIMIT 1",
            (platform, slug),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def latest_two(self, platform: str, slug: str) -> tuple[dict | None, dict | None]:
        """Return (current, previous) snapshot payloads for a program, newest first."""
        rows = self._conn.execute(
            "SELECT payload FROM snapshots WHERE platform = ? AND slug = ? ORDER BY id DESC LIMIT 2",
            (platform, slug),
        ).fetchall()
        payloads = [json.loads(row[0]) for row in rows]
        current = payloads[0] if len(payloads) > 0 else None
        previous = payloads[1] if len(payloads) > 1 else None
        return current, previous

    def listed_slugs(self, platform: str) -> set[str]:
        """Slugs of `platform`'s programs not marked gone."""
        rows = self._conn.execute(
            "SELECT slug FROM programs WHERE platform = ? AND gone_at IS NULL", (platform,)
        ).fetchall()
        return {row[0] for row in rows}

    def known_slugs(self, platform: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT slug FROM snapshots WHERE platform = ?", (platform,)
        ).fetchall()
        return [row[0] for row in rows]

    def known_programs(self, platform: str) -> dict[str, Program]:
        """Latest stored copy of every program ever seen on `platform`, by slug."""
        rows = self._conn.execute(_LATEST + " WHERE s.platform = ?", (platform,)).fetchall()
        programs = [Program.from_dict(json.loads(row[0])) for row in rows]
        return {p.slug: p for p in programs}

    def current_programs(self, platform: str | None = None) -> list[Program]:
        """Latest copy of every program still listed (not gone), optionally for one platform."""
        query, args = _LATEST + " WHERE p.gone_at IS NULL", ()
        if platform:
            query, args = query + " AND s.platform = ?", (platform,)
        return [Program.from_dict(json.loads(row[0])) for row in self._conn.execute(query, args)]


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
