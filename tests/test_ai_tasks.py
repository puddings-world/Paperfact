"""Task models vary independently while login/account settings remain reusable."""

import json
import os

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit

from paper_daily import ai_accounts, ai_choices, ai_profiles, ai_usage, llm
from paper_daily.ai_types import Settings
from paper_daily.desktop.ai_picker import AIPickerDialog
from paper_daily.desktop.ai_tasks import AITasksDialog
from paper_daily.desktop.ask import AskRunner

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])
    monkeypatch.setattr(ai_accounts, "auth", lambda cfg, action: ("logged in", "ok"))
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: ["small", "large"])
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {"windows": [], "message": "fixture"})
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: None)

    def start(self, prompt, done, failed, call, **kwargs):
        value, reason = call(prompt)
        (done if value is not None else failed)(value if value is not None else reason)

    monkeypatch.setattr(AskRunner, "start", start)
    llm.save_settings(
        profile="personal", backend="cli", model="usual", isolated=True, account_id="a" * 32
    )
    llm.save_settings(
        profile="work", backend="codex", model="coding", isolated=True, account_id="b" * 32
    )
    yield app
    for widget in app.topLevelWidgets():
        if isinstance(widget, (AITasksDialog, AIPickerDialog)):
            widget.reject()
            widget.deleteLater()
    app.processEvents()


def choose(widget, task, backend, model):
    account, picker = widget.rows[task]
    index = next(i for i in range(1, account.count()) if account.itemData(i).backend == backend)
    account.setCurrentIndex(index)
    picker.setEditText(model)


def test_task_page_has_account_and_model_choices_without_api_fields(setup):
    widget = AITasksDialog()
    widget.show()
    setup.processEvents()
    assert set(widget.rows) == set(llm.TASKS)
    assert len(widget.findChildren(QLineEdit)) == len(llm.TASKS)
    for account, model in widget.rows.values():
        assert account.currentText() == "跟隨全域"
        assert not model.isEnabled()
        assert account.count() == 4
        assert {account.itemData(i).backend for i in range(1, account.count())} == {
            "cli",
            "codex",
            "gemini",
        }


def test_two_functions_can_share_login_but_use_different_models(setup):
    widget = AITasksDialog()
    before = ai_profiles.load(llm.SETTINGS_PATH)["profiles"]
    choose(widget, "translate", "cli", "small")
    choose(widget, "dive", "cli", "large")
    widget._save()
    assert llm.settings(task="translate").model == "small"
    assert llm.settings(task="dive").model == "large"
    assert llm.settings(task="dive").account_id == llm.settings(task="translate").account_id
    assert llm.settings().model == "usual"
    assert ai_profiles.load(llm.SETTINGS_PATH)["profiles"] == before
    reopened = AITasksDialog()
    assert reopened.rows["translate"][1].currentText() == "small"
    assert reopened.rows["dive"][1].currentText() == "large"


def test_service_default_model_is_distinct_from_global_default(setup):
    widget = AITasksDialog()
    choose(widget, "slides", "cli", "")
    widget.rows["slides"][1].setCurrentIndex(0)
    widget._save()
    assert llm.settings(task="slides").model is None
    assert llm.settings().model == "usual"
    reopened = AITasksDialog()
    assert reopened.rows["slides"][1].currentData() == ""


@pytest.mark.parametrize("model", ["sonnet", "fable"])
def test_task_alias_display_still_routes_exact_id(setup, monkeypatch, model):
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: [model])
    widget = AITasksDialog()
    widget.show()
    choose(widget, "slides", "cli", model)
    widget._pump()  # Wait for background discovery before choosing a returned option.
    picker = widget.rows["slides"][1]
    picker.setCurrentIndex(picker.findData(model))
    assert picker.currentText() == model.capitalize()
    widget._save()
    assert llm.settings(task="slides").model == model


