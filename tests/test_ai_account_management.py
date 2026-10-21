import os

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from paper_daily import ai_accounts, ai_choices, llm
from paper_daily.desktop.ai_picker import AIPickerDialog
from paper_daily.desktop.ask import AskRunner


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_choices, "_account_labels", {})
    monkeypatch.setattr(AIPickerDialog, "_inspect", lambda *a, **k: None)
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])
    llm.save_settings(profile="personal", backend="cli", model="sonnet", isolated=True,
                      account_id="a" * 32)
    llm.save_settings(profile="work", backend="cli", model="opus", isolated=True,
                      account_id="b" * 32)
    yield app
    for widget in app.topLevelWidgets():
        if isinstance(widget, AIPickerDialog):
            widget.reject()
            widget.deleteLater()
    app.processEvents()


def test_account_names_include_identity_and_do_not_change_routing(workspace):
    cfg = llm.settings()
    ai_choices.remember_identity(cfg, "已登入：reader@example.org")
    ai_choices.rename_account(cfg, "Lab")
    assert ai_choices.account_title(cfg) == "Lab · reader@example.org"
    assert llm.settings() == cfg
    ai_choices.rename_account(cfg, "")
    assert ai_choices.account_title(cfg) == "reader@example.org"
    with pytest.raises(ValueError):
        ai_choices.rename_account(cfg, "bad\nname")


def test_account_picker_deduplicates_profiles_but_keeps_requested_profile(workspace):
    llm.save_settings(profile="shared-slides", backend="cli", model="haiku", isolated=True,
                      account_id="a" * 32)
    options = ai_choices.account_options("cli", "shared-slides")
    assert len(options) == 2
    assert next(cfg for cfg in options if cfg.account_id == "a" * 32).model == "haiku"
    assert llm.settings().profile == "personal"


def test_remove_used_account_is_blocked_without_changing_settings(workspace):
    cfg = llm.settings(profile="work")
    llm.save_task_choices({"slides": (cfg, "opus")})
    before = llm.SETTINGS_PATH.read_bytes()
    with pytest.raises(ValueError, match="仍被使用"):
        ai_choices.forget_account(cfg)
    assert llm.SETTINGS_PATH.read_bytes() == before
    with pytest.raises(ValueError, match="仍被使用"):
        ai_choices.forget_account(llm.settings())


def test_remove_unused_connection_keeps_vendor_files_and_other_accounts(workspace, tmp_path):
    cfg = llm.settings(profile="work")
    account_dir = llm.SETTINGS_PATH.parent / "ai-accounts" / "cli" / cfg.account_id
    account_dir.mkdir(parents=True)
    marker = account_dir / "fixture-vendor-owned"
    marker.write_text("fixture")
    ai_choices.rename_account(cfg, "Work")
    ai_choices.forget_account(cfg)
    assert llm.profile_names() == ["personal"]
    assert llm.settings().model == "sonnet" and marker.read_text() == "fixture"


def test_logout_cancel_then_failure_preserves_settings_and_scopes_account(workspace, monkeypatch):
    dialog = AIPickerDialog()
    dialog._select("cli", selected="work", check=False)
    before = llm.SETTINGS_PATH.read_bytes()
    calls = []

    def start(self, prompt, done, failed, call, **kwargs):
        value, reason = call(prompt)
        (done if value is not None else failed)(value if value is not None else reason)

    def auth(cfg, action):
        calls.append((cfg.account_id, action))
        return None, "fixture logout failed"

    monkeypatch.setattr(AskRunner, "start", start)
    monkeypatch.setattr(ai_accounts, "auth", auth)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    dialog._logout()
    assert not calls
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    dialog._logout()
    assert calls == [("b" * 32, "logout")]
    assert "failed" in dialog.notice.text() and dialog.manage_button.isEnabled()
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_rename_cancel_and_removal_warning_do_not_apply_changes(workspace, monkeypatch):
    dialog = AIPickerDialog()
    before = llm.SETTINGS_PATH.read_bytes()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a: ("Lab", False))
    dialog._rename()
    dialog._forget()
    assert "全域預設" in dialog.notice.text()
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_custom_id_is_explicit_and_task_choice_has_clear_scope(workspace):
    dialog = AIPickerDialog(task="slides")
    assert dialog.model.lineEdit().isReadOnly()
    dialog.custom_model.click()
    assert not dialog.model.lineEdit().isReadOnly()
    assert "只變更" in dialog.scope_hint.text() and "僅套用" in dialog.use_button.text()


def test_logout_success_keeps_routes_but_hides_old_quota(workspace, monkeypatch):
    dialog = AIPickerDialog()
    before = llm.SETTINGS_PATH.read_bytes()
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)

    def start(self, prompt, done, failed, call, **kwargs):
        answer, reason = call(prompt)
        (done if answer is not None else failed)(answer if answer is not None else reason)

    def auth(cfg, action):
        calls.append((cfg.account_id, action))
        return "signed out", "ok"

    monkeypatch.setattr(AskRunner, "start", start)
    monkeypatch.setattr(ai_accounts, "auth", auth)
    dialog._logout()
    dialog._cached_usage()
    assert calls == [("a" * 32, "logout")]
    assert "已登出" in dialog.account_status.text()
    assert not dialog.usage.scroll.isVisible()
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_nickname_before_first_login_does_not_activate_added_account(workspace):
    from paper_daily.ai_types import Settings

    llm.SETTINGS_PATH.unlink()
    ai_choices.rename_account(Settings("cli"), "Terminal")
    saved = ai_choices.save(ai_choices.new_account("codex"), "chosen", activate=False)
    assert llm.active_profile() != saved.profile
    assert llm.profile_fields(llm.active_profile())["backend"] == "auto"
