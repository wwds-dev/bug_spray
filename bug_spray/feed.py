"""Read-only view of Bug Spray's saved data for the Sentinel panel and CLI."""

from __future__ import annotations

from . import config, watchlist
from .models import Program
from .store import Store


def read_feed(settings: config.Settings, show_all: bool = False) -> dict:
    """Saved programs and recent changes; `show_all` ignores the watchlist filters."""

    def wanted(program: Program) -> bool:
        return show_all or watchlist.matches(program, settings)

    if not settings.db_path.exists():
        return {"last_scan": None, "poll_interval_minutes": settings.poll_interval_minutes,
                "programs": [], "changes": []}
    db = Store(settings.db_path, readonly=True)
    try:
        programs = [p for p in db.current_programs() if wanted(p)]
        programs.sort(key=lambda p: (p.active, p.max_reward_usd() or 0), reverse=True)
        events = []
        # Memoise the per-program "wanted?" decision: recent_changes often
        # carries many events for the same program, and each db.latest() is a
        # separate query (an N+1 over the change feed).
        wanted_cache: dict[tuple[str, str], bool] = {}
        for event in db.recent_changes(200):
            key = (event["program"]["platform"], event["program"]["slug"])
            if key not in wanted_cache:
                payload = db.latest(*key)
                wanted_cache[key] = bool(payload and wanted(Program.from_dict(payload)))
            if wanted_cache[key]:
                events.append(event)
        return {
            "last_scan": db.last_scan(),
            "poll_interval_minutes": settings.poll_interval_minutes,
            "programs": [
                {"platform": p.platform, "slug": p.slug, "name": p.name, "url": p.url,
                 "active": p.active, "reward": p.max_reward(),
                 "scope_count": len(p.scope.in_scope)}
                for p in programs
            ],
            "changes": events[:100],
        }
    finally:
        db.close()


def read_program(settings: config.Settings, platform: str, slug: str) -> Program | None:
    if not settings.db_path.exists():
        return None
    db = Store(settings.db_path, readonly=True)
    try:
        payload = db.latest(platform, slug)
        return Program.from_dict(payload) if payload else None
    finally:
        db.close()