def test_cancel_does_not_save_and_follow_default_clears_only_overrides(setup):
    llm.save_task_choices({"slides": (llm.settings(profile="work"), "large")})
    before = llm.SETTINGS_PATH.read_bytes()
    widget = AITasksDialog()
    widget._follow()
    widget.reject()
    assert llm.SETTINGS_PATH.read_bytes() == before
    widget = AITasksDialog()
    widget._follow()
    widget._save()
    assert not llm.task_routes()
    assert llm.settings(task="slides").model == "usual"
    assert llm.profile_names() == ["personal", "work"]


def test_account_manager_login_keeps_global_default_and_hides_models(setup):
    widget = AIPickerDialog(accounts_only=True)
    widget.show()
    setup.processEvents()
    assert not widget.model_row.isVisible() and not widget.advanced.isVisible()
    widget.providers["gemini"].click()
    widget.login_button.click()
    assert len(ai_choices.accounts()) == 3
    widget.use_button.click()
    assert llm.settings().profile == "personal" and llm.settings().model == "usual"


def test_existing_api_assignment_survives_without_editing_credentials(setup):
    llm.save_settings(profile="existing", backend="openai", api_key="secret", model="saved")
    llm.use_profile("existing", task="slides")
    original = ai_profiles.load(llm.SETTINGS_PATH)["profiles"]
    widget = AITasksDialog()
    choose(widget, "translate", "cli", "small")
    widget._save()
    assert llm.settings(task="slides").api_key == "secret"
    assert llm.settings(task="slides").model == "saved"
    assert ai_profiles.load(llm.SETTINGS_PATH)["profiles"] == original


def test_saving_invalid_selection_is_atomic(setup):
    before = llm.SETTINGS_PATH.read_bytes()
    with pytest.raises(ValueError):
        llm.save_task_choices({"ask": (llm.settings(), "small"), "unknown": None})
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_native_account_task_choice_preserves_implicit_default(setup, monkeypatch):
    llm.SETTINGS_PATH.unlink()
    monkeypatch.setattr(ai_profiles.shutil, "which", lambda name: None)
    llm.save_task_choices({"ask": (Settings("codex"), "custom")})
    assert llm.settings().backend == "none"
    assert llm.settings(task="ask").backend == "codex"
    assert llm.settings(task="ask").model == "custom"


def test_running_job_retains_task_model_when_choices_change(setup):
    cfg = llm.settings()
    llm.save_task_choices({"ask": (cfg, "small")})
    snapshot = llm.capture_connections()
    llm.save_task_choices({"ask": (cfg, "large")})
    with llm.connection_scope(snapshot):
        assert llm.settings(task="ask").model == "small"
    assert llm.settings(task="ask").model == "large"
    assert llm.settings(task="ask", profile="personal").model == "usual"


def test_legacy_route_changes_clear_obsolete_model_override(setup):
    llm.save_task_choices({"ask": (llm.settings(), "small")})
    llm.save_routes({"ask": "work"})
    assert llm.settings(task="ask").model == "coding"
    llm.save_task_choices({"ask": (llm.settings(), "small")})
    llm.use_profile("work", task="ask")
    assert llm.settings(task="ask").model == "coding"


def test_model_discovery_does_not_replace_a_changed_service(setup, monkeypatch):
    widget = AITasksDialog()
    widget.show()
    callbacks = []
    monkeypatch.setattr(widget.runner, "start", lambda *args, **kw: callbacks.append(args[1]))
    choose(widget, "slides", "codex", "draft-codex")
    widget._pump()
    choose(widget, "slides", "cli", "draft-claude")
    callbacks[0](json.dumps(["codex-only"]))
    assert widget.rows["slides"][1].currentText() == "draft-claude"
    assert widget.rows["slides"][1].findText("codex-only") < 0


