import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_research_plan import fake_plan
from test_ui_stress import settle
from test_workspace_transfer_ui import _sync_runner
from test_workspace_transfer_ui import workspace as _workspace

from paper_daily import research_plan as rp
from paper_daily import store
from paper_daily.desktop import ai_access
from paper_daily.desktop.import_dialog import ImportListDialog

workspace = _workspace


@pytest.fixture
def dialog(workspace, monkeypatch):
    monkeypatch.setattr(ai_access, "_bridge", None)
    fake_plan(monkeypatch)
    widget = ImportListDialog({}, workspace[1])
    widget.name.setText("My research route")
    widget.body.setPlainText("I want methods and critical evaluations, not a bibliography")
    widget.depth.setCurrentIndex(widget.depth.findData("quick"))
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()


def test_topic_is_default_and_requires_preview_confirmation(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    assert dialog.mode.currentData() == "topic"
    dialog._start()
    assert dialog.plan and not dialog.imported
    assert dialog.papers.topLevelItemCount() == 2
    assert "Full texts need review" in dialog.explanation.toPlainText()
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    dialog.papers.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    dialog.name.setText("Renamed before commit")
    dialog._start()
    assert dialog.imported
    with store.connect() as conn:
        assert conn.execute("SELECT name FROM lists").fetchone()[0] == "Renamed before commit"
        assert conn.execute("SELECT count(*) FROM list_papers").fetchone()[0] == 1
    assert "清單綜覽" in dialog.status.text()


def test_uncheck_all_leaves_preview_available_without_creating_list(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    dialog._start()
    for i in range(dialog.papers.topLevelItemCount()):
        dialog.papers.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)
    dialog._start()
    assert not dialog.imported and dialog.plan and "至少勾選" in dialog.status.text()


def test_review_opens_retrieved_source_not_a_model_supplied_url(dialog, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    _sync_runner(dialog, monkeypatch)
    dialog._start()
    dialog._open_source(dialog.papers.topLevelItem(0), 0)
    assert opened == ["https://www.semanticscholar.org/paper/p1"]


def test_ai_picker_is_scoped_to_list_creation(dialog, monkeypatch):
    from paper_daily.desktop import ai_picker

    opened = []

    class Picker:
        def __init__(self, parent, *, task):
            opened.append(task)

        def exec(self):
            return 0

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    dialog.ai_button.click()
    assert opened == ["list_parse"]


@pytest.mark.parametrize("change", ["body", "depth", "mode"])
def test_changing_research_input_invalidates_old_preview(dialog, monkeypatch, change):
    _sync_runner(dialog, monkeypatch)
    dialog._start()
    assert dialog.plan
    if change == "body":
        dialog.body.setPlainText("A different question")
    elif change == "depth":
        dialog.depth.setCurrentIndex(dialog.depth.findData("deep"))
    else:
        dialog.mode.setCurrentIndex(dialog.mode.findData("references"))
    assert dialog.plan is None and dialog.preview.isHidden()


def test_failed_search_keeps_inputs_and_can_retry(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    original = rp.propose
    monkeypatch.setattr(rp, "propose", lambda *a: (_ for _ in ()).throw(ValueError("unavailable")))
    dialog._start()
    assert "unavailable" in dialog.status.text() and dialog.go.isEnabled()
    assert dialog.body.toPlainText().startswith("I want")
    monkeypatch.setattr(rp, "propose", original)
    dialog._start()
    assert dialog.plan and not dialog.imported


def test_failed_commit_can_retry_same_preview_without_another_ai_call(dialog, monkeypatch):
    _sync_runner(dialog, monkeypatch)
    dialog._start()
    original = rp.commit
    monkeypatch.setattr(rp, "commit", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    dialog._start()
    assert dialog.plan and "disk" in dialog.status.text() and not dialog.imported
    monkeypatch.setattr(rp, "propose", lambda *a: pytest.fail("retry regenerated route"))
    monkeypatch.setattr(rp, "commit", original)
    dialog._start()
    assert dialog.imported


@pytest.mark.parametrize("cancel", [False, True])
def test_click_close_flood_during_preview_never_creates_a_list(dialog, monkeypatch, cancel):
    plan = rp.propose("Fixture research", "quick")
    entered, release = threading.Event(), threading.Event()
    calls = []

    def propose(*args):
        calls.append(args)
        entered.set()
        assert release.wait(4)
        return plan

    monkeypatch.setattr(rp, "propose", propose)
    try:
        dialog._start()
        assert entered.wait(2)
        for _ in range(25):
            dialog.go.click()
            dialog._start()
            dialog.close_btn.click()
            dialog.close()
        assert dialog.isVisible() and not dialog.body.isEnabled()
        assert dialog.bar.isVisible()
        if cancel:
            dialog.stop.click()
            assert "取消" in dialog.status.text()
        release.set()
        settle(dialog.runner)
        assert len(calls) == 1 and not dialog.imported
        assert bool(dialog.plan) is not cancel
        with store.connect() as conn:
            assert conn.execute("SELECT count(*) FROM lists").fetchone()[0] == 0
    finally:
        release.set()
        if dialog.runner._thread:
            dialog.runner._thread.quit()
            dialog.runner._thread.wait(4000)
        QTest.qWait(5)


def test_late_preview_is_not_applied_to_changed_request(dialog, monkeypatch):
    plan = rp.propose("Fixture research", "quick")
    callbacks = []
    monkeypatch.setattr(dialog.runner, "start", lambda prompt, done, failed, **kw:
                        callbacks.append(done))
    dialog._start()
    dialog.body.setPlainText("Changed programmatically while pending")
    import json

    callbacks[0](json.dumps(plan))
    assert dialog.plan is None and not dialog.imported
    assert "未套用舊結果" in dialog.status.text()
