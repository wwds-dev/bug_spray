"""Store, diffing, watchlist and the `scan` / `list` / `show` commands, offline."""

import json
import fcntl
import os
import sqlite3
from dataclasses import asdict, replace

import pytest

from bug_spray import cli, config, sources, store, watchlist
from bug_spray.changes import diff_program
from bug_spray.feed import read_feed
from bug_spray.models import Program, RewardTier, Scope, merge_tiers


def make(slug="acme", **kw):
    base = dict(platform="hackerone", slug=slug, name=slug.title(), url=f"https://h1/{slug}",
                active=True, scope=Scope(in_scope=["a.example"]),
                rewards=[RewardTier("critical", 1000, 5000)], tags=["url"])
    base.update(kw)
    return Program(**base)


# ---------------------------------------------------------------- models


def test_scope_and_tags_are_normalised():
    p = make(scope=Scope(in_scope=["b", "a", "a", " "]), tags=["URL", "url", "Web"])
    assert p.scope.in_scope == ["a", "b"] and p.tags == ["url", "web"]


def test_merge_tiers_keeps_widest_range_and_up_to_has_no_minimum():
    tiers = merge_tiers([("high", 100, 200), ("high", 50, 400), ("critical", None, 9000), ("low", 0, 0)], "USD")
    by = {t.severity: (t.min_amount, t.max_amount) for t in tiers}
    assert by == {"high": (50, 400), "critical": (None, 9000)}


def test_program_round_trips_and_loads_v0_payload():
    p = make()
    assert Program.from_dict(asdict(p)) == p
    v0 = {"platform": "hackerone", "slug": "x", "name": "X", "url": "u", "active": True,
          "scope": {"in_scope": ["x.com"], "out_of_scope": []}, "rewards": [], "last_updated": None}
    assert Program.from_dict(v0).tags == []


def test_max_reward_usd_converts_and_refuses_unknown_currency():
    assert make(rewards=[RewardTier("critical", None, 1000, "EUR")]).max_reward_usd() == pytest.approx(1100)
    assert make(rewards=[RewardTier("critical", None, 1000, "XYZ")]).max_reward_usd() is None
    assert make(rewards=[]).max_reward_usd() is None


# ---------------------------------------------------------------- store


def test_record_only_writes_a_snapshot_when_something_changed(tmp_path):
    db = store.Store(tmp_path / "db.sqlite3")
    try:
        assert db.record(make()) == (None, False)
        previous, _ = db.record(make())
        assert previous is not None
        db.record(make(scope=Scope(in_scope=["a.example", "b.example"])))
        rows = db._conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert rows == 2
    finally:
        db.close()


def test_gone_and_returned(tmp_path):
    db = store.Store(tmp_path / "db.sqlite3")
    try:
        db.record(make("a"))
        db.record(make("b"))
        gone = db.mark_gone("hackerone", {"a"})
        assert [p.slug for p in gone] == ["b"]
        assert db.mark_gone("hackerone", {"a"}) == [], "gone is reported once"
        assert [p.slug for p in db.current_programs()] == ["a"]
        _, was_gone = db.record(make("b"))
        assert was_gone
        assert db.listed_slugs("hackerone") == {"a", "b"}
    finally:
        db.close()


def test_v0_database_upgrades_in_place(tmp_path):
    path = tmp_path / "db.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, "
        "slug TEXT NOT NULL, fetched_at TEXT NOT NULL, payload TEXT NOT NULL);"
    )
    v0 = {"platform": "hackerone", "slug": "old", "name": "Old", "url": "u", "active": True,
          "scope": {"in_scope": ["x.com"], "out_of_scope": []}, "rewards": [], "last_updated": None}
    conn.execute("INSERT INTO snapshots (platform, slug, fetched_at, payload) VALUES (?,?,?,?)",
                 ("hackerone", "old", "2026-09-15T00:00:00+00:00", json.dumps(v0)))
    conn.commit()
    conn.close()

    db = store.Store(path)
    try:
        assert db.listed_slugs("hackerone") == {"old"}
        assert db.known_programs("hackerone")["old"].scope.in_scope == ["x.com"]
    finally:
        db.close()


# ---------------------------------------------------------------- changes


def test_diff_program_reports_each_kind():
    before = make()
    after = replace(
        make(scope=Scope(in_scope=["new.example"]), rewards=[RewardTier("critical", 1000, 10000)]),
        active=False,
    )
    change = diff_program(after, asdict(before))
    assert change.scope_added == ["new.example"] and change.scope_removed == ["a.example"]
    assert [(r.severity, r.before, r.after) for r in change.rewards] == [("critical", 5000, 10000)]
    assert change.status == "paused"
    assert set(change.kinds()) == {"scope", "rewards", "status"}


def test_diff_program_unchanged_is_falsy_and_new_is_new():
    payload = asdict(make())
    assert not diff_program(make(), payload)
    assert diff_program(make(), None).new


# ---------------------------------------------------------------- watchlist


@pytest.mark.parametrize(
    "settings, expected",
    [
        (config.Settings(), True),
        (config.Settings(min_reward_usd=5000), True),
        (config.Settings(min_reward_usd=5001), False),
        (config.Settings(watchlist_keywords=["A.EXAMPLE"]), True),
        (config.Settings(watchlist_keywords=["nope", "acme"]), True),
        (config.Settings(watchlist_keywords=["nope"]), False),
        (config.Settings(watchlist_tags=["URL"]), True),
        (config.Settings(watchlist_tags=["android"]), False),
        (config.Settings(watchlist_tags=["url"], watchlist_keywords=["nope"]), False),
    ],
)
def test_watchlist(settings, expected):
    assert watchlist.matches(make(), settings) is expected