def test_failed_write_keeps_dialog_and_saved_choices(setup, monkeypatch):
    widget = AITasksDialog()
    widget.show()
    before = llm.SETTINGS_PATH.read_bytes()
    choose(widget, "ask", "cli", "small")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(ai_profiles, "write", fail)
    widget._save()
    assert widget.isVisible() and "未儲存" in widget.status.text()
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_account_refresh_keeps_unsaved_task_choices(setup):
    widget = AITasksDialog()
    choose(widget, "translate", "cli", "draft-model")
    selections = widget._selections()
    ai_choices.save(ai_choices.new_account("gemini"), "", activate=False)
    widget._refresh(selections)
    assert widget.rows["translate"][1].currentText() == "draft-model"
    assert widget.rows["translate"][0].count() == 4
    assert not llm.task_routes()


def test_failed_model_discovery_keeps_manual_choice(setup, monkeypatch):
    widget = AITasksDialog()
    widget.show()
    choose(widget, "slides", "codex", "custom-model")

    def fail(cfg):
        raise TimeoutError()

    monkeypatch.setattr(ai_accounts, "models", fail)
    widget._pump()
    assert widget.rows["slides"][1].currentText() == "custom-model"
    assert "暫時無法取得" in widget.status.text()
    widget._save()
    assert llm.settings(task="slides").model == "custom-model"


def test_unsaved_local_service_is_selectable_without_changing_default(setup):
    before = llm.SETTINGS_PATH.read_bytes()
    widget = AITasksDialog()
    choose(widget, "translate", "gemini", "chosen-gemini")
    assert widget.rows["translate"][1].isEnabled()
    assert llm.SETTINGS_PATH.read_bytes() == before
    widget._save()
    assert llm.settings(task="translate").backend == "gemini"
    assert llm.settings(task="translate").model == "chosen-gemini"
    assert llm.settings().profile == "personal"


def test_login_does_not_discard_unsaved_local_connection_choice(setup):
    widget = AITasksDialog()
    choose(widget, "translate", "gemini", "local-draft")
    selections = widget._selections()
    ai_choices.save(ai_choices.new_account("gemini"), "", activate=False)
    widget._refresh(selections)
    account, model = widget.rows["translate"]
    assert account.currentData().backend == "gemini"
    assert account.currentData().account_id is None
    assert model.currentText() == "local-draft"
    assert not llm.task_routes()


def test_effective_labels_show_account_model_and_inheritance(setup):
    ai_choices.remember_identity(llm.settings(), "reader@example.org")
    widget = AITasksDialog()
    assert "reader@example.org" in widget.default_label.text()
    assert "沿用全域" in widget.effective["translate"].text()
    assert "usual" in widget.effective["translate"].text()
    choose(widget, "translate", "codex", "custom-model")
    assert "個別指定" in widget.effective["translate"].text()
    assert "Codex" in widget.effective["translate"].toolTip()
    assert "custom-model" in widget.effective["translate"].text()
    widget._follow()
    assert "reader@example.org" in widget.effective["translate"].toolTip()
    assert "custom-model" not in widget.effective["translate"].text()


def test_saved_task_choices_dispatch_to_correct_providers_and_models(setup, monkeypatch):
    from paper_daily.ai_types import Completion

    observed = []

    class Provider:
        def complete(self, request, cfg, post):
            observed.append((request.task, cfg.backend, cfg.model, cfg.account_id))
            return Completion("answer")

    for backend in ("cli", "codex", "gemini"):
        monkeypatch.setitem(llm._PROVIDERS, backend, Provider())
    widget = AITasksDialog()
    choose(widget, "translate", "cli", "small")
    choose(widget, "dive", "codex", "large")
    choose(widget, "slides", "gemini", "presentation-model")
    widget._save()
    for task in ("translate", "dive", "slides"):
        assert llm.complete_result("test", task=task).text == "answer"
    assert observed == [
        ("translate", "cli", "small", "a" * 32),
        ("dive", "codex", "large", "b" * 32),
        ("slides", "gemini", "presentation-model", None),
    ]
    receipts = [
        json.loads(line)
        for line in (llm.SETTINGS_PATH.parent / "ai-usage.jsonl").read_text().splitlines()
    ]
    assert [row["account_id"] for row in receipts] == ["a" * 32, "b" * 32, None]


