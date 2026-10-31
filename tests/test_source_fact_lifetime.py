"""Owned workers drain through modeless GUI delivery; no late source/model retargeting."""

import json
import threading
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_claim_jobs import claims as claims_fixture
from test_claim_jobs import ready as ready_fixture
from test_claim_jobs import workspace as workspace_fixture
from test_highlight_generation import QUOTES
from test_research_view_reentry import reading_window as reading_fixture
from test_source_fact_dialog import open_child, wait
from test_source_fact_dialog import scene as scene_fixture
from test_source_fact_dialog import source as source_fixture

from paper_daily import llm
from paper_daily.ai_types import Completion, Settings
from paper_daily.desktop.research_audit import open_report

scene, source = scene_fixture, source_fixture
workspace, ready, claims, reading_window = (
    workspace_fixture,
    ready_fixture,
    claims_fixture,
    reading_fixture,
)


@pytest.mark.parametrize(
    "change", ["cancel", "close", "paper", "source", "config", "env", "refresh"]
)
def test_pending_work_never_replaces_prior_report_after_context_changes(scene, monkeypatch, change):
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    old, text = child.report, child.output.toPlainText()
    entered, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", held)
    try:
        assert child.generate() and not child.generate()
        wait(scene.app, entered.is_set)
        if change == "cancel":
            child.cancel()
        elif change == "close":
            assert not child.close() and not child.disposed
            assert child.report is old and child.output.toPlainText() == text
        elif change == "paper":
            scene.active[1] = "another-paper"
        elif change == "source":
            scene.source.path.write_bytes(b"changed actual source")
        elif change == "config":
            scene.config.write_text('{"selection":"different"}', encoding="utf-8")
        elif change == "env":
            monkeypatch.setenv("PAPERFACT_SYNTHETIC_A3_SCOPE", "changed")
        else:
            scene.audit.refresh()
            wait(scene.app, lambda: not scene.audit.busy)
        child._tick()
        release.set()
        wait(scene.app, lambda: not child.busy)
        if change == "close":
            assert child.disposed
            assert child.capture is None and child.report is None and child.accepted is None
            assert child.output.toPlainText() == text
        else:
            assert child.report is old and child.output.toPlainText() == text
        assert scene.counts["model"] == 2
        assert scene.question.text() == "Unsent question"
        assert scene.note.toPlainText() == "Unsent note"
    finally:
        release.set()


def test_future_model_change_preserves_accepted_source_and_provenance(scene, monkeypatch):
    jumps = []
    scene.audit.source_callback = lambda source: jumps.append(source) or True
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    old, text = child.report, child.output.toPlainText()
    monkeypatch.setattr(
        llm,
        "settings",
        lambda **kw: Settings(
            "openai", model="next-different", profile="Later account", requires_key=False
        ),
    )
    scene.config.write_text('{"next":"different"}', encoding="utf-8")
    wait(scene.app, lambda: not child.busy and "next-different" in child.route.text())
    assert child.report is old and child.output.toPlainText() == text
    assert "audit-request" in text and "next-different" not in text
    assert child.source_buttons and child.source_buttons[0].isEnabled()
    child.source_buttons[0].click()
    wait(scene.app, lambda: not child.busy)
    assert len(jumps) == 1 and jumps[0]["document_hash"] == scene.source.sha256
    assert scene.counts["model"] == 1


def test_parent_requests_both_existing_and_source_child_to_drain(scene, monkeypatch):
    child = open_child(scene)
    entered, release = threading.Event(), threading.Event()

    class ExistingBusyChild:
        disposed = False
        requested = 0

        def close(self):
            self.requested += 1
            return False

    existing = ExistingBusyChild()
    scene.audit._appraisal_dialog = existing

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", held)
    try:
        assert child.generate()
        wait(scene.app, entered.is_set)
        assert scene.audit.close() is False
        assert existing.requested == 1 and child._closing
        assert child._worker is not None and child.capture is not None
        release.set()
        wait(scene.app, lambda: child.disposed and not child.busy)
        assert child.report is None
    finally:
        existing.disposed = True
        release.set()