def test_config_validation_catches_bad_filters():
    assert config.Settings(watchlist_keywords=[""]).validate()
    assert config.Settings(watchlist_tags="url").validate()
    assert config.Settings(min_reward_usd=-1).validate()
    assert not config.Settings(watchlist_tags=["url"], min_reward_usd=100).validate()


# ---------------------------------------------------------------- CLI


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """An isolated config + DB and a scriptable fake HackerOne adapter."""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    config.save(config.Settings(enabled_platforms=["hackerone"], data_dir=str(tmp_path / "data")), cfg)
    listing: list[Program] = []
    monkeypatch.setitem(sources.REGISTRY, "hackerone", lambda known: list(listing))
    return listing


def test_scan_baseline_then_changes(lab, capsys):
    lab[:] = [make("a"), make("b")]
    assert cli.main(["scan"]) == 0
    assert "baseline stored" in capsys.readouterr().out

    assert cli.main(["scan"]) == 0
    assert "No changes since the last scan" in capsys.readouterr().out

    lab[:] = [make("a", scope=Scope(in_scope=["a.example", "api.a.example"])), make("c")]
    assert cli.main(["scan", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    kinds = {c["program"]["slug"]: c["kinds"] for c in report["changes"]}
    assert kinds == {"a": ["scope"], "c": ["new"], "b": ["gone"]}
    saved = read_feed(config.load())
    assert saved["last_scan"]["scanned_at"] == report["scanned_at"]
    assert {c["program"]["slug"] for c in saved["changes"]} == {"a", "b", "c"}
    assert {p["slug"] for p in saved["programs"]} == {"a", "c"}
    assert cli.main(["feed", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["changes"]) == 3


def test_feed_reads_v1_database_without_writing(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, "
        "slug TEXT NOT NULL, fetched_at TEXT NOT NULL, payload TEXT NOT NULL);"
        "CREATE TABLE programs (platform TEXT, slug TEXT, first_seen TEXT, last_seen TEXT, gone_at TEXT);"
    )
    conn.execute("INSERT INTO snapshots (platform, slug, fetched_at, payload) VALUES (?,?,?,?)",
                 ("hackerone", "old", "2026-09-25T00:00:00+00:00", json.dumps(asdict(make("old")))))
    conn.execute("INSERT INTO programs VALUES (?,?,?,?,?)",
                 ("hackerone", "old", "2026-09-25T00:00:00+00:00", "2026-09-25T00:00:00+00:00", None))
    conn.commit()
    conn.close()
    settings = config.Settings(data_dir=str(tmp_path))
    path.rename(settings.db_path)
    result = read_feed(settings)
    assert result["programs"][0]["slug"] == "old"
    assert result["changes"] == []
    assert result["last_scan"]["scanned_at"] == "2026-09-25T00:00:00+00:00"
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='scan_runs'").fetchone() is None
    conn.close()


def test_scan_does_not_mark_half_a_platform_gone(lab, capsys):
    lab[:] = [make(s) for s in "abcd"]
    cli.main(["scan"])
    lab[:] = [make("a")]
    cli.main(["scan"])
    out = capsys.readouterr().out
    assert "not marking them gone" in out and "GONE" not in out


def test_scan_reports_platform_error_and_fails(lab, monkeypatch, capsys):
    monkeypatch.setitem(sources.REGISTRY, "hackerone", lambda known: (_ for _ in ()).throw(ValueError("x")))
    assert cli.main(["scan"]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_scan_refuses_overlap(lab, capsys):
    lock_path = config.load().db_path.parent / "scan.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cli.main(["scan", "--json"]) == 1
        assert "already running" in json.loads(capsys.readouterr().out)["error"]
    finally:
        os.close(fd)


def test_scan_watchlist_filters_report_not_storage(lab, capsys):
    lab[:] = [make("wanted"), make("other")]
    cli.main(["scan"])
    config.save(replace(config.load(), watchlist_keywords=["wanted"]), config.CONFIG_PATH)
    lab[:] = [make(slug, rewards=[RewardTier("critical", 1000, 9000)]) for slug in ("wanted", "other")]
    capsys.readouterr()
    cli.main(["scan", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert [c["program"]["slug"] for c in report["changes"]] == ["wanted"]
    assert cli.main(["list", "--all", "--json"]) == 0
    assert {p["slug"] for p in json.loads(capsys.readouterr().out)} == {"wanted", "other"}


def test_list_and_show(lab, capsys):
    lab[:] = [make("cheap", rewards=[RewardTier("low", 50, 100)]), make("rich")]
    cli.main(["scan"])
    capsys.readouterr()
    cli.main(["list"])
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "rich" in lines[0].lower() and "cheap" in lines[1].lower()
    assert cli.main(["show", "hackerone", "rich"]) == 0
    out = capsys.readouterr().out
    assert "a.example" in out and "$1,000 – $5,000" in out and "not authorization" in out
    assert cli.main(["show", "hackerone", "missing"]) == 1


def test_scan_without_platforms_is_a_no_op(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "none.json")
    assert cli.main(["scan"]) == 0
    assert "No platforms enabled" in capsys.readouterr().out


def test_feed_show_all_ignores_the_watchlist(tmp_path):
    settings = config.Settings(watchlist_keywords=["wanted"], data_dir=str(tmp_path))
    db = store.Store(settings.db_path)
    try:
        db.record(make("wanted"))
        db.record(make("other"))
    finally:
        db.close()
    assert [p["slug"] for p in read_feed(settings)["programs"]] == ["wanted"]
    assert {p["slug"] for p in read_feed(settings, show_all=True)["programs"]} == {"wanted", "other"}
