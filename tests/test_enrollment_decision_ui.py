"""The copy preview explains preserved review decisions in both UI languages."""

import json
from contextlib import closing

import pytest
from test_enrollment_dialog import app as app
from test_enrollment_dialog import wait
from test_enrollment_review_decisions import decision as decision
from test_enrollment_review_decisions import source as source

from paper_daily import enrollment_history
from paper_daily import research_generation as generation
from paper_daily.desktop.enrollment_dialog import EnrollmentDialog


@pytest.mark.parametrize(
    "language,label", [("en", "Review decision history"), ("zh-TW", "審閱決策歷史")]
)
def test_review_decision_copy_controls_show_history_and_prepare_only_once(
    decision, app, tmp_path, language, label
):
    value = decision
    before = value["database"].read_bytes()
    view = EnrollmentDialog(value["database"], language=language)
    view.show()
    try:
        assert view.check_content()
        assert not view.check_content()
        wait(app, lambda: not view.busy)
        assert view.preview["supported"]
        assert label + ": 1" in view.coverage.toPlainText()
        assert "research_review_receipts" not in view.coverage.toPlainText()
        assert not view.prepare_button.isEnabled()
        output, backup = tmp_path / "ui-copy", tmp_path / "ui-backup.zip"
        view.output_path.setText(str(output))
        view.backup_path.setText(str(backup))
        assert view.prepare_button.isEnabled()
        view.prepare_button.click()
        view.prepare_button.click()
        wait(app, lambda: not view.busy)
        assert output.is_dir() and backup.is_file() and view.open_button.isEnabled()
        with closing(generation._connect(output / "papers.db")) as conn:
            archived = enrollment_history.archived(conn)
            receipts = [
                json.loads(row["body_json"])
                for row in archived
                if row["protocol"] == "research_review_receipts"
            ]
            assert receipts == [value["receipt"]]
        assert value["database"].read_bytes() == before
    finally:
        if view.busy:
            view.cancel()
            wait(app, lambda: not view.busy)
        view.close()