@pytest.fixture
def native(reading_window, monkeypatch, tmp_path):
    view = reading_window
    view.window.data.add_note("paper", QUOTES[0])
    config = tmp_path / "a3-native-ai.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(llm, "SETTINGS_PATH", config)
    monkeypatch.setattr(view.window.account_status, "check", lambda *a, **k: None)
    monkeypatch.setattr(llm, "capture_connections", lambda: ({}, {}, config.parent))
    monkeypatch.setattr(
        llm,
        "settings",
        lambda **kw: Settings(
            "openai", model="native-request", profile="Native fixture", requires_key=False
        ),
    )
    entered, release = threading.Event(), threading.Event()
    calls = []

    def complete(prompt, **kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(10)
        items = json.loads(prompt)["items"]
        item = next(i for i in items if i["id"] == "notes:1")
        span = next(s for s in item["spans"] if QUOTES[0] in s["text"])
        return Completion(
            json.dumps(
                dict(
                    study_type="unknown",
                    empty_reason=None,
                    facts=[
                        dict(
                            id="native",
                            category="method",
                            statement=QUOTES[0],
                            origin="author_stated",
                            scope={
                                k: None
                                for k in (
                                    "construct",
                                    "outcome",
                                    "comparator",
                                    "population",
                                    "time",
                                    "unit",
                                    "statistic",
                                    "conditions",
                                )
                            },
                            value=dict(kind="text", text=QUOTES[0]),
                            output=dict(item_id="notes:1", excerpt=QUOTES[0]),
                            evidence=[dict(item_id="notes:1", span_id=span["id"], quote=QUOTES[0])],
                        )
                    ],
                )
            ),
            model="native-reported",
        )

    monkeypatch.setattr(llm, "complete_result", complete)
    audit = open_report(view.reader)
    wait(view.app, lambda: not audit.busy and audit.report is not None)
    yield view, audit, entered, release, calls
    release.set()
    child = audit._source_fact_dialog
    if child is not None and child.busy:
        child.cancel()
        wait(view.app, lambda: not child.busy)
    if child is not None and not child.disposed:
        child.close()


def open_native(native):
    view, audit, entered, release, calls = native
    child = audit.open_source_facts()
    wait(view.app, lambda: not child.busy and child._proof is not None)
    return view, audit, child, entered, release, calls


def test_actual_modeless_main_typing_and_verified_native_source_focus(native, monkeypatch):
    view, audit, child, entered, release, calls = open_native(native)
    focus = view.reader.pdf.selection.focus
    focused = []

    def observed(anchor):
        result = focus(anchor)
        focused.append((anchor, result))
        return result

    monkeypatch.setattr(view.reader.pdf.selection, "focus", observed)
    assert child.generate()
    wait(view.app, entered.is_set)
    assert QApplication.activeModalWidget() is None
    assert audit.windowModality() == Qt.WindowModality.NonModal
    assert child.windowModality() == Qt.WindowModality.NonModal
    view.window.activateWindow()
    for widget, text in (
        (view.reader.ask_box, "Question while comparing"),
        (view.reader.note_edit, "Note while comparing"),
    ):
        assert widget.isEnabled()
        widget.setFocus()
        QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(widget, text)
    assert child.busy and view.window.activity_hub.busy
    release.set()
    wait(view.app, lambda: not child.busy)
    assert child.report is not None and len(calls) == 1
    assert view.reader.ask_box.text() == "Question while comparing"
    assert view.reader.note_edit.toPlainText() == "Note while comparing"
    child.source_buttons[0].click()
    wait(view.app, lambda: not child.busy)
    assert len(focused) == 1 and focused[0][1]
    assert view.reader.pdf.selection.anchor() == focused[0][0]
    assert view.reader.ask_box.text() == "Question while comparing"
    assert view.reader.note_edit.toPlainText() == "Note while comparing"


@pytest.mark.parametrize("operation", ["close", "update", "restart"])
def test_actual_main_retains_worker_and_capture_until_delivery_drain(
    native, monkeypatch, operation
):
    view, audit, child, entered, release, calls = open_native(native)
    assert child.generate()
    wait(view.app, entered.is_set)
    worker, capture = child._worker, child.capture
    native_wait, joined = worker.wait, []

    def observed_wait(*args):
        result = native_wait(*args)
        if result:
            joined.append(True)
        return result

    monkeypatch.setattr(worker, "wait", observed_wait)
    action = {
        "close": view.window.close,
        "update": view.window._prepare_update,
        "restart": view.window._prepare_restart,
    }[operation]
    assert action() is False
    assert child._worker is worker and child.capture is capture and worker.isRunning()
    assert view.window.isVisible() and view.window.activity_hub.busy
    child.cancel()
    release.set()
    wait(view.app, lambda: not child.busy)
    assert joined == [True] and len(calls) == 1
    assert child.report is None
    assert not view.window.activity_hub.busy and child._worker is None


@pytest.mark.parametrize("held", [False, True], ids=["accepted-idle", "held-close-drain"])
def test_accepted_parent_close_releases_actual_sealed_capture_with_closed_ui_retained(
    scene, monkeypatch, held
):
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    assert child.report is not None
    assert child.capture.snapshot._bytes == scene.source.path.read_bytes()
    capture = weakref.ref(child.capture)
    report_id = id(child.report)
    assert child.report.sheet._capture is capture()
    entered, release, joined = threading.Event(), threading.Event(), []

    def complete(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    try:
        if held:
            monkeypatch.setattr(llm, "complete_result", complete)
            assert child.generate()
            wait(scene.app, entered.is_set)
            worker_type, worker_id = type(child._worker), id(child._worker)
            native_wait = worker_type.wait

            def observe_wait(worker, *args):
                result = native_wait(worker, *args)
                if id(worker) == worker_id and result:
                    joined.append(True)
                return result

            monkeypatch.setattr(worker_type, "wait", observe_wait)
            assert scene.audit.close() is False
            assert not child.disposed and not scene.audit.disposed
            assert capture() is child.capture
            assert capture().snapshot._bytes == scene.source.path.read_bytes()
            assert id(child.report) == report_id and child.accepted is not None
            assert child._worker.isRunning() and not joined
            release.set()
            wait(scene.app, lambda: child.disposed and scene.audit.disposed and not child.busy)
            assert joined == [True]
        else:
            assert scene.audit.close()
        # Only the deliberately retained closed UI objects own this capture;
        # the fixture has a ResolvedDocument, not an AuditCapture/EvidenceSnapshot.
        assert scene.audit._source_fact_dialog is child
        assert scene.audit.captured is None and scene.audit.disposed and child.disposed
        assert not child.isVisible() and not scene.audit.isVisible()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        scene.app.processEvents()
        assert child.capture is None and child.report is None and child.accepted is None
        assert capture() is None
        assert not child.poll.isActive()
        child._tick()
        child._finished()
        assert not child._probe()
        assert not child.generate() and not child.settings()
        assert not child.open_source({})
    finally:
        release.set()


def test_stop_keeps_accepted_capture_and_report_while_view_remains_open(scene, monkeypatch):
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    capture, report, accepted = child.capture, child.report, child.accepted
    text = child.output.toPlainText()
    entered, release = threading.Event(), threading.Event()

    def complete(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", complete)
    try:
        assert child.generate()
        wait(scene.app, entered.is_set)
        child.cancel()
        release.set()
        wait(scene.app, lambda: not child.busy)
        assert not child.disposed and child.isVisible()
        assert child.capture is capture and child.report is report and child.accepted is accepted
        assert child.output.toPlainText() == text and scene.counts["model"] == 2
    finally:
        release.set()
