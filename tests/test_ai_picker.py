"""Normal users select a service and a model without editing connection internals."""

import json
import os

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QProgressBar

from paper_daily import ai_accounts, ai_choices, ai_usage, llm, usage_cache
from paper_daily.desktop.ai_picker import AIPickerDialog
from paper_daily.desktop.ask import AskRunner

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def picker(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_accounts, "command", lambda backend: [backend])
    monkeypatch.setattr(ai_accounts, "auth", lambda cfg, action: ("已登入：me@example.org", "ok"))
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: ["model-a", "model-b"])
    monkeypatch.setattr(
        ai_usage, "subscription", lambda cfg: {"windows": [], "message": cfg.backend + " quota"}
    )
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: {
        "calls": 15, "failed": 0, "input": 0, "output": 0, "unknown": 15,
    })

    def start(self, _prompt, done, failed, call, **kwargs):
        answer, reason = call("")
        (done if answer is not None else failed)(answer if answer is not None else reason)

    monkeypatch.setattr(AskRunner, "start", start)
    llm.save_settings(profile="old", backend="cli", model="before", isolated=True)
    widget = AIPickerDialog()
    widget.show()
    app.processEvents()
    yield widget, app
    widget.reject()
    widget.deleteLater()
    app.processEvents()


def test_home_has_three_services_and_only_one_text_input(picker):
    widget, _app = picker
    assert list(widget.providers) == ["cli", "codex", "gemini"]
    assert [w for w in widget.findChildren(QLineEdit) if w.isVisible()] == [widget.model.lineEdit()]
    assert not widget.accounts.isVisible()
    assert "me@example.org" in widget.account_status.text()


def test_browsing_services_does_not_change_active_account(picker):
    widget, _app = picker
    before = llm.SETTINGS_PATH.read_bytes()
    widget.providers["codex"].click()
    widget.providers["gemini"].click()
    assert llm.SETTINGS_PATH.read_bytes() == before
    assert widget.cfg.backend == "gemini"


def test_select_model_then_use_preserves_account_and_task_overrides(picker):
    widget, _app = picker
    llm.save_settings(profile="slides", backend="codex", model="slides-model")
    llm.use_profile("slides", task="slides")
    widget.model.setCurrentIndex(widget.model.findData("model-b"))
    widget.use_button.click()
    assert llm.settings().model == "model-b"
    assert llm.settings().profile == "old"
    assert llm.settings(task="slides").model == "slides-model"


def test_new_service_needs_no_profile_name_and_custom_models_work(picker):
    widget, _app = picker
    widget.providers["gemini"].click()
    widget.model.setEditText("future-model")
    widget.use_button.click()
    assert llm.settings().backend == "gemini"
    assert llm.settings().model == "future-model"
    assert llm.settings().profile


def test_default_model_label_is_never_sent_as_a_model_id(picker):
    widget, _app = picker
    widget.model.setCurrentIndex(0)
    widget.use_button.click()
    assert not llm.settings().model


def test_login_creates_separate_account_without_replacing_default(picker, monkeypatch):
    widget, _app = picker
    calls = []

    def auth(cfg, action):
        calls.append((cfg, action))
        return "登入完成", "ok"

    monkeypatch.setattr(ai_accounts, "auth", auth)
    widget.providers["gemini"].click()
    widget.login_button.click()
    logged_in = next(cfg for cfg, action in calls if action == "login")
    assert logged_in.account_id and logged_in.cli_home
    assert widget.cfg.account_id == logged_in.account_id
    assert llm.settings().profile == "old"
    widget.use_button.click()
    assert llm.settings().account_id == logged_in.account_id


def test_failed_login_keeps_original_settings_and_restores_controls(picker, monkeypatch):
    widget, _app = picker
    before = llm.SETTINGS_PATH.read_bytes()
    monkeypatch.setattr(ai_accounts, "auth", lambda *a: (None, "login cancelled"))
    widget.login_button.click()
    assert llm.SETTINGS_PATH.read_bytes() == before
    assert widget.notice.text() == "login cancelled"
    assert widget.providers["codex"].isEnabled() and widget.use_button.isEnabled()


