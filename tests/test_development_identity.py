"""Development versions follow Git and never replace themselves with release binaries."""
import sqlite3

import pytest

from paper_daily import build_identity, runtime, store, updates


@pytest.mark.parametrize("version", ["0.5.0.dev", "0.5.0.dev0", "v0.5.0.dev12"])
def test_dev_versions_never_offer_published_installers(version, tmp_path):
    assert updates.parse_version(version) == (0, 5, 0)
    assert updates.default_channel(version, {}) == "beta"
    releases = [dict(tag_name="v0.4.4"), dict(tag_name="v1.0.0")]
    assert updates.newest(releases, version, include_prerelease=True) is None
    conn = sqlite3.connect(tmp_path / "isolated.db")
    conn.executescript(store.SCHEMA)
    calls = []
    try:
        for force in (False, True):
            assert updates.check(conn, current=version,
                                 fetch=lambda: calls.append(1) or releases, force=force) is None
        assert not calls
    finally:
        conn.close()


def test_development_version_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(build_identity, "__version__", "0.5.0.dev")
    info = build_identity.identity(root=tmp_path, frozen=True)
    assert "0.5.0.dev" in build_identity.label(info)
    assert "0.5.0.dev" in build_identity.describe(info)


def test_explicit_dev_workspace_wins_over_daily_env_file(tmp_path):
    daily, development = tmp_path / "daily", tmp_path / "development"
    config = tmp_path / ".env"
    config.write_text(f"PAPERFACT_DATA={daily}\n", encoding="utf-8")
    env = {"PAPERFACT_DATA": str(development)}
    runtime.load_env_file(env, frozen=False, path=config)
    assert runtime.data_dir(env, frozen=False) == development
    assert not daily.exists() and not development.exists()


@pytest.mark.parametrize("tag", ["v0.5.0.dev", "v0.5.0.dev0", "v0.5.0-rc1"])
def test_development_artifacts_are_never_offered_to_maintenance_users(tag):
    assert updates.newest([dict(tag_name=tag)], "0.4.4", include_prerelease=True) is None
