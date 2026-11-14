"""Actual Qt Lineage actions preserve research, drafts and running-worker lifetimes."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidgetItem
from test_lineage_jobs import routes
from test_research_lineage import corpus as corpus
from test_research_lineage import proposals

from paper_daily import lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.ai_types import Completion
from paper_daily.desktop.lineage_dialog import TEXT, LineageDialog
from paper_daily.manual_highlight_ops import observe_owner


def until(app, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def scene(corpus, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from paper_daily.desktop import fonts
    from paper_daily.desktop.main import style

    fonts.load()
    style(app)
    selected = routes()
    monkeypatch.setattr(llm, "available", lambda **_k: True)
    monkeypatch.setattr(llm, "freeze_connections", lambda _tasks: selected)
    monkeypatch.setattr(llm, "capture_configured_connections", lambda: selected)
    monkeypatch.setattr(llm, "settings", lambda task=None, **_k: selected.settings(task))
    owner = observe_owner(corpus[0], "focal", expected_native=generation._identity(corpus[0]))
    view = ["original-view"]
    dialog = LineageDialog(
        corpus[0],
        "focal",
        owner=owner,
        document=None,
        legacy_root=corpus[1],
        current_view=lambda: view[0],
        language="en",
    )
    dialog.show()
    until(app, lambda: not dialog.busy and dialog.peers.count() == 3)
    yield app, dialog, view
    if dialog.busy:
        dialog.cancel()
        until(app, lambda: not dialog.busy)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def select_peers(dialog):
    for index in range(dialog.peers.count()):
        dialog.peers.item(index).setSelected(True)


def test_open_and_refresh_are_saved_only_and_chinese_labels_survive_utf8(
    scene, corpus, monkeypatch
):
    app, dialog, _view = scene
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    assert TEXT["zh-TW"]["title"] == "\u7814\u7a76\u8108\u7d61"
    assert dialog.status.text() == dialog.t["empty"]
    assert dialog.refresh()
    assert not dialog.refresh()
    until(app, lambda: not dialog.busy)
    assert lineage_sets.saved(corpus[0], "focal") == []
    assert dialog.status.text() == dialog.t["empty"]


def test_actual_generation_saves_renders_and_repeated_click_does_not_duplicate(
    scene, corpus, monkeypatch
):
    app, dialog, _view = scene
    select_peers(dialog)
    calls = []

    def complete(*_a, **_k):
        calls.append(True)
        return Completion(json.dumps(proposals(corpus[2])), model="actual-returned")

    monkeypatch.setattr(llm, "complete_result", complete)
    assert dialog.generate()
    assert not dialog.generate() and not dialog.generate_button.isEnabled()
    until(app, lambda: not dialog.busy)
    saved = lineage_sets.saved(corpus[0], "focal")
    assert len(saved) == 1 and len(calls) == 1
    assert dialog.saved == saved and dialog.results.count() == 1
    assert dialog.status.text() == dialog.t["saved_local"]
    assert any("actual-returned" in label.text() for label in dialog.cards.findChildren(QLabel))
    assert dialog.generate_button.isEnabled()
    assert dialog.source_buttons
    dialog.source_buttons[0].click()
    until(app, lambda: not dialog.busy)
    viewer = dialog._original_viewer
    assert viewer is not None and not viewer.disposed
    assert viewer.document.pageCount() >= 1
    row, source_id, _page = dialog._source_expected
    body = lineage_sets.decode(row["body_json"])
    expected = next(
        source["document_hash"] for source in body["report"]["sources"] if source["id"] == source_id
    )
    assert hashlib.sha256(bytes(viewer.buffer.data())).hexdigest() == expected
    assert dialog.document is None  # Separate original inspection never replaces the main reader.
    viewer.close()
    assert viewer.disposed and viewer.buffer.size() == 0
    from shiboken6 import isValid

    until(app, lambda: not isValid(viewer))
    image = Path(__file__).resolve().parents[1] / "build" / "lineage-desktop-20261113.png"
    assert dialog.grab().save(str(image))
    monkeypatch.setattr(
        "paper_daily.desktop.lineage_dialog.QMessageBox.question",
        lambda *_a, **_k: (
            __import__(
                "PySide6.QtWidgets", fromlist=["QMessageBox"]
            ).QMessageBox.StandardButton.Cancel
        ),
    )
    assert not dialog.generate()
    assert lineage_sets.saved(corpus[0], "focal") == saved and len(calls) == 1


@pytest.mark.parametrize("change", ["view", "close"])
def test_late_result_cannot_fill_changed_view_or_destroy_running_worker(
    scene, corpus, monkeypatch, change
):
    app, dialog, view = scene
    select_peers(dialog)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def complete(*_a, **_k):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        return Completion(json.dumps(proposals(corpus[2])))

    monkeypatch.setattr(llm, "complete_result", complete)
    assert dialog.generate()
    until(app, entered.is_set)
    try:
        if change == "view":
            view[0] = "another-paper"
            assert not dialog._check()
        else:
            assert not dialog.close()
            assert dialog.busy and not dialog.disposed
    finally:
        release.set()
    until(app, lambda: not dialog.busy)
    if change == "close":
        until(app, lambda: dialog.disposed)
    else:
        assert dialog.status.text() == dialog.t["changed"]
        assert not dialog.generate_button.isEnabled()
    assert lineage_sets.saved(corpus[0], "focal") == [] and len(calls) == 1


def test_failed_model_keeps_saved_content_and_requires_explicit_retry(scene, corpus, monkeypatch):
    app, dialog, _view = scene
    select_peers(dialog)
    calls = []

    def failed(*_a, **_k):
        calls.append(True)
        raise RuntimeError("synthetic provider failure")

    monkeypatch.setattr(llm, "complete_result", failed)
    assert dialog.generate()
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["failed"]
    assert lineage_sets.saved(corpus[0], "focal") == [] and len(calls) == 1
    assert dialog.generate_button.isEnabled()
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: Completion(json.dumps(proposals(corpus[2])))
    )
    assert dialog.generate()
    until(app, lambda: not dialog.busy)
    assert len(lineage_sets.saved(corpus[0], "focal")) == 1


def test_four_related_papers_are_refused_before_model_or_storage(scene, corpus, monkeypatch):
    _app, dialog, _view = scene
    select_peers(dialog)
    extra = QListWidgetItem("Fourth related paper", dialog.peers)
    extra.setData(Qt.ItemDataRole.UserRole, "fourth")
    extra.setSelected(True)
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    assert not dialog.generate()
    assert dialog.status.text() == dialog.t["limit"]
    assert lineage_sets.saved(corpus[0], "focal") == []


def test_missing_login_requests_task_scoped_sign_in_without_generation(scene, corpus, monkeypatch):
    _app, dialog, _view = scene
    from paper_daily.desktop import ai_access

    seen = []
    monkeypatch.setattr(llm, "available", lambda **_k: False)
    monkeypatch.setattr(ai_access, "login", lambda parent, task, reason: seen.append(task))
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    assert not dialog.generate()
    assert seen == ["lineage"]
    assert lineage_sets.saved(corpus[0], "focal") == []


def test_search_keeps_already_selected_related_papers_visible_and_selected(scene):
    app, dialog, _view = scene
    first = dialog.peers.item(0)
    first.setSelected(True)
    identity = first.data(Qt.ItemDataRole.UserRole)
    dialog.search.setText("Prior")
    assert dialog.refresh()
    until(app, lambda: not dialog.busy)
    assert {item.data(Qt.ItemDataRole.UserRole) for item in dialog.peers.selectedItems()} == {
        identity
    }
    assert any(dialog.peers.item(i).text() == "Prior Study" for i in range(dialog.peers.count()))


def test_actual_research_menu_reuses_window_and_preserves_question_draft(
    scene, corpus, monkeypatch
):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QLineEdit, QWidget

    from paper_daily import config, store
    from paper_daily.desktop import research_tasks
    from paper_daily.desktop.lineage_dialog import open_report

    app, original, _view = scene
    reader = QWidget()
    reader.paper = SimpleNamespace(id="focal")
    reader._qa_epoch = 1
    reader._active_document = None
    reader._highlight_owner = original.owner
    reader.ask_box = QLineEdit("My unsent research question", reader)
    reader.ask_status = QLabel(reader)
    monkeypatch.setattr(store, "DB_PATH", corpus[0])
    monkeypatch.setattr(config, "PDF_DIR", corpus[1])
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    picker = research_tasks.button(reader)
    action = next(a for a in picker.menu().actions() if a.data() == "grounded_lineage")
    action.trigger()
    dialog = reader._lineage_dialog
    try:
        until(app, lambda: not dialog.busy)
        assert open_report(reader) is dialog
        assert dialog.paper_id == "focal" and dialog.saved == []
        assert reader.ask_box.text() == "My unsent research question"
        assert lineage_sets.saved(corpus[0], "focal") == []
    finally:
        if dialog.busy:
            dialog.cancel()
            until(app, lambda: not dialog.busy)
        dialog.close()
        reader.close()
        reader.deleteLater()
        app.processEvents()


def test_changed_account_after_completion_retains_proposal_without_installing(
    scene, corpus, monkeypatch
):
    from paper_daily.ai_types import Settings

    app, dialog, _view = scene
    select_peers(dialog)
    configured = [routes().settings("lineage")]
    monkeypatch.setattr(llm, "settings", lambda task=None, **_k: configured[0])
    calls = []

    def complete(*_a, **_k):
        calls.append(True)
        configured[0] = Settings("openai", model="different-account-model", profile="other")
        return Completion(json.dumps(proposals(corpus[2])))

    monkeypatch.setattr(llm, "complete_result", complete)
    assert dialog.generate()
    until(app, lambda: not dialog.busy)
    assert dialog.status.text() == dialog.t["retained"]
    assert len(calls) == 1 and lineage_sets.saved(corpus[0], "focal") == []
    assert dialog.workflow._job._state.candidate is not None


def test_open_original_closes_after_exact_saved_row_changes(scene, corpus, monkeypatch):
    app, dialog, _view = scene
    select_peers(dialog)
    monkeypatch.setattr(
        llm, "complete_result", lambda *_a, **_k: Completion(json.dumps(proposals(corpus[2])))
    )
    assert dialog.generate()
    until(app, lambda: not dialog.busy)
    dialog.source_buttons[0].click()
    until(app, lambda: not dialog.busy)
    viewer = dialog._original_viewer
    assert viewer is not None and not viewer.disposed
    with generation._connect(corpus[0]) as conn:
        conn.execute("UPDATE paper_lineage_sets SET written_at='2026-11-20T00:00:00+00:00'")
        conn.commit()
    until(app, lambda: viewer.disposed)
    assert dialog.document is None


@pytest.mark.parametrize("change", ["paper", "workspace"])
def test_dialog_refuses_owner_from_another_visible_context_before_ai(
    scene, corpus, monkeypatch, change
):
    from dataclasses import replace

    _app, dialog, _view = scene
    owner = (
        replace(dialog.owner, paper_id="prior")
        if change == "paper"
        else replace(dialog.owner, database=corpus[0].parent / "another-workspace.sqlite")
    )
    monkeypatch.setattr(llm, "complete_result", lambda *_a, **_k: pytest.fail("No model call"))
    with pytest.raises(ValueError, match="another paper/workspace"):
        LineageDialog(
            corpus[0],
            "focal",
            owner=owner,
            document=None,
            legacy_root=corpus[1],
            current_view=lambda: "original",
        )
    assert lineage_sets.saved(corpus[0], "focal") == []
