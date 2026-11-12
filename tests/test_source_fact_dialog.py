"""Explicit temporary source-fact comparisons stay on one captured Audit call."""

import copy
import json
import sqlite3
import sys
import time
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QPushButton, QWidget
from test_audit_fact_extraction import response
from test_research_evidence import proposal
from test_research_evidence import source as source_fixture

from paper_daily import llm, manual_highlight_ops, research_evidence
from paper_daily.ai_types import Completion, Settings
from paper_daily.desktop.research_audit import AuditDialog

source = source_fixture


def wait(app, condition, seconds=20):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)
    # Check at once: one more event pass may start follow-up work, such as the
    # dialog re-reading a changed AI route, and hide that the awaited state came.
    assert condition(), "Isolated source-fact UI did not settle"


@pytest.fixture
def scene(source, monkeypatch, tmp_path):
    database = source._owner.db_path
    with closing(sqlite3.connect(database)) as conn, conn:
        for body in ("50 participants", "60 participants"):
            conn.execute(
                "INSERT INTO notes(paper_id,body,kind,created_at) "
                "VALUES('paper',?,'note','fixture')",
                (body,),
            )
    app = QApplication.instance() or QApplication([])
    config = tmp_path / "fixture-ai.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(llm, "SETTINGS_PATH", config)
    cfg = Settings("openai", model="audit-request", profile="Fixture Audit", requires_key=False)
    counts = dict(capture=0, model=0)

    def capture():
        assert QThread.currentThread() != app.thread()
        counts["capture"] += 1
        return {}, {}, config.parent

    def settings(**kwargs):
        assert QThread.currentThread() != app.thread()
        assert kwargs.get("task") == "audit"
        return cfg

    def complete(prompt, **kwargs):
        assert QThread.currentThread() != app.thread()
        assert kwargs["task"] == "audit" and kwargs["max_tokens"] == 4000
        counts["model"] += 1
        return Completion(json.dumps(response(prompt)), model="audit-reported")

    monkeypatch.setattr(llm, "capture_connections", capture)
    monkeypatch.setattr(llm, "settings", settings)
    monkeypatch.setattr(llm, "complete_result", complete)
    parent = QWidget()
    question = QLineEdit("Unsent question", parent)
    note = QPlainTextEdit("Unsent note", parent)
    active = [database, "paper", source]
    audit = AuditDialog(
        database,
        "paper",
        document=source,
        owner=manual_highlight_ops.capture_owner(database, "paper"),
        current_view=lambda: tuple(active),
        language="en",
        parent=parent,
    )
    audit.show()
    wait(app, lambda: not audit.busy and audit.report is not None)
    value = SimpleNamespace(
        app=app,
        audit=audit,
        parent=parent,
        question=question,
        note=note,
        source=source,
        config=config,
        cfg=cfg,
        counts=counts,
        active=active,
        complete=complete,
    )
    yield value
    child = getattr(audit, "_source_fact_dialog", None)
    if child is not None and not child.disposed:
        child.close()
        wait(app, lambda: child.disposed and not child.busy)
    if audit.busy:
        audit.cancel()
        wait(app, lambda: not audit.busy)
    audit.close()
    parent.close()
    audit.deleteLater()
    parent.deleteLater()
    app.processEvents()


def open_child(scene):
    button = scene.audit.findChild(QPushButton, "compareStatements")
    assert button is not None and button.isVisible() and button.isEnabled()
    button.click()
    child = scene.audit._source_fact_dialog
    wait(scene.app, lambda: not child.busy and child._proof is not None)
    return child


def test_existing_audit_has_one_free_reused_comparison_child(scene):
    child = open_child(scene)
    scene.audit.findChild(QPushButton, "compareStatements").click()
    assert scene.audit._source_fact_dialog is child
    assert scene.counts["model"] == 0 and child.report is None
    assert "audit-request" in child.route.text() and "4000" in child.budget.text()
    assert scene.question.text() == "Unsent question" and scene.note.toPlainText() == "Unsent note"


def test_explicit_generate_runs_once_and_shows_temporary_source_bound_output(scene):
    child = open_child(scene)
    assert child.generate() and not child.generate()
    wait(scene.app, lambda: not child.busy)
    assert scene.counts["model"] == 1 and child.report is not None
    text = child.output.toPlainText()
    assert "50 participants" in text and "audit-request" in text and "audit-reported" in text
    assert "Temporary" in text and "semantic" in text.lower()
    assert scene.source.sha256 in text
    assert scene.question.text() == "Unsent question" and scene.note.toPlainText() == "Unsent note"


@pytest.mark.parametrize("mode", ["empty", "malformed", "failure"])
def test_empty_is_honest_and_failed_retry_preserves_prior_temporary_report(
    scene, monkeypatch, mode
):
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    old, text = child.report, child.output.toPlainText()

    def result(*args, **kwargs):
        scene.counts["model"] += 1
        if mode == "failure":
            raise OSError("private provider detail")
        return Completion(
            json.dumps(
                {
                    "study_type": "unknown",
                    "facts": [],
                    "empty_reason": "No usable fact in selected material.",
                }
            )
            if mode == "empty"
            else "malformed",
            model=None,
        )

    monkeypatch.setattr(llm, "complete_result", result)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    if mode == "empty":
        assert child.report is not old
        assert "No usable fact" in child.output.toPlainText()
        assert "Not reported" in child.output.toPlainText()
    else:
        assert child.report is old and child.output.toPlainText() == text
        assert "private" not in child.status.text()
        monkeypatch.setattr(llm, "complete_result", scene.complete)
        assert child.generate()
        wait(scene.app, lambda: not child.busy)
        assert child.report is not old
    assert scene.counts["model"] == (2 if mode == "empty" else 3)


