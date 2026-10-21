"""The update banner, and the PDF toolbar that wraps instead of running off the pane."""

import os
from datetime import date

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from paper_daily import store, updates  # noqa: E402
from paper_daily.desktop import update_banner  # noqa: E402
from paper_daily.desktop.flow_layout import FlowLayout  # noqa: E402
from paper_daily.desktop.main import LIGHT  # noqa: E402

RELEASE = updates.Release(
    version="9.0.0",
    title="Paperfact v9.0.0",
    notes="- 引用分頁切換變快\n- 自動更新",
    page="https://github.com/puddings-world/Paperfact/releases/tag/v9.0.0",
    assets={"Paperfact-9.0.0-windows-x64-setup.exe": "https://dl/setup.exe"},
)


@pytest.fixture
def banner(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    QApplication.instance() or QApplication([])
    widget = update_banner.UpdateBanner(LIGHT)
    widget.resize(900, 40)
    return widget


def test_the_banner_names_the_version_and_what_changed(banner, monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: True)
    banner.offer(RELEASE)
    assert not banner.isHidden()
    text = banner.label.text()
    assert "9.0.0" in text and "引用分頁切換變快 · 自動更新" in text
    assert banner.install.text() == "更新並重啟"


def test_a_source_checkout_is_told_how_rather_than_offered_an_install(banner, monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: False)
    opened = []
    monkeypatch.setattr(update_banner.QDesktopServices, "openUrl", lambda url: opened.append(url))
    banner.offer(RELEASE)
    assert banner.install.text() == "怎麼更新"
    assert "git pull" in banner.install.toolTip()
    banner.install.click()
    assert opened and opened[0].toString() == RELEASE.page


def test_later_hides_it_until_tomorrow(banner):
    banner.offer(RELEASE)
    banner.later.click()
    assert banner.isHidden()
    with store.connect() as conn:
        assert updates.snoozed(conn, RELEASE)
        assert not updates.snoozed(conn, RELEASE, date(2099, 1, 1))


def test_a_failed_download_says_so_and_can_be_retried(banner, monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: True)
    banner.offer(RELEASE)
    banner._failed("connection reset")
    assert "connection reset" in banner.label.text()
    assert banner.install.isEnabled() and banner.install.text() == "再試一次"


def test_a_finished_download_hands_over_to_the_installer_and_quits(banner, monkeypatch, tmp_path):
    started, quit_asked = [], []
    monkeypatch.setattr(updates, "launch_installer", lambda path: started.append(path))
    banner.quit_for_update.connect(lambda: quit_asked.append(True))
    banner.offer(RELEASE)
    banner._downloaded(tmp_path / "setup.exe")
    assert started == [tmp_path / "setup.exe"] and quit_asked == [True]


def _toolbar():
    QApplication.instance() or QApplication([])
    host = QWidget()
    flow = FlowLayout(host)
    buttons = [QPushButton(f"按鈕 {i}") for i in range(8)]
    for b in buttons:
        flow.addWidget(b)
    hint = QLabel("選取原文 → 翻譯 / 寫筆記 / 問這段 · Ctrl＋滾輪縮放")
    flow.addWidget(hint, optional=True)
    return host, flow, buttons, hint


def test_a_narrow_toolbar_wraps_and_never_clips():
    host, flow, buttons, hint = _toolbar()
    wide = flow.heightForWidth(4000)
    narrow = flow.heightForWidth(260)
    assert narrow > 2 * wide
    host.resize(260, narrow)
    flow.setGeometry(host.rect())
    for b in buttons:
        assert b.geometry().right() <= 260 and b.geometry().width() > 0
    # The hint gives way rather than taking a row of its own.
    assert hint.geometry().isEmpty()


def test_a_wide_toolbar_is_one_row_with_the_hint():
    host, flow, buttons, hint = _toolbar()
    host.resize(4000, flow.heightForWidth(4000))
    flow.setGeometry(host.rect())
    assert len({b.geometry().center().y() for b in buttons}) == 1
    assert not hint.geometry().isEmpty()
