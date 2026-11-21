"""AI settings are one window: the default, each feature's AI, and agent hosts."""

import json

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_ai_tasks import choose
from test_ai_tasks import setup as _setup

from paper_daily import llm
from paper_daily.desktop.ai_settings import DEFAULT, FEATURES, HOSTS, AISettingsPage

setup = _setup


@pytest.fixture
def page(setup):
    widget = AISettingsPage()
    widget.show()
    setup.processEvents()
    yield widget
    widget.features.dirty = False
    widget.reject()
    widget.deleteLater()
    setup.processEvents()


def answer(monkeypatch, label):
    """Click the unsaved-changes prompt's button with this label."""

    def run(box):
        button = next(b for b in box.buttons() if b.text() == label)
        monkeypatch.setattr(box, "clickedButton", lambda: button)

    monkeypatch.setattr(QMessageBox, "exec", run)


def test_one_window_holds_the_default_the_features_and_agent_hosts(page):
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "全域預設",
        "各功能的 AI",
        "連接外部 agent",
    ]
    assert page.tabs.currentIndex() == DEFAULT
    # The parts do not open one another as further windows.
    assert not page.default.advanced.isVisible()
    assert not page.features.accounts_button.isVisible()
    assert list(page.default.providers) == ["cli", "codex", "api"]


def test_setting_the_default_keeps_the_window_open_and_the_feature_tab_follows(page, setup):
    page.default.providers["codex"].click()
    page.default.model.setCurrentIndex(page.default.model.findData("large"))
    page.default.use_button.click()
    setup.processEvents()
    assert page.isVisible() and page.default.isVisible()
    assert (llm.settings().backend, llm.settings().model) == ("codex", "large")
    assert "已設為全域預設" in page.default.notice.text()
    assert "Codex" in page.features.default_label.text()
    assert not page.features.dirty


def test_the_feature_tab_sends_the_reader_to_the_default_tab(page):
    page.tabs.setCurrentIndex(FEATURES)
    page.features.default_button.click()
    assert page.tabs.currentIndex() == DEFAULT


def test_saving_feature_choices_keeps_the_window_open(page, setup):
    page.tabs.setCurrentIndex(FEATURES)
    choose(page.features, "ask", "codex", "large")
    page.features._edited()
    page.features.save_button.click()
    assert page.isVisible() and page.features.isVisible()
    assert "已儲存" in page.features.status.text() and not page.features.dirty
    assert (llm.settings(task="ask").backend, llm.settings(task="ask").model) == ("codex", "large")


def test_closing_with_unsaved_feature_choices_asks_first(page, monkeypatch):
    choose(page.features, "ask", "codex", "large")
    page.features._edited()
    answer(monkeypatch, "繼續編輯")
    page.reject()
    assert page.isVisible() and page.tabs.currentIndex() == FEATURES
    assert "ask" not in llm.task_routes()
    answer(monkeypatch, "不儲存")
    page.reject()
    assert not page.isVisible() and "ask" not in llm.task_routes()


def test_closing_can_save_the_unsaved_feature_choices(page, monkeypatch):
    choose(page.features, "ask", "codex", "large")
    page.features._edited()
    answer(monkeypatch, "儲存分配")
    page.reject()
    assert not page.isVisible()
    assert llm.settings(task="ask").backend == "codex"


def test_closing_without_changes_does_not_ask(page, monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda box: pytest.fail("asked"))
    before = llm.SETTINGS_PATH.read_bytes()
    page.tabs.setCurrentIndex(FEATURES)
    page.reject()
    assert not page.isVisible() and llm.SETTINGS_PATH.read_bytes() == before


def test_escape_in_a_tab_closes_the_window_not_the_tab(page):
    page.default.reject()
    assert not page.isVisible()


def test_the_window_stays_open_while_a_sign_in_is_running(page, monkeypatch):
    monkeypatch.setattr(type(page.default.auth_runner), "busy", property(lambda self: True))
    page.tabs.setCurrentIndex(HOSTS)
    page.reject()
    assert page.isVisible() and page.tabs.currentIndex() == DEFAULT
    assert "請稍候" in page.default.notice.text()
    monkeypatch.undo()


def test_the_agent_host_tab_gives_the_connection_and_changes_no_setting(page):
    before = llm.SETTINGS_PATH.read_bytes()
    page.tabs.setCurrentIndex(HOSTS)
    entry = json.loads(page.hosts.config.toPlainText())["mcpServers"]["paperfact"]
    assert "mcp" in entry["args"] and "--workspace" in entry["args"]
    page.hosts.copy_button.click()
    assert QApplication.clipboard().text() == page.hosts.config.toPlainText()
    assert page.hosts.copied.text() == "已複製。"
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_the_toolbar_opens_the_settings_window():
    from paper_daily.desktop import main

    source = main.MainWindow._ai_settings.__code__
    assert "AISettingsPage" in source.co_names and "AIPickerDialog" not in source.co_names