def test_claude_discovery_is_background_and_shared_by_rows_for_same_account(setup, monkeypatch):
    calls, callbacks = [], []
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: calls.append(cfg) or ["fable"])
    widget = AITasksDialog()
    monkeypatch.setattr(
        widget.runner, "start", lambda _p, done, failed, call: callbacks.append((done, call))
    )
    widget.show()
    choose(widget, "slides", "cli", "draft-slides")
    choose(widget, "dive", "cli", "draft-dive")
    assert not calls
    widget._pump()
    done, fetch = callbacks.pop()
    answer, _reason = fetch("")
    done(answer)
    widget._pump()
    assert len(calls) == 1 and not callbacks
    for task, draft in (("slides", "draft-slides"), ("dive", "draft-dive")):
        assert widget.rows[task][1].findData("fable") >= 0
        assert widget.rows[task][1].currentText() == draft
    assert not llm.task_routes()


def test_failed_catalog_can_retry_same_account_without_losing_draft(setup, monkeypatch):
    widget = AITasksDialog()
    widget.show()
    choose(widget, "slides", "cli", "draft-model")
    calls = []

    def discover(cfg):
        calls.append(cfg)
        if len(calls) == 1:
            raise TimeoutError()
        return ["recovered-model"]

    monkeypatch.setattr(ai_accounts, "models", discover)
    widget._pump()
    account = widget.rows["slides"][0]
    selected = account.currentIndex()
    account.setCurrentIndex(0)
    account.setCurrentIndex(selected)
    widget.rows["slides"][1].setEditText("draft-model")
    widget._pump()
    assert len(calls) == 2
    assert widget.rows["slides"][1].findData("recovered-model") >= 0
    assert widget.rows["slides"][1].currentText() == "draft-model"


def test_inherited_rows_receive_official_versions_without_overrides(setup, monkeypatch):
    from paper_daily import model_catalog

    llm.save_settings(profile="personal", model="sonnet")

    def discover(cfg):
        model_catalog.remember(cfg, [{"value": "sonnet", "displayName": "Sonnet 5.5"}])
        return ["sonnet"]

    monkeypatch.setattr(ai_accounts, "models", discover)
    widget = AITasksDialog()
    widget.show()
    widget._pump()
    assert "Sonnet 5.5" in widget.default_label.text()
    assert all(model.currentText() == "Sonnet 5.5" for _, model in widget.rows.values())
    assert not llm.task_routes()


def test_task_filter_and_custom_ids_keep_unsaved_choices(setup):
    widget = AITasksDialog()
    widget.show()
    choose(widget, "slides", "cli", "draft-model")
    widget.only_overrides.setChecked(True)
    assert widget.rows["slides"][1].isVisible()
    assert not widget.rows["ask"][1].isVisible()
    widget.custom_models.setChecked(True)
    assert all(not model.lineEdit().isReadOnly() for _, model in widget.rows.values())
    widget.only_overrides.setChecked(False)
    assert widget.rows["slides"][1].currentText() == "draft-model"
    assert not llm.task_routes()


def test_hidden_dialog_refreshes_inherited_version_when_later_opened(setup):
    from paper_daily import model_catalog

    llm.save_settings(profile="personal", model="sonnet")
    widget = AITasksDialog()
    widget._pump()  # A timer may fire before this dialog becomes visible.
    model_catalog.remember(llm.settings(), [{"value": "sonnet", "displayName": "Sonnet 5.5"}])
    widget.show()
    assert all(model.currentText() == "Sonnet 5.5" for _, model in widget.rows.values())
    assert "Sonnet 5.5" in widget.default_label.text()