def test_late_status_cannot_replace_another_services_account(picker, monkeypatch):
    widget, _app = picker
    callbacks = []
    monkeypatch.setattr(widget.runner, "start", lambda *a, **kw: callbacks.append(a[1]))
    widget._inspect()
    widget._select("codex", check=False)
    callbacks[0]('{"account":"wrong account","models":["wrong-model"]}')
    assert "wrong" not in widget.account_status.text()
    assert widget.model.findText("wrong-model") < 0


def test_first_login_can_be_saved_without_activating_it(picker):
    widget, _app = picker
    llm.SETTINGS_PATH.unlink()
    cfg = ai_choices.new_account("gemini")
    saved = ai_choices.save(cfg, "", activate=False)
    assert llm.active_profile() != saved.profile
    assert llm.profile_fields(saved.profile)["account_id"] == cfg.account_id


@pytest.mark.parametrize("backend", ["cli", "codex"])
def test_model_discovery_failure_is_visible_without_losing_selection(picker, monkeypatch, backend):
    widget, _app = picker
    widget._select(backend, check=False)
    widget.model.setEditText("my-model")

    def fail(cfg):
        raise TimeoutError()

    monkeypatch.setattr(ai_accounts, "models", fail)
    widget._inspect()
    assert "暫時無法取得" in widget.notice.text()
    assert widget._model() == "my-model"


def test_usage_is_inline_for_browsed_account_without_switching_default(picker):
    # User-requested replacement of the separate usage dialog action.
    widget, _app = picker
    before = llm.SETTINGS_PATH.read_bytes()
    widget.providers["gemini"].click()
    # Plan is now always visible, including an explicit unknown state.
    assert widget.usage.isVisible()
    assert widget.usage.quota_status.text() == "gemini quota\n方案：官方未提供"
    assert "15 次呼叫" in widget.usage.local.text()
    assert "總量未知" in widget.usage.local.text()
    assert "輸入 0" not in widget.usage.local.text()
    assert not widget.usage.scroll.isVisible()
    widget.usage.refresh_button.click()
    assert llm.SETTINGS_PATH.read_bytes() == before


def test_inline_quota_refresh_failure_and_retry_preserve_model(picker, monkeypatch):
    widget, _app = picker
    widget.model.setEditText("custom-version")
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {
        "windows": [{"label": "fixture", "used": 42, "minutes": 300, "reset": None}],
        "message": "official", "plan": "plus",
    })
    widget.usage.refresh_button.click()
    assert widget.usage.scroll.isVisible()
    assert widget.usage.findChild(QProgressBar).value() == 420
    assert "plus" in widget.usage.quota_status.text()
    with monkeypatch.context() as failure:
        failure.setattr(
            widget.runner, "start", lambda prompt, done, failed, call: failed("offline")
        )
        widget.usage.refresh_button.click()
        assert not widget.usage.scroll.isVisible() and widget.usage.windows.count() == 0
        assert "未知" in widget.usage.quota_status.text()
        assert widget.usage.refresh_button.isEnabled()
    widget.usage.refresh_button.click()
    assert widget.usage.windows.count() == 2
    assert widget._model() == "custom-version"


def test_stale_usage_cannot_appear_under_another_account(picker, monkeypatch):
    widget, _app = picker
    callbacks = []
    monkeypatch.setattr(widget.runner, "start", lambda *a, **kw: callbacks.append(a[1]))
    widget._inspect()
    widget._select("gemini", check=False)
    assert "15 次呼叫" not in widget.usage.local.text()
    callbacks[0](json.dumps({
        "account": "wrong@example.org", "models": [],
        "quota": {"windows": [], "message": "wrong quota"},
        "local": {"calls": 999, "failed": 0, "input": 0, "output": 0, "unknown": 0},
    }))
    assert "wrong" not in widget.usage.quota_status.text()
    assert "999" not in widget.usage.local.text()
    assert widget.usage.backend == "gemini"


