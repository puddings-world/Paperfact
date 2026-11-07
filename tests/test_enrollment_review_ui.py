"""Actual bilingual copy preview exposes reviewed Q&A history before preparing."""

import json
from contextlib import closing

import pytest
from test_enrollment_chat_review_history import reviewed as reviewed
from test_enrollment_chat_review_history import source as source
from test_enrollment_dialog import app as app
from test_enrollment_dialog import wait

from paper_daily import enrollment_history
from paper_daily import research_generation as generation
from paper_daily.desktop.enrollment_dialog import EnrollmentDialog


@pytest.mark.parametrize(
    "language,label", [("en", "Q&A review history"), ("zh-TW", "問答審閱歷史")]
)
def test_actual_reviewed_answer_copy_preview_prepare_and_repeat_preserve_receipt(
    reviewed,
    app,
    tmp_path,
    language,
    label,
):
    value = reviewed
    before = value["database"].read_bytes()
    view = EnrollmentDialog(value["database"], language=language)
    view.show()
    try:
        assert view.check_content()
        assert not view.check_content()
        wait(app, lambda: not view.busy)
        assert view.preview["supported"]
        assert not view.prepare_button.isEnabled()
        assert label + ": 1" in view.coverage.toPlainText()
        assert "research_chat_review_receipts" not in view.coverage.toPlainText()
        output, backup = tmp_path / "ui-copy", tmp_path / "ui-backup.zip"
        view.output_path.setText(str(output))
        view.backup_path.setText(str(backup))
        assert view.prepare_button.isEnabled()
        view.prepare_button.click()
        view.prepare_button.click()
        wait(app, lambda: not view.busy)
        assert output.is_dir() and backup.is_file()
        assert view.open_button.isEnabled()
        with closing(generation._connect(output / "papers.db")) as conn:
            rows = enrollment_history.archived(conn)
            originals = [
                json.loads(row["body_json"])
                for row in rows
                if row["protocol"] == "research_chat_review_receipts"
            ]
            assert originals == [value["receipt"]]
        assert value["database"].read_bytes() == before
    finally:
        if view.busy:
            view.cancel()
            wait(app, lambda: not view.busy)
        view.close()
