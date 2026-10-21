import json
import os
import sqlite3
from uuid import uuid4

import pytest

from paper_daily import feedback, llm
from paper_daily.ai_types import Completion, Settings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


def test_opt_in_is_required_and_repeated_choice_preserves_identity(setup):
    feedback.record("ui.action", "list_overview")
    assert not feedback.path().exists()
    feedback.set_consent(True)
    first = feedback.consent()
    feedback.set_consent(True)
    assert feedback.consent() == first
    feedback.record("ui.action", "list_overview")
    assert len(feedback.local_snapshot()["events"]) == 1
    feedback.set_consent(False)
    feedback.record("ui.action", "list_overview")
    assert feedback.local_snapshot() == {"schema_version": 1, "consent": None, "events": []}
    feedback.set_consent(True)
    assert feedback.consent()["participant_id"] != first["participant_id"]


def test_events_are_small_closed_schema_without_inputs_or_identity(setup, monkeypatch):
    feedback.set_consent(True)

    class Provider:
        def complete(self, request, cfg, post):
            return Completion("private answer", model="custom-secret-model")

    monkeypatch.setitem(llm._PROVIDERS, "cli", Provider())
    with feedback.flow("dive") as outcome:
        llm.complete_result("private paper and email@example.org", task="dive", cfg=Settings(
            "cli", profile="private-profile", account_id="secret-id", api_key="secret-key"
        ))
        outcome["success"] = True
    data = feedback.local_snapshot()
    serialized = json.dumps(data)
    assert not any(word in serialized for word in (
        "private", "email@example.org", "secret", "prompt", "answer"
    ))
    events = data["events"]
    assert [row["event"] for row in events] == [
        "flow.started", "ai.started", "ai.completed", "flow.completed"
    ]
    assert len({row["trace_id"] for row in events}) == 1
    assert events[1]["parent_node_id"] == events[0]["node_id"]
    assert events[1]["node_id"] == events[2]["node_id"]
    assert events[2]["success"] is True and events[2]["model_family"] == "other"
    assert len(json.dumps(events[2])) < 650


def test_unknown_names_are_redacted_and_raw_text_properties_rejected(setup):
    feedback.set_consent(True)
    feedback.record("ui.action", "private-name", backend="private-provider", model="private-model")
    row = feedback.local_snapshot()["events"][0]
    assert (row["feature"], row["backend"], row["model_family"]) == ("other", "other", "other")
    with pytest.raises(TypeError):
        feedback.record("ui.action", "ask", prompt="secret")
    with pytest.raises(ValueError):
        feedback.record("secret", "ask")
    with pytest.raises(ValueError):
        feedback.record("ui.action", "ask", node_id="private text")


def test_failed_flow_restores_parent_and_retention_removes_old_events(setup):
    feedback.set_consent(True)
    with pytest.raises(RuntimeError), feedback.flow("slides"):
        raise RuntimeError("secret failure")
    assert feedback.FLOW.get() is None
    with sqlite3.connect(feedback.path()) as db:
        db.execute("INSERT INTO events(day,body) VALUES ('2000-01-01', '{}')")
    events = feedback.local_snapshot()["events"]
    assert len(events) == 2 and events[-1]["success"] is False


def test_feedback_dialog_cancel_export_failure_retry_and_withdrawal(setup, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from paper_daily.desktop.feedback_dialog import FeedbackDialog

    app = QApplication.instance() or QApplication([])
    widget = FeedbackDialog()
    assert not widget.enabled.isChecked()
    widget.enabled.setChecked(True)
    widget.reject()
    assert feedback.consent() is None  # Merely checking, then closing, does not save.
    widget.apply()
    feedback.record("ui.action", "list_overview", node_id=uuid4().hex)
    widget.reload()
    reviewed = widget.preview.toPlainText()
    feedback.record("ui.action", "ai_settings")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    widget.export_preview()
    assert not (setup / "out.json").exists()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(setup), ""))
    widget.export_preview()
    assert "失敗" in widget.status.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(setup / "out.json"), ""))
    widget.export_preview()
    assert (setup / "out.json").read_text(encoding="utf-8") == reviewed
    widget.enabled.setChecked(False)
    widget.apply()
    assert not widget.export.isEnabled() and feedback.local_snapshot()["events"] == []
    widget.deleteLater()
    app.processEvents()


def test_retention_caps_size_and_observation_failure_does_not_break_ai(setup, monkeypatch):
    feedback.set_consent(True)
    with sqlite3.connect(feedback.path()) as db:
        from datetime import UTC, datetime

        db.executemany("INSERT INTO events(day,body) VALUES (?,?)",
                       [(datetime.now(UTC).date().isoformat(), '{}')] * 10001)
    assert len(feedback.local_snapshot()["events"]) == 10000
    monkeypatch.setattr(feedback, "record", lambda *a, **k: (_ for _ in ()).throw(
        sqlite3.OperationalError("disk full")
    ))
    feedback.safe_record("ui.action", "ai_settings")


def test_background_worker_keeps_parent_flow_and_failed_result(setup):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.ask import AskWorker

    app = QApplication.instance() or QApplication([])
    feedback.set_consent(True)
    with feedback.flow("slides"):
        worker = AskWorker("private", call=lambda prompt: (None, "fixture failure"))
    import threading

    def call(prompt):
        feedback.record("ai.completed", "slides", success=False, node_id=uuid4().hex)
        return None, "fixture failure"

    worker._call = call
    thread = threading.Thread(target=worker.run)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    events = feedback.local_snapshot()["events"]
    assert events[-1]["parent_node_id"] == events[0]["node_id"]
    assert events[-1]["trace_id"] == events[0]["trace_id"]
    assert events[-1]["success"] is False
    worker.deleteLater()
    app.processEvents()
