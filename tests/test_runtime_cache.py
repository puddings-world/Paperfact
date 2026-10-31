"""Derived-review cache uses platform-local storage and creates no directories."""

import pytest

from paper_daily.runtime import user_cache_dir


@pytest.mark.parametrize(
    "platform,suffix",
    [
        ("win32", "AppData/Local/Paperfact/Cache"),
        ("darwin", "Library/Caches/Paperfact"),
        ("linux", ".cache/Paperfact"),
    ],
)
def test_default_cache_is_local_independent_of_research_and_install(platform, suffix, tmp_path):
    home = tmp_path / "home"
    result = user_cache_dir(platform, env={"PAPERFACT_DATA": str(tmp_path / "research")}, home=home)
    assert result == home / suffix
    assert not home.exists() and not (tmp_path / "research").exists()


@pytest.mark.parametrize(
    "platform,variable,suffix",
    [("win32", "LOCALAPPDATA", "Paperfact/Cache"), ("linux", "XDG_CACHE_HOME", "Paperfact")],
)
def test_explicit_absolute_cache_override_is_respected(platform, variable, suffix, tmp_path):
    result = user_cache_dir(
        platform, env={variable: str(tmp_path / "configured")}, home=tmp_path / "home"
    )
    assert result == tmp_path / "configured" / suffix and not result.exists()


@pytest.mark.parametrize(
    "platform,variable,suffix",
    [
        ("win32", "LOCALAPPDATA", "AppData/Local/Paperfact/Cache"),
        ("linux", "XDG_CACHE_HOME", ".cache/Paperfact"),
    ],
)
def test_relative_cache_env_does_not_land_in_the_install_folder(
    platform, variable, suffix, tmp_path
):
    result = user_cache_dir(platform, env={variable: "relative-cache"}, home=tmp_path / "home")
    assert result == tmp_path / "home" / suffix and not result.exists()
