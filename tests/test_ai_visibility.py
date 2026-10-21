import os

import pytest
from PySide6.QtWidgets import QApplication

from paper_daily import ai_choices, llm
from paper_daily.desktop import fonts
from paper_daily.desktop.ai_dialog import AIStatusButton

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    fonts.load()  # Match app startup before asserting bounded toolbar text.
    for key in list(os.environ):
        if key.startswith(("PAPERFACT_", "PAPER_DAILY_")):
            monkeypatch.delenv(key)
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_choices, "_account_labels", {})
    llm.save_settings(profile="mine", backend="cli", model="sonnet", isolated=True)
    llm.save_settings(profile="other", backend="codex", model="research", isolated=True)
    ai_choices.remember_identity(llm.settings(profile="mine"), "me@example.org")
    return app


def test_global_status_is_compact_with_full_account_details_in_tooltip(settings):
    # User-requested replacement of the long profile dropdown with a settings button.
    widget = AIStatusButton()
    assert widget.text() == "全域 AI：Claude · Sonnet"
    assert widget.menu() is None
    assert "me@example.org" not in widget.text()
    assert "Claude · me@example.org · Sonnet" in widget.toolTip()
    widget.deleteLater()


def test_task_effective_accounts_are_visible_after_switching_global(settings):
    llm.use_profile("mine", task="slides")
    widget = AIStatusButton()
    llm.use_profile("other", desktop=True)
    widget.refresh()
    assert "Codex" in widget.text() and "research" in widget.text()
    assert "另有 1 個功能指定其他 AI" in widget.toolTip()
    assert "進階設定" in widget.toolTip() and len(widget.toolTip().splitlines()) == 3
    assert llm.settings(task="slides").backend == "cli"
    assert llm.settings(task="ask").backend == "codex"
    widget.deleteLater()


def test_long_model_does_not_expand_header_or_lose_full_details(settings):
    model = "future-model-" + "long-version-" * 20
    llm.save_settings(profile="mine", model=model)
    widget = AIStatusButton()
    assert widget.sizeHint().width() <= 280
    assert len(widget.text()) < len(model)
    assert model in widget.toolTip()
    widget.deleteLater()


def test_unfixed_models_and_unchecked_accounts_are_explicit(settings):
    cfg = llm.settings(profile="other")
    llm.save_settings(profile="other", model="")
    label = ai_choices.connection_label(llm.settings(profile="other"))
    assert "待確認" in label and "使用 Codex 預設模型" in label
    ai_choices.remember_identity(cfg, "尚未登入 Codex")
    assert "尚未登入" in ai_choices.connection_label(cfg)


def test_background_identity_result_stays_with_its_original_account(settings, monkeypatch):
    import threading

    from PySide6.QtWidgets import QWidget

    from paper_daily import ai_accounts
    from paper_daily.desktop.account_status import AccountStatus

    release, finished = threading.Event(), threading.Event()
    chosen = llm.settings(profile="mine")

    def auth(cfg, action):
        assert cfg == chosen and action == "status"
        release.wait(2)
        finished.set()
        return "original@example.org", "ok"

    monkeypatch.setattr(ai_accounts, "auth", auth)
    owner = QWidget()
    changed = []
    monitor = AccountStatus(owner, lambda: changed.append(True))
    monitor.check([chosen])
    llm.use_profile("other", desktop=True)
    release.set()
    assert finished.wait(2)
    for _ in range(100):
        from PySide6.QtTest import QTest

        QTest.qWait(5)
        if changed:
            break
    assert changed and "original@example.org" in ai_choices.account_label(chosen)
    assert "original@example.org" not in ai_choices.account_label(llm.settings())
    owner.deleteLater()