@pytest.mark.parametrize("model", ["sonnet", "opus", "haiku", "fable"])
def test_readable_model_name_still_saves_original_id(picker, monkeypatch, model):
    widget, _app = picker
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: [model])
    widget._select("cli")
    widget.model.setCurrentIndex(widget.model.findData(model))
    assert widget.model.currentText() == model.capitalize()
    assert "使用權限依你的方案" in widget.model_hint.text()
    widget.use_button.click()
    assert llm.settings().model == model


def test_default_and_full_id_are_explained_without_guessing_version(picker):
    widget, _app = picker
    widget.model.setCurrentIndex(0)
    assert "預設模型" in widget.model.currentText()
    assert "目前的預設模型" in widget.model_hint.text()
    widget.model.setEditText("claude-sonnet-specific-version")
    assert "使用你指定的模型" in widget.model_hint.text()
    widget.use_button.click()
    assert llm.settings().model == "claude-sonnet-specific-version"


def test_official_friendly_name_selection_saves_model_id_and_advanced_entry(picker, monkeypatch):
    from paper_daily import model_catalog

    widget, _app = picker

    def discover(cfg):
        model_catalog.remember(cfg, [{"value": "fable", "displayName": "Fable 5.1"}])
        return ["fable"]

    monkeypatch.setattr(ai_accounts, "models", discover)
    widget._select("cli")
    widget.model.setCurrentIndex(widget.model.findData("fable"))
    assert widget.model.currentText() == "Fable 5.1"
    assert "進階設定" in widget.advanced.text()
    widget.use_button.click()
    assert llm.settings().model == "fable"


def test_usage_failure_does_not_hide_account_or_local_receipts(picker, monkeypatch):
    widget, _app = picker

    def unavailable(cfg):
        raise TimeoutError("sensitive provider response")

    monkeypatch.setattr(ai_usage, "subscription", unavailable)
    widget.usage.refresh_button.click()
    assert "me@example.org" in widget.account_status.text()
    assert "15 次呼叫" in widget.usage.local.text()
    assert "未知" in widget.usage.quota_status.text()
    assert "sensitive" not in widget.usage.quota_status.text()


def test_both_standard_quota_windows_are_readable_without_scrolling(picker, monkeypatch):
    from PySide6.QtTest import QTest

    widget, _app = picker
    monkeypatch.setattr(ai_usage, "subscription", lambda cfg: {
        "windows": [
            {"label": "Codex", "used": 42, "minutes": 300, "reset": None},
            {"label": "Codex", "used": 17, "minutes": 10080, "reset": None},
        ],
        "message": "official",
    })
    widget.usage.refresh_button.click()
    QTest.qWait(30)
    viewport = widget.usage.scroll.viewport()
    bars = [bar for bar in widget.usage.findChildren(QProgressBar) if bar.isVisible()]
    assert [bar.value() for bar in bars] == [420, 170]
    for bar in bars:
        assert viewport.rect().contains(bar.mapTo(viewport, bar.rect().center()))


def test_cached_usage_appears_before_auth_and_live_refresh_updates_open_page(picker, monkeypatch):
    widget, _app = picker
    cfg = widget.cfg
    calls = []
    monkeypatch.setattr(widget.runner, "start", lambda *args, **kwargs: calls.append(True))
    widget._select(cfg.backend, selected=cfg.profile)
    assert calls and "15 次呼叫" in widget.usage.local.text()
    monkeypatch.setattr(ai_usage, "local_summary", lambda cfg: {
        "calls": 16, "failed": 0, "input": 10, "output": 20, "unknown": 15,
    })
    usage_cache.cache.read(cfg, force=True)
    widget._cached_usage()
    assert "16 次呼叫" in widget.usage.local.text()
    assert "輸入 10" in widget.usage.local.text()


