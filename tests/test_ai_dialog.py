"""The settings UI saves independent profiles and keeps task routes intact."""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily import llm  # noqa: E402
from paper_daily.desktop.ai_dialog import AISettingsDialog  # noqa: E402


@pytest.fixture
def dialog(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")) or key in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(backend="anthropic", api_key="stored-secret", model="original-model")
    from PySide6.QtWidgets import QMessageBox

    def unexpected_warning(_parent, _title, message):
        pytest.fail(message)

    monkeypatch.setattr(QMessageBox, "warning", unexpected_warning)
    widget = AISettingsDialog()
    yield widget, app
    widget.reject()
    widget.deleteLater()
    app.processEvents()


def test_existing_key_is_not_displayed_and_survives_editing_the_model(dialog):
    widget, app = dialog
    assert widget.name_edit.text() == "default"
    assert widget.backend_picker.currentData() == "anthropic"
    assert widget.key_edit.text() == ""
    widget.model_edit.setText("updated-model")
    assert widget._save()
    cfg = llm.settings()
    assert cfg.model == "updated-model" and cfg.api_key == "stored-secret"
    widget.show()
    app.processEvents()
    Path("build").mkdir(exist_ok=True)
    assert widget.grab().save("build/paperfact-ai-settings.png")


def test_new_profile_and_task_route_can_be_saved_without_changing_default(dialog):
    widget, _app = dialog
    widget.model_edit.setText("main-model")
    assert widget._save()
    widget.profile_picker.setCurrentIndex(widget.profile_picker.count() - 1)
    widget.name_edit.setText("local")
    widget.backend_picker.setCurrentIndex(widget.backend_picker.findData("openai"))
    widget.model_edit.setText("local-model")
    widget.base_edit.setText("http://localhost:11434/v1")
    widget.requires_key.setChecked(False)
    widget.make_default.setChecked(False)
    assert widget._save()
    picker = widget.routes["translate"]
    picker.setCurrentIndex(picker.findData("local"))
    assert widget._save()
    data = json.loads(llm.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert data["active_profile"] == "default"
    assert data["routes"]["translate"] == "local"
    cfg = llm.settings(task="translate")
    assert cfg.model == "local-model" and cfg.api_key is None and not cfg.requires_key
    assert llm.settings().api_key == "stored-secret"


def test_with_nothing_saved_the_form_shows_what_actually_runs(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    widget = AISettingsDialog()
    try:
        # The app falls back to "auto"; the form must not pretend it is OpenAI.
        assert widget.backend_picker.currentData() == "auto"
        assert widget.resolved.text().startswith("目前實際使用：")
        assert not widget.route_hint.isHidden()
        assert [
            widget.routes["dive"].itemData(i) for i in range(widget.routes["dive"].count())
        ] == [None]
    finally:
        widget.reject()
        widget.deleteLater()
        app.processEvents()


def test_the_route_hint_goes_once_a_profile_exists(dialog):
    widget, _app = dialog
    assert "original-model" in widget.resolved.text()
    assert not widget.route_hint.isHidden()
    llm.save_settings(profile="strong", backend="anthropic", model="strong-model")
    widget._refresh_routes()
    assert widget.route_hint.isHidden()
    assert widget.routes["dive"].findData("strong") > 0


def test_new_cli_connections_can_keep_separate_accounts_or_share_one(dialog):
    widget, _app = dialog
    widget.presets.setCurrentIndex(widget.presets.findData("cli"))
    widget._preset(0)
    widget.name_edit.setText("personal")
    widget.model_edit.setText("sonnet")
    assert widget._save()
    personal = llm.settings(profile="personal")
    assert personal.account_id and personal.isolated
    assert widget.base_edit.isHidden() and widget.key_edit.isHidden()
    assert not widget.account_picker.isHidden()
    widget.presets.setCurrentIndex(widget.presets.findData("cli"))
    widget._preset(0)
    widget.name_edit.setText("work")
    assert widget._save()
    assert llm.settings(profile="work").account_id != personal.account_id
    widget.presets.setCurrentIndex(widget.presets.findData("cli"))
    widget._preset(0)
    widget.name_edit.setText("personal-opus")
    widget.model_edit.setText("opus")
    widget.account_picker.setCurrentIndex(widget.account_picker.findData(personal.account_id))
    assert widget._save()
    assert llm.settings(profile="personal-opus").account_id == personal.account_id


def test_local_preset_needs_no_login_or_api_key(dialog):
    widget, _app = dialog
    widget.presets.setCurrentIndex(widget.presets.findData("local"))
    widget._preset(0)
    widget.name_edit.setText("local")
    widget.model_edit.setText("my-local-model")
    assert widget._save()
    cfg = llm.settings(profile="local")
    assert cfg.base_url == "http://localhost:11434/v1"
    assert not cfg.requires_key and cfg.api_key is None
    assert widget.auth_bar.isHidden()


def test_status_refresh_preserves_task_overrides_after_explicit_global_change(
    dialog, monkeypatch
):
    from paper_daily.desktop.ai_dialog import AIStatusButton

    widget, _app = dialog
    assert widget._save()
    llm.save_settings(profile="work", backend="codex", isolated=True)
    llm.use_profile("default", task="slides")
    monkeypatch.setenv("PAPERFACT_PROFILE", "default")
    switch = AIStatusButton()
    llm.use_profile("work", desktop=True)
    switch.refresh()
    assert llm.settings().profile == "work"
    assert llm.settings(task="slides").profile == "default"
    assert "Codex" in switch.text()
    switch.deleteLater()


def test_routing_can_be_saved_without_creating_an_unfinished_connection(dialog):
    widget, _app = dialog
    assert widget._save()
    llm.use_profile("default", task="slides")
    widget._refresh_routes()
    widget.profile_picker.setCurrentIndex(widget.profile_picker.count() - 1)
    widget._follow_default()
    assert widget._save_routes()
    assert llm.task_routes() == {}
    assert llm.profile_names() == ["default"]


def test_changing_provider_clears_fields_from_the_previous_provider(dialog):
    widget, _app = dialog
    widget.base_edit.setText("https://old.example/v1")
    widget.key_edit.setText("old-secret")
    widget.key_env_edit.setText("OLD_KEY")
    widget.backend_picker.setCurrentIndex(widget.backend_picker.findData("openai"))
    assert not widget.base_edit.text() and not widget.key_edit.text()
    assert not widget.key_env_edit.text() and not widget.model_edit.text()


def test_login_button_uses_selected_account_and_restores_ui_on_failure(dialog, monkeypatch):
    from paper_daily import ai_accounts

    widget, _app = dialog
    widget.presets.setCurrentIndex(widget.presets.findData("cli"))
    widget._preset(0)
    widget.name_edit.setText("login-test")
    seen = []

    def auth(cfg, action):
        seen.append((cfg, action))
        return None, "login denied"

    def start(_prompt, done, failed, call, **_kwargs):
        answer, reason = call("")
        (done if answer else failed)(answer or reason)

    monkeypatch.setattr(ai_accounts, "auth", auth)
    monkeypatch.setattr(widget.runner, "start", start)
    widget.login_button.click()
    assert seen[0][0].account_id == llm.settings(profile="login-test").account_id
    assert seen[0][1] == "login"
    assert widget.status.text() == "login denied"
    assert widget.tabs.isEnabled() and widget.save_button.isEnabled()


@pytest.mark.parametrize("succeeds", [True, False])
def test_model_discovery_preserves_selection_and_restores_controls(dialog, monkeypatch, succeeds):
    from paper_daily import ai_providers

    widget, _app = dialog
    seen = []

    def list_models(cfg):
        seen.append(cfg)
        return (["new-a", "new-b"], "ok") if succeeds else ([], "service unavailable")

    def start(_prompt, done, failed, call, **_kwargs):
        assert not widget.tabs.isEnabled() and not widget.save_button.isEnabled()
        answer, reason = call("")
        (done if answer else failed)(answer or reason)

    monkeypatch.setattr(ai_providers, "list_models", list_models)
    monkeypatch.setattr(widget.runner, "start", start)
    widget.models_button.click()
    assert seen[0].api_key == "stored-secret"
    assert widget.model_edit.text() == "original-model"
    assert llm.settings().model == "original-model"
    assert widget.tabs.isEnabled() and widget.save_button.isEnabled()
    if succeeds:
        assert widget.model_picker.findText("new-b") >= 0
    else:
        assert widget.status.text() == "service unavailable"


def test_connection_settings_scroll_on_a_small_window(dialog):
    widget, app = dialog
    widget.resize(660, 480)
    widget.advanced.setChecked(True)
    widget.show()
    app.processEvents()
    scroll = widget.tabs.widget(0)
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(widget.token_parameter)
    assert scroll.verticalScrollBar().value() > 0
    assert widget.save_button.isVisible()
