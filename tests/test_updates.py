"""New versions from GitHub Releases: which one counts, how often to ask, and how
each platform's build replaces itself."""

from datetime import date
from pathlib import Path, PurePosixPath

import pytest

from paper_daily import runtime, store, updates


def _release(tag, *, draft=False, prerelease=False, body="", assets=()):
    return {
        "tag_name": tag,
        "name": f"Paperfact {tag}",
        "draft": draft,
        "prerelease": prerelease,
        "body": body,
        "html_url": f"https://github.com/puddings-world/Paperfact/releases/tag/{tag}",
        "assets": [{"name": n, "browser_download_url": f"https://dl/{n}"} for n in assets],
    }


RELEASES = [
    _release("cataract-2026-10-15", assets=["cataract-20261015.zip"]),
    _release("v0.3.0", draft=True),
    _release("v0.2.1-rc1"),
    _release("v0.2.5", prerelease=True),
    _release(
        "v0.2.0",
        body="## 新功能\n- 引用分頁切換變快\n- **自動更新**\n\n細節見下。",
        assets=[
            "Paperfact-0.2.0-windows-x64-setup.exe",
            "Paperfact-0.2.0-macos-arm64.dmg",
            "Paperfact-0.2.0-linux-x86_64.AppImage",
        ],
    ),
    _release("v0.1.5"),
]


def test_only_published_version_tags_count():
    found = updates.newest(RELEASES, "0.1.0")
    assert found.version == "0.2.0"
    assert found.page.endswith("/v0.2.0")
    assert updates.newest(RELEASES, "0.2.0") is None
    assert updates.newest(RELEASES, "0.10.0") is None
    assert updates.newest([_release("v0.10.0"), _release("v0.9.0")], "0.2.0").version == "0.10.0"


def test_each_platform_gets_its_own_build():
    release = updates.newest(RELEASES, "0.1.0")
    assert updates.asset_for(release, "win32")[0].endswith("windows-x64-setup.exe")
    assert updates.asset_for(release, "darwin")[0].endswith(".dmg")
    assert updates.asset_for(release, "linux")[0].endswith(".AppImage")
    assert updates.asset_for(release, "freebsd") is None
    bare = updates.newest([_release("v9.0.0")], "0.1.0")
    assert updates.asset_for(bare, "win32") is None


def test_the_banner_line_is_the_notes_as_plain_text():
    release = updates.newest(RELEASES, "0.1.0")
    assert updates.headline(release.notes) == "新功能 · 引用分頁切換變快 · 自動更新 · 細節見下。"
    long = updates.headline("- " + "很長的一句話" * 40, limit=30)
    assert len(long) == 30 and long.endswith("…")
    assert updates.headline("") == ""
    assert updates.headline("<!-- rewrite these,\n then publish -->\n\n- 新功能") == "新功能"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as c:
        yield c


def test_github_is_asked_once_a_day(conn):
    calls = []

    def fetch():
        calls.append(1)
        return RELEASES

    day = date(2026, 10, 20)
    assert updates.check(conn, "0.1.0", fetch, day).version == "0.2.0"
    assert updates.check(conn, "0.1.0", fetch, day).version == "0.2.0"
    assert len(calls) == 1
    updates.check(conn, "0.1.0", fetch, date(2026, 10, 21))
    assert len(calls) == 2


def test_offline_is_not_remembered_as_a_check(conn):
    day = date(2026, 10, 20)
    assert updates.check(conn, "0.1.0", lambda: None, day) is None
    assert updates.check(conn, "0.1.0", lambda: RELEASES, day).version == "0.2.0"


def test_a_release_found_before_updating_is_no_longer_news(conn):
    day = date(2026, 10, 20)
    updates.check(conn, "0.1.0", lambda: RELEASES, day)
    # The same day, after the update installed 0.2.0: the stored find is stale.
    assert updates.check(conn, "0.2.0", lambda: RELEASES, day) is None


def test_later_hides_one_version_for_the_rest_of_the_day(conn):
    day = date(2026, 10, 20)
    release = updates.check(conn, "0.1.0", lambda: RELEASES, day)
    updates.snooze(conn, release, day)
    assert updates.snoozed(conn, release, day)
    assert not updates.snoozed(conn, release, date(2026, 10, 21))
    newer = updates.newest([_release("v0.3.0")], "0.1.0")
    assert not updates.snoozed(conn, newer, day)


def test_only_an_installed_build_replaces_itself():
    assert not updates.can_install("win32", {}, frozen=False)
    assert updates.can_install("win32", {}, frozen=True)
    assert updates.can_install("darwin", {}, frozen=True)
    # A Linux build that is not an AppImage has no single file to swap.
    assert not updates.can_install("linux", {}, frozen=True)
    assert updates.can_install("linux", {"APPIMAGE": "/opt/Paperfact.AppImage"}, frozen=True)


def test_the_mac_swap_keeps_the_old_app_until_the_copy_succeeds():
    app = PurePosixPath("/Applications/Paper fact.app")
    script = updates.mac_script(PurePosixPath("/tmp/Paperfact 0.2.0.dmg"), app, 4242)
    assert "kill -0 4242" in script
    assert "'/tmp/Paperfact 0.2.0.dmg'" in script
    move = script.index("mv '/Applications/Paper fact.app' '/Applications/Paper fact.app.old'")
    copy = script.index("ditto")
    restore = script.index("mv '/Applications/Paper fact.app.old' '/Applications/Paper fact.app'")
    assert move < copy < restore
    assert script.rstrip().endswith("open '/Applications/Paper fact.app'")
    assert updates.app_bundle("/Applications/Paperfact.app/Contents/MacOS/Paperfact").name == (
        "Paperfact.app"
    )


def test_the_appimage_is_replaced_after_the_app_quits():
    script = updates.linux_script(
        PurePosixPath("/home/u/Apps/new.AppImage"), PurePosixPath("/home/u/Apps/P.AppImage"), 7
    )
    lines = script.splitlines()
    assert lines[1].startswith("while kill -0 7")
    assert "mv -f /home/u/Apps/new.AppImage /home/u/Apps/P.AppImage" in script


def test_the_windows_installer_runs_silently_and_closes_the_old_copy():
    command = updates.windows_command(Path("C:/Temp/setup.exe"))
    assert command[0].endswith("setup.exe")
    assert "/SILENT" in command and "/CLOSEAPPLICATIONS" in command


def test_a_download_only_takes_its_name_when_complete(tmp_path, monkeypatch):
    class Response:
        headers = {"content-length": "6"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, _size):
            yield b"abc"
            yield b"def"

    monkeypatch.setattr(updates.httpx, "stream", lambda *a, **k: Response())
    seen = []
    dest = updates.download("https://dl/x", tmp_path / "x.exe", lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == b"abcdef"
    assert seen == [(3, 6), (6, 6)]
    assert not (tmp_path / "x.exe.part").exists()


def test_the_build_names_match_what_the_release_workflow_uploads():
    workflow = (runtime.bundle_root() / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for suffix in updates.ASSET_SUFFIX.values():
        assert suffix in workflow
