import json

import pytest

from paper_daily import feedback, feedback_report, llm


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "llm.json")
    return tmp_path


def test_report_counts_outcomes_models_sizes_and_nested_workflow_without_identifiers(workspace):
    feedback.set_consent(True)
    with feedback.flow("dive") as outcome:
        feedback.record("ai.started", "dive", backend="cli", model="fable", input_chars=2000)
        feedback.record("ai.completed", "dive", success=False, elapsed_ms=12000)
        outcome["success"] = False
    feedback.record("ui.action", "ai_settings")
    result = feedback.export_payload()
    assert result["schema_version"] == 2
    assert result["feature_usage"] == [{"feature": "ai_settings", "count": 1}]
    assert result["model_usage"] == [{"provider": "cli", "model_family": "fable", "count": 1}]
    assert result["input_sizes"] == [{"feature": "dive", "size_bucket": "medium", "count": 1}]
    assert result["workflow_edges"] == [{"from_feature": "dive", "to_feature": "dive", "count": 1}]
    assert {r["kind"] for r in result["outcomes"]} == {"ai", "workflow"}
    assert all(r["outcome"] == "failed" for r in result["outcomes"])
    assert {r["duration_bucket"] for r in result["durations"]} == {"10_to_60s", "under_10s"}
    serialized = json.dumps(result)
    for excluded in ("participant", "session", "node_id", "trace", "event_id", "sequence",
                     "accepted_at", "day", feedback.SESSION):
        # retention_days is a fixed policy value, not an observation date.
        assert excluded not in serialized.replace("retention_days", "retention")


def test_unknown_and_malformed_raw_values_cannot_leak_into_export():
    report = feedback_report.aggregate([None, "secret", {
        "event": "ai.started", "feature": "secret", "backend": "secret",
        "model_family": "secret", "input_size": "secret", "prompt": "secret",
        "account": "secret", "node_id": "secret", "parent_node_id": "missing",
    }, {"event": "ai.completed", "feature": ["secret"], "success": "secret"}], "fixture")
    assert "secret" not in json.dumps(report)
    assert report["workflow_edges"] == []
    assert report["outcomes"][0]["outcome"] == "unknown"
    assert report["durations"][0]["duration_bucket"] == "unknown"


@pytest.mark.parametrize(("value", "bucket"), [
    (0, "under_10s"), (9, "under_10s"), (10, "10_to_60s"), (59, "10_to_60s"),
    (60, "1_to_5m"), (299, "1_to_5m"), (300, "over_5m"), (-1, "unknown"),
    (None, "unknown"), (True, "unknown"), (float("nan"), "unknown"),
    (float("inf"), "unknown"),
])
def test_duration_buckets(value, bucket):
    assert feedback_report.duration(value) == bucket


def test_disabled_and_changed_policy_export_no_observations(workspace, monkeypatch):
    empty = feedback.export_payload()
    assert not feedback.path().exists()
    feedback.set_consent(True)
    feedback.record("ui.action", "ai_settings")
    feedback.set_consent(False)
    assert feedback.export_payload() == empty
    feedback.set_consent(True)
    feedback.record("ui.action", "ai_settings")
    monkeypatch.setattr(feedback, "POLICY", "next-purpose")
    assert feedback.export_payload()["feature_usage"] == []


def test_summary_is_readable_and_export_contains_exact_reviewed_aggregates(workspace, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from paper_daily.desktop.feedback_dialog import FeedbackDialog

    app = QApplication.instance() or QApplication([])
    feedback.set_consent(True)
    feedback.record("ui.action", "ai_settings")
    widget = FeedbackDialog()
    assert "AI 設定：1 次" in widget.summary.toPlainText()
    assert widget.report_tabs.currentWidget() is widget.summary
    reviewed = widget.preview.toPlainText()
    target = workspace / "report.json"

    def choose(*args):
        feedback.record("ui.action", "list_overview")
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    widget.export_preview()
    assert target.read_text(encoding="utf-8") == reviewed
    assert "events" not in json.loads(reviewed)
    widget.deleteLater()
    app.processEvents()
