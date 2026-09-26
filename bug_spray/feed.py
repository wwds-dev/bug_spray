"""Read-only view of Bug Spray's saved data for the Sentinel panel and CLI."""

from __future__ import annotations

from . import config, watchlist
from .models import Program
from .store import Store


def read_feed(settings: config.Settings) -> dict:
    if not settings.db_path.exists():
        return {"last_scan": None, "poll_interval_minutes": settings.poll_interval_minutes,
                "programs": [], "changes": []}
    db = Store(settings.db_path, readonly=True)
    try:
        programs = [p for p in db.current_programs() if watchlist.matches(p, settings)]
        programs.sort(key=lambda p: (p.active, p.max_reward_usd() or 0), reverse=True)
        events = []
        for event in db.recent_changes(200):
            payload = db.latest(event["program"]["platform"], event["program"]["slug"])
            if payload and watchlist.matches(Program.from_dict(payload), settings):
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
