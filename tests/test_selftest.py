from bug_spray import config, secrets, sources, store
from bug_spray.sources import hackerone  # noqa: F401  (registers the adapter)


def test_settings_round_trip(tmp_path):
    path = tmp_path / "config.json"
    settings = config.Settings(enabled_platforms=["hackerone"], poll_interval_minutes=30)
    config.save(settings, path)
    loaded = config.load(path)
    assert loaded.enabled_platforms == ["hackerone"]
    assert loaded.poll_interval_minutes == 30


def test_settings_validate_rejects_unknown_platform():
    settings = config.Settings(enabled_platforms=["not_a_real_platform"])
    assert settings.validate()


def test_store_creates_and_diffs(tmp_path):
    from bug_spray.models import Program, Scope

    db = store.Store(tmp_path / "programs.sqlite3")
    try:
        program = Program(
            platform="hackerone",
            slug="example",
            name="Example Program",
            url="https://hackerone.com/example",
            active=True,
            scope=Scope(in_scope=["example.com"]),
        )
        _, previous = db.latest_two("hackerone", "example")
        assert previous is None
        db.save(program)
        current, previous = db.latest_two("hackerone", "example")
        assert current["slug"] == "example"
        assert previous is None
    finally:
        db.close()


def test_hackerone_adapter_registered():
    assert "hackerone" in sources.REGISTRY


def test_secrets_backend_name_does_not_raise():
    assert isinstance(secrets.backend_name(), str)


def test_selftest_command_passes_on_a_fresh_checkout(tmp_path, monkeypatch, capsys):
    from bug_spray import cli

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    config.save(config.Settings(data_dir=str(tmp_path / "data")), tmp_path / "config.json")
    assert cli.main(["--selftest"]) == 0
    out = capsys.readouterr().out
    assert "OK" in out and "immunefi" in out