def test_claude_catalog_loads_in_worker_and_fable_saves_without_losing_routes(picker, monkeypatch):
    widget, _app = picker
    calls = []
    callbacks = []
    llm.save_settings(profile="slides", backend="codex", model="slides-model")
    llm.use_profile("slides", task="slides")
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: calls.append(cfg) or ["fable"])
    monkeypatch.setattr(
        widget.runner, "start", lambda _p, done, failed, call: callbacks.append((done, call))
    )
    before = llm.SETTINGS_PATH.read_bytes()
    widget._select("cli")
    assert not calls and callbacks  # Discovery never runs synchronously on the GUI thread.
    done, work = callbacks.pop()
    response, _reason = work("")
    done(response)
    assert calls == [widget.cfg]
    assert widget.model.findData("fable") >= 0
    assert llm.SETTINGS_PATH.read_bytes() == before
    widget.model.setCurrentIndex(widget.model.findData("fable"))
    widget.use_button.click()
    assert llm.settings().model == "fable"
    assert llm.settings(task="slides").model == "slides-model"


def test_claude_retry_clears_error_and_empty_catalog_keeps_only_manual_model(picker, monkeypatch):
    widget, _app = picker
    widget.model.setEditText("my-version")

    def fail(_cfg):
        raise TimeoutError()

    monkeypatch.setattr(ai_accounts, "models", fail)
    widget._inspect()
    assert "暫時無法取得" in widget.notice.text()
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: ["fable"])
    widget._inspect()
    assert widget.notice.text() == "" and widget._model() == "my-version"
    assert widget.model.findData("fable") >= 0
    monkeypatch.setattr(ai_accounts, "models", lambda cfg: [])
    widget._inspect()
    assert widget.model.findData("fable") == -1
    assert widget._model() == "my-version" and "未回傳" in widget.notice.text()


def test_claude_catalog_result_cannot_cross_accounts(picker, monkeypatch):
    widget, _app = picker
    callbacks = []
    monkeypatch.setattr(widget.runner, "start", lambda *a, **kw: callbacks.append(a[1]))
    widget._inspect()
    cfg = ai_choices.new_account("cli", "separate-model")
    saved = ai_choices.save(cfg, cfg.model, activate=False)
    widget._select("cli", selected=saved.profile, check=False)
    callbacks[0](json.dumps({"account": "wrong account", "models": ["wrong-model"]}))
    assert widget.cfg.account_id == cfg.account_id
    assert widget.model.findData("wrong-model") < 0
    assert widget._model() == "separate-model"
    assert "wrong" not in widget.account_status.text()


def test_task_picker_reads_override_and_saves_without_changing_shared_profile(picker):
    _widget, _app = picker
    llm.save_task_choices({"slides": (llm.settings(), "slides-only")})
    before = llm.profile_fields("old")
    dialog = AIPickerDialog(task="slides")
    assert dialog._model() == "slides-only"
    dialog.model.setEditText("new-slides-only")
    dialog._use()
    assert llm.settings(task="slides").model == "new-slides-only"
    assert llm.settings(task="ask").model == "before"
    assert llm.profile_fields("old") == before
    assert "僅套用" in dialog.use_button.text()
    dialog.deleteLater()


def test_same_display_name_preserves_the_selected_model_id(picker, monkeypatch):
    from paper_daily import model_catalog

    widget, _app = picker

    def discover(cfg):
        rows = [{"value": model, "displayName": "Sonnet 5.5"}
                for model in ("sonnet", "claude-sonnet-exact")]
        model_catalog.remember(cfg, rows)
        return [row["value"] for row in rows]

    monkeypatch.setattr(ai_accounts, "models", discover)
    widget._inspect()
    widget.model.setCurrentIndex(widget.model.findData("claude-sonnet-exact"))
    widget._use()
    assert llm.settings().model == "claude-sonnet-exact"


def test_unconfirmed_login_does_not_show_cached_quota_or_query_models(picker, monkeypatch):
    widget, _app = picker
    monkeypatch.setattr(ai_accounts, "auth", lambda *a: (None, "not signed in"))
    monkeypatch.setattr(ai_accounts, "models", lambda *a: pytest.fail("must confirm login first"))
    widget._inspect()
    widget._cached_usage()
    assert "尚未確認登入" in widget.usage.quota_status.text()
    assert not widget.usage.scroll.isVisible()
    assert "not signed in" in widget.account_status.text()
