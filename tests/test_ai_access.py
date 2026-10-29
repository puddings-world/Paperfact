import os

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from paper_daily import ai_accounts, llm
from paper_daily.ai_types import Settings
from paper_daily.desktop import ai_access

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_missing_login_blocks_provider_and_reports_the_actual_task(monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    bridge = ai_access.AccessBridge(owner)
    bridge.needed.disconnect()
    seen = []
    bridge.needed.connect(lambda task, reason: seen.append((task, reason)))
    monkeypatch.setattr(ai_accounts, "auth", lambda cfg, action: (None, "not signed in"))
    monkeypatch.setattr(llm, "ACCESS_CHECK", bridge.check)
    monkeypatch.setattr(
        llm._PROVIDERS["codex"],
        "complete",
        lambda *a: pytest.fail("unauthenticated model was invoked"),
    )
    result = llm.complete_result("question", cfg=Settings("codex"), task="slides")
    assert result.text is None and "登入" in result.reason
    assert seen == [("slides", "not signed in")]
    owner.deleteLater()
    app.processEvents()


def test_ready_accounts_and_local_api_do_not_require_another_login(monkeypatch):
    monkeypatch.setattr(ai_accounts, "auth", lambda cfg, action: ("me@example.org", "ok"))
    assert ai_access.readiness(Settings("codex")) == ""
    assert ai_access.readiness(Settings("openai", requires_key=False)) == ""
    assert ai_access.readiness(Settings("openai", api_key="local-key")) == ""
    assert ai_access.readiness(Settings("openai"))
    assert ai_access.readiness(Settings("none"))


def test_preflight_checks_task_route_and_does_not_run_on_a_changed_paper(monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.paper_id = "first"
    bridge = ai_access.AccessBridge(owner)
    observed, callbacks = [], []
    monkeypatch.setattr(llm, "settings", lambda task: Settings("codex", profile=task))
    monkeypatch.setattr(bridge, "check", lambda cfg, task: observed.append(cfg.profile) or "")

    def start(prompt, done, failed, call):
        value, _reason = call(prompt)
        callbacks.append(lambda: done(value))

    monkeypatch.setattr(bridge.runner, "start", start)
    ran = []
    bridge.run(owner, ["slides"], lambda: ran.append(True))
    owner.paper_id = "second"
    callbacks[0]()
    assert observed == ["slides"] and not ran
    owner.deleteLater()
    app.processEvents()


def test_task_login_picker_saves_task_account_without_replacing_global(tmp_path, monkeypatch):
    from paper_daily.desktop.ai_picker import AIPickerDialog

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key)
    llm.save_settings(profile="global", backend="cli", model="global-model", isolated=True)
    llm.save_settings(
        profile="slides-account", backend="gemini", model="slide-model", isolated=True
    )
    llm.use_profile("global", desktop=True)
    llm.use_profile("slides-account", task="slides", desktop=True)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: [])
    monkeypatch.setattr(AIPickerDialog, "_inspect", lambda self: None)
    widget = AIPickerDialog(task="slides")
    assert widget.cfg.profile == "slides-account"
    widget._use()
    assert llm.settings(task="slides").model == "slide-model"
    assert llm.settings().profile == "global"
    widget.deleteLater()
    app.processEvents()


def test_closing_creation_dialog_during_login_check_does_not_create_hidden_list(monkeypatch):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.show()
    bridge = ai_access.AccessBridge(owner)
    callbacks, created = [], []
    monkeypatch.setattr(
        bridge.runner, "start", lambda prompt, done, failed, call: callbacks.append(done)
    )
    bridge.run(owner, ["list_parse"], lambda: created.append(True))
    owner.close()
    callbacks[0]("ready")
    assert not created
    owner.deleteLater()
    app.processEvents()


def test_missing_login_opens_one_account_picker_for_requested_feature(monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel

    from paper_daily.desktop import ai_picker

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    opened = []

    class Picker(QDialog):
        def __init__(self, parent, *, task):
            super().__init__(parent)
            self.notice = QLabel(self)
            opened.append(task)

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    bridge = ai_access.AccessBridge(owner)
    bridge.show_login("list_parse", "Please sign in")
    assert bridge.dialog.isVisible()
    assert "Please sign in" in bridge.dialog.notice.text()
    bridge.show_login("list_parse", "Please sign in")
    assert opened == ["list_parse"]
    bridge.dialog.reject()
    assert bridge.dialog is None
    owner.deleteLater()
    app.processEvents()


def test_a_request_made_during_another_check_waits_instead_of_vanishing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    first, second = QWidget(), QWidget()
    bridge = ai_access.AccessBridge(first)
    monkeypatch.setattr(llm, "settings", lambda task: Settings("codex", profile=task))
    checked = []
    monkeypatch.setattr(bridge, "check", lambda cfg, task: checked.append(task) or "")
    running = []

    def start(prompt, done, failed, call):
        value, _reason = call(prompt)
        running.append(lambda: done(value))

    monkeypatch.setattr(bridge.runner, "start", start)
    monkeypatch.setattr(type(bridge.runner), "busy", property(lambda self: bool(running)))
    ran = []
    bridge.run(first, ["slides"], lambda: ran.append("slides"))
    bridge.run(first, ["slides"], lambda: ran.append("slides again"))
    bridge.run(second, ["survey"], lambda: ran.append("survey"))
    assert checked == ["slides"] and len(running) == 1
    running.pop()()
    assert ran == ["slides"] and checked == ["slides", "survey"]
    running.pop()()
    assert ran == ["slides", "survey"]
    first.deleteLater()
    second.deleteLater()
    app.processEvents()
