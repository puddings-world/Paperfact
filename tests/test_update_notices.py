"""Release channels, non-blocking announcements and background lifecycle."""

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from paper_daily import runtime, store, updates
from paper_daily.desktop import update_banner
from paper_daily.desktop.main import LIGHT


def release(tag="v0.4.0", *, beta=True, draft=False):
    return dict(
        tag_name=tag,
        name=tag,
        prerelease=beta,
        draft=draft,
        body="- 外部清單更新\n- 操作更順暢",
        assets=[],
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(runtime, "FROZEN", False)
    monkeypatch.setattr(updates, "can_install", lambda: False)
    monkeypatch.setattr(QApplication, "focusWidget", lambda *_: None)
    widget = update_banner.UpdateBanner(LIGHT)
    monkeypatch.setattr(widget, "underMouse", lambda: False)
    yield widget
    widget.close()
    widget.deleteLater()


@pytest.fixture
def pending(monkeypatch):
    jobs = []

    class Thread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            jobs.append(self.target)

    monkeypatch.setattr(update_banner, "threading", SimpleNamespace(Thread=Thread))
    return jobs


def offer():
    return updates.Release(
        "0.4.0",
        "Preview",
        "- 外部清單更新",
        "https://github.com/puddings-world/Paperfact/releases/tag/v0.4.0",
        {
            "Paperfact-0.4.0-windows-x64-setup.exe": "https://fixture/setup.exe",
            "Paperfact-0.4.0-macos-arm64.dmg": "https://fixture/app.dmg",
            "Paperfact-0.4.0-linux-x86_64.AppImage": "https://fixture/app.AppImage",
        },
        prerelease=True,
    )


def test_beta_channel_can_find_published_preview_without_enabling_drafts():
    items = [release(), release("v0.5.0", draft=True), release("v0.3.1", beta=False)]
    assert updates.newest(items, "0.3.0", include_prerelease=True).version == "0.4.0"
    assert updates.newest(items, "0.3.0").version == "0.3.1"
    assert updates.newest([release()], "0.4.0", include_prerelease=True) is None
    assert (
        updates.newest([release("research-data"), None], "0.3.0", include_prerelease=True) is None
    )


def test_preview_policy_and_explicit_stable_setting():
    assert updates.default_channel("0.3.0", {}) == "beta"
    assert updates.default_channel("1.0.0", {}) == "stable"
    assert updates.default_channel("0.3.0", {"PAPERFACT_UPDATE_CHANNEL": "stable"}) == "stable"
    assert updates.default_channel("1.0.0", {"PAPERFACT_UPDATE_CHANNEL": "beta"}) == "beta"


def test_cache_is_bound_to_channel_and_running_version(workspace):
    calls = []

    def fetch():
        calls.append(1)
        return [release()]

    day = date(2026, 10, 26)
    with store.connect() as conn:
        assert updates.check(conn, "0.3.0", fetch, day, channel="stable") is None
        assert updates.check(conn, "0.3.0", fetch, day, channel="beta").prerelease
        assert updates.check(conn, "0.3.0", fetch, day, channel="beta").version == "0.4.0"
        assert len(calls) == 2
        assert updates.check(conn, "0.4.0", fetch, day, channel="beta") is None
        assert updates.check(conn, "0.3.0", fetch, day, channel="beta").version == "0.4.0"
        # Returning to a previously checked context uses its own cache.
        assert len(calls) == 3


def test_offline_channel_switch_does_not_reuse_beta_notice(workspace):
    with store.connect() as conn:
        updates.check(conn, "0.3.0", lambda: [release()], channel="beta")
        assert updates.check(conn, "0.3.0", lambda *_: None, channel="stable") is None
        assert updates.check(conn, "0.3.0", lambda: [release()], channel="stable") is None


def test_notice_rotates_in_place_and_pauses_for_interaction(workspace, monkeypatch):
    workspace.offer(offer())
    first = workspace.label.text()
    assert "公開 beta" in first and "原始碼版" in first and "外部清單更新" in first
    workspace._cycle()
    assert "git pull --ff-only" in workspace.label.text()
    second = workspace.label.text()
    workspace.offer(offer())  # repeated poll must not reset the announcement
    assert workspace.label.text() == second
    monkeypatch.setattr(workspace, "underMouse", lambda: True)
    workspace._cycle()
    assert workspace.label.text() == second
    monkeypatch.setattr(workspace, "underMouse", lambda: False)
    monkeypatch.setattr(QApplication, "focusWidget", lambda *_: workspace.install)
    workspace._cycle()
    assert workspace.label.text() == second
    monkeypatch.setattr(QApplication, "focusWidget", lambda *_: None)
    workspace._cycle()
    assert workspace.label.text() == first


def test_snooze_persists_and_late_check_cannot_redisplay(workspace):
    found = offer()
    workspace.offer(found)
    workspace.later.click()
    workspace._found(found)
    assert workspace.isHidden()
    with store.connect() as conn:
        assert updates.snoozed(conn, found)
    newer = updates.Release("0.5.0", "", "", found.page, {})
    workspace._found(newer)
    assert not workspace.isHidden() and "0.5.0" in workspace.label.text()


def test_background_checks_are_deduplicated_and_use_preview_channel(
    workspace, pending, monkeypatch
):
    calls = []

    def check(conn, **kwargs):
        calls.append(kwargs)
        return offer()

    monkeypatch.setattr(updates, "check", check)
    monkeypatch.setattr(updates, "default_channel", lambda: "beta")
    for _ in range(30):
        workspace.check_in_background()
    assert len(pending) == 1 and workspace.isHidden()
    pending.pop()()
    QApplication.processEvents()
    assert calls == [{"channel": "beta"}]
    assert not workspace.isHidden()
    assert workspace._poll.isActive()  # an app left open retries on later days


def test_check_failure_can_retry_and_close_ignores_late_result(workspace, pending, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("offline fixture")

    monkeypatch.setattr(updates, "check", broken)
    workspace.check_in_background()
    pending.pop()()
    QApplication.processEvents()
    monkeypatch.setattr(updates, "check", lambda *args, **kwargs: offer())
    workspace.check_in_background()
    assert len(pending) == 1
    workspace.close()
    pending.pop()()
    QApplication.processEvents()
    assert workspace.isHidden() and not workspace._poll.isActive()
    workspace.check_in_background()
    assert len(pending) == 0


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_download_repeated_activation_and_late_offer_are_isolated(
    workspace, pending, monkeypatch, platform
):
    asset_for = updates.asset_for
    monkeypatch.setattr(updates, "asset_for", lambda found: asset_for(found, platform))
    monkeypatch.setattr(updates, "can_install", lambda: True)
    workspace.offer(offer())
    for _ in range(30):
        workspace.start_install()
    assert len(pending) == 1 and not workspace.install.isEnabled()
    workspace._found(updates.Release("0.5.0", "", "", "", {}))
    assert workspace.release.version == "0.4.0"
    text = workspace.label.text()
    workspace._cycle()
    assert workspace.label.text() == text
    workspace._failed("fixture timeout")
    assert workspace.install.isEnabled() and "fixture timeout" in workspace.label.text()
    workspace.start_install()
    assert len(pending) == 2


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_download_finishing_after_close_does_not_start_installer(
    workspace, pending, monkeypatch, tmp_path, platform
):
    asset_for = updates.asset_for
    monkeypatch.setattr(updates, "asset_for", lambda found: asset_for(found, platform))
    launched = []
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(updates, "download_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "download", lambda url, path, progress: path)
    monkeypatch.setattr(updates, "launch_installer", lambda path: launched.append(path))
    workspace.offer(offer())
    workspace.start_install()
    workspace.close()
    pending.pop()()
    QApplication.processEvents()
    assert not launched


def test_no_release_activation_and_missing_asset_only_open_release_page(
    workspace, pending, monkeypatch
):
    opened = []
    monkeypatch.setattr(
        update_banner.QDesktopServices, "openUrl", lambda u: opened.append(u.toString())
    )
    workspace.start_install()
    assert not pending and not opened
    monkeypatch.setattr(updates, "can_install", lambda: True)
    found = updates.Release(
        "0.4.0", "", "", "https://github.com/puddings-world/Paperfact/releases", {}
    )
    workspace.offer(found)
    workspace.start_install()
    assert not pending and opened == [found.page]


def test_non_self_updating_installed_build_is_not_given_git_instructions(workspace, monkeypatch):
    monkeypatch.setattr(runtime, "FROZEN", True)
    workspace.offer(offer())
    assert "安裝版" in workspace.label.text()
    assert workspace.install.text() == "下載新版"
    assert "git pull" not in workspace.install.toolTip()


def test_main_window_close_stops_late_release_results(workspace, pending, monkeypatch):
    from paper_daily.desktop.main import MainWindow

    monkeypatch.setattr(updates, "check", lambda *args, **kwargs: offer())
    window = MainWindow()
    banner = window.update_banner
    banner.check_in_background()
    assert len(pending) == 1
    window.close()
    pending.pop()()
    QApplication.processEvents()
    assert banner.isHidden() and not banner._poll.isActive()
    window.deleteLater()


def test_old_stable_cache_does_not_hide_beta_upgrade(workspace):
    # v0.3.0 stored only the date and a stable-only result, without context.
    with store.connect() as conn:
        store.set_kv(conn, updates.LAST_CHECK, date.today().isoformat())
        store.set_kv(conn, updates.FOUND, "")
        result = updates.check(conn, "0.3.0", lambda: [release()], channel="beta")
        assert result.version == "0.4.0"
