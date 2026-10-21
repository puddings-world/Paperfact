import json
from dataclasses import replace
from pathlib import Path

from paper_daily import ai_choices, model_catalog
from paper_daily.ai_types import Settings


def test_public_names_and_default_are_read_from_official_metadata():
    rows = json.loads((Path(__file__).parent / "fixtures/claude_models_2_1_304.json").read_text(
        encoding="utf-8"
    ))["models"]
    cfg = Settings("cli", account_id="first")
    model_catalog.remember(cfg, rows)
    assert ai_choices.model_label(cfg) == "Claude 預設：Opus 5.5"
    assert ai_choices.model_label(replace(cfg, model="fable")) == "Fable 5.1"
    assert ai_choices.model_label(replace(cfg, model="claude-fable-5")) == "Fable 5"
    assert cfg.model is None


def test_names_are_scoped_to_provider_account_and_home():
    cfg = Settings("cli", account_id="first", cli_home="a")
    model_catalog.remember(cfg, [{"value": "fable", "displayName": "Fable 5.1"}])
    for other in (replace(cfg, account_id="second"), replace(cfg, backend="codex"),
                  replace(cfg, cli_home="b")):
        assert model_catalog.name(other, "fable") is None
    model_catalog.remember(replace(cfg, account_id="second"), [
        {"value": "fable", "displayName": "Different version"}
    ])
    assert model_catalog.name(cfg, "fable") == "Fable 5.1"


def test_missing_or_ambiguous_metadata_does_not_invent_versions():
    cfg = Settings("cli")
    model_catalog.remember(cfg, [None, {}, {"value": "fable", "displayName": 12},
                                {"value": "default", "description": "Unverified 9.9"}])
    assert ai_choices.model_label(cfg) == "使用 Claude 預設模型"
    assert ai_choices.model_label(replace(cfg, model="fable")) == "Fable"
    assert ai_choices.model_label(replace(cfg, model="custom-model")) == "custom-model"


def test_cached_model_ids_exclude_default_and_do_not_cross_accounts():
    cfg = Settings("cli", account_id="first")
    model_catalog.remember(cfg, [
        {"value": "default", "displayName": "Default"},
        {"value": "fable", "displayName": "Fable 5.1"},
    ])
    assert model_catalog.models(cfg) == ["fable"]
    assert model_catalog.models(replace(cfg, account_id="second")) == []


def test_background_catalog_refresh_updates_global_status_without_switching(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication, QWidget

    from paper_daily import llm, usage_cache
    from paper_daily.desktop import fonts
    from paper_daily.desktop.ai_dialog import AIStatusButton
    from paper_daily.desktop.usage_monitor import UsageMonitor

    app = QApplication.instance() or QApplication([])
    fonts.load()  # Production loads bundled fonts before constructing the toolbar.
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    llm.save_settings(profile="fixture", backend="cli", model="fable", isolated=True)
    monkeypatch.setattr(usage_cache.cache, "refresh_background", lambda cfg: None)
    owner = QWidget()
    owner.ai_picker = AIStatusButton(owner)
    monitor = UsageMonitor(owner)
    monitor.tick()
    before = llm.SETTINGS_PATH.read_bytes()
    model_catalog.remember(llm.settings(), [{"value": "fable", "displayName": "Fable 5.1"}])
    monitor.tick()
    assert "Fable 5.1" in owner.ai_picker.text()
    assert llm.SETTINGS_PATH.read_bytes() == before
    owner.deleteLater()
    app.processEvents()