def test_empty_selection_and_unsupported_budget_cannot_start_a_model(scene, monkeypatch):
    child = open_child(scene)
    for check in child.checks.values():
        check.setChecked(False)
    assert not child.generate_button.isEnabled() and not child.generate()
    assert scene.counts["model"] == 0
    monkeypatch.setattr(llm, "settings", lambda **kw: Settings("openai", max_tokens=100))
    scene.config.write_text('{"budget":100}', encoding="utf-8")
    wait(scene.app, lambda: not child.busy and not child._supported)
    assert not any(check.isChecked() for check in child.checks.values())
    assert not child.generate_button.isEnabled() and not child.generate()
    assert "budget" in child.status.text() and scene.counts["model"] == 0


@pytest.mark.parametrize("language", ["en", "zh-TW"])
def test_compact_bilingual_dialog_is_modeless_and_controls_wrap(scene, language):
    from PySide6.QtCore import Qt

    from paper_daily.desktop.source_fact_dialog import TEXT, SourceFactDialog

    child = SourceFactDialog(
        scene.audit.captured,
        owner=scene.audit.owner,
        current_view=lambda: tuple(scene.active),
        language=language,
        parent=scene.audit,
    )
    child.show()
    try:
        wait(scene.app, lambda: not child.busy and child._proof is not None)
        child.resize(480, 700)
        scene.app.processEvents()
        assert child.windowModality() == Qt.WindowModality.NonModal
        assert QApplication.activeModalWidget() is None
        assert child.generate_button.text() == TEXT[language]["generate"]
        assert child.route.wordWrap() and child.budget.wordWrap()
        assert child.route.height() >= child.route.heightForWidth(child.route.width())
        assert scene.counts["model"] == 0
    finally:
        child.close()
        child.deleteLater()
        scene.app.processEvents()


@pytest.mark.parametrize("case", ["numeric", "rounding", "derived", "unknown"])
def test_both_saved_output_locations_and_comparison_limits_are_visible(scene, monkeypatch, case):
    found = research_evidence.verify(scene.source, proposal(scene.source, page=2))
    anchor = {
        **found["claims"][0]["passages"][0]["location"]["anchor"],
        "document_hash": scene.source.sha256,
    }
    with closing(sqlite3.connect(scene.source._owner.db_path)) as conn, conn:
        conn.execute("UPDATE notes SET page=2,anchor=?", (json.dumps(anchor),))
    scene.audit.refresh()
    wait(scene.app, lambda: not scene.audit.busy)

    def complete(prompt, **kwargs):
        scene.counts["model"] += 1
        body = response(prompt)
        second = copy.deepcopy(body["facts"][0])
        second.update(
            id="second",
            statement="60 participants",
            output=dict(item_id="notes:2", excerpt="60 participants"),
        )
        second["value"]["decimal"] = "60"
        item = next(i for i in json.loads(prompt)["items"] if i["id"] == "notes:2")
        span = next(s for s in item["spans"] if "50 participants" in s["text"])
        second["evidence"][0].update(item_id="notes:2", span_id=span["id"])
        if case == "rounding":
            second["value"]["rounded_places"] = 0
        elif case == "derived":
            second["value"]["derived"] = True
        elif case == "unknown":
            second.update(origin="unknown", value=None)
        body["facts"].append(second)
        return Completion(json.dumps(body), model="recorded-model")

    monkeypatch.setattr(llm, "complete_result", complete)
    child = open_child(scene)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    text = child.output.toPlainText()
    assert "notes:1" in text and "notes:2" in text
    assert "50 participants" in text and "60 participants" in text and "0–15" in text
    expected = {
        "numeric": "Proposed numeric values differ",
        "rounding": "rounding intervals",
        "derived": "Derived value",
        "unknown": "Not comparable",
    }[case]
    assert expected in text and "not scientific" in child.t["intro"]
    assert scene.counts["model"] == 1


@pytest.mark.parametrize("outcome", ["cancel", "error", "change"])
def test_existing_task_picker_is_single_flight_and_safe_on_cancel_error(
    scene, monkeypatch, outcome
):
    from paper_daily.desktop import ai_picker

    child = open_child(scene)
    opened, errors = [], []

    class Picker:
        def __init__(self, parent, *, task):
            opened.append(task)

        def exec(self):
            child.settings_button.click()
            if outcome == "error":
                raise OSError("private settings error")
            if outcome == "change":
                scene.config.write_text('{"selection":"new"}', encoding="utf-8")

        def deleteLater(self):
            pass

    monkeypatch.setattr(ai_picker, "AIPickerDialog", Picker)
    monkeypatch.setattr(sys, "excepthook", lambda _kind, error, _traceback: errors.append(error))
    child.settings_button.click()
    wait(scene.app, lambda: not child.busy)
    assert errors == [] and opened == ["audit"] and not child._settings_open
    assert scene.counts["model"] == 0
    assert scene.question.text() == "Unsent question" and scene.note.toPlainText() == "Unsent note"


def test_no_ai_route_disables_generate_and_guides_local_configuration_without_calls(
    scene, monkeypatch
):
    def settings(**kwargs):
        assert QThread.currentThread() != scene.app.thread()
        assert kwargs.get("task") == "audit"
        return Settings("none")

    monkeypatch.setattr(llm, "settings", settings)
    child = open_child(scene)
    assert scene.counts["model"] == 0 and not child.busy
    assert not child.generate_button.isEnabled() and not child._supported
    assert child.settings_button.isEnabled()
    assert child.status.text() == (
        "Choose an Audit account, model and supported output budget before generating."
    )
    child.generate_button.click()
    child.generate_button.click()
    assert not child.generate() and not child.busy and scene.counts["model"] == 0
    assert scene.question.text() == "Unsent question" and scene.note.toPlainText() == "Unsent note"
