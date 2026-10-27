"""Shared review dialog exposes typed grouped actions without an unsafe JSON editor."""

from threading import Event

from PySide6.QtWidgets import QMessageBox
from test_compound_review import candidate
from test_research_generation import rows
from test_research_generation import workspace as workspace
from test_review_dialog import app as app
from test_review_dialog import opened, wait

from paper_daily import store


def test_group_readonly_apply_rapid_repeat_and_reopen(app, workspace):
    path, _client, _document = workspace
    candidate(workspace)
    dialog = opened(app, path)
    try:
        assert dialog.preview.data["origin"] == "compound"
        assert dialog.draft.isReadOnly()
        assert '"one"' in dialog.draft.toPlainText()
        assert '"two"' in dialog.draft.toPlainText()
        assert dialog.target_button.isEnabled()
        dialog.apply.click()
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert len(rows(path, "SELECT * FROM cites")) == 2
        assert len(rows(path, "SELECT * FROM research_review_receipts")) == 1
        assert not dialog.apply.isEnabled()
    finally:
        dialog.reject()
    reopened = opened(app, path)
    try:
        assert '"one"' in reopened.draft.toPlainText()
        assert "applied" in reopened.list.currentItem().text()
    finally:
        reopened.reject()


def test_group_confirmation_cancel_and_late_change_failure_remain_visible(
    app, workspace, monkeypatch
):
    path, _client, _document = workspace
    candidate(workspace)
    dialog = opened(app, path)
    try:
        preview = dialog.service.target_preview(dialog.preview, "paper")
        dialog._display(preview)
        monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Cancel)
        dialog.apply.click()
        assert rows(path, "SELECT * FROM cites") == []
        assert not dialog.busy
        monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
        with store.connect() as conn:
            conn.execute("UPDATE papers SET title='Changed after preview' WHERE id='paper'")
        dialog.apply.click()
        wait(app, lambda: not dialog.busy)
        assert dialog.isVisible()
        assert "changed" in dialog.status.text()
        assert '"one"' in dialog.draft.toPlainText()
        assert rows(path, "SELECT * FROM cites") == []
    finally:
        dialog.reject()


def test_close_cancels_pending_group_before_any_commit(app, workspace, monkeypatch):
    path, _client, _document = workspace
    candidate(workspace)
    dialog = opened(app, path)
    entered, release = Event(), Event()
    original = dialog.service.decide

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "decide", delayed)
    dialog.apply.click()
    wait(app, entered.is_set)
    assert dialog.close()
    release.set()
    wait(app, lambda: all(f.done() for f, *_ in dialog.jobs))
    assert rows(path, "SELECT * FROM cites") == []
    assert rows(path, "SELECT status FROM research_compound_requests") == [{"status": "candidate"}]


def test_group_plain_text_has_meaningful_fields_and_explicit_deletions():
    from paper_daily.desktop.review_compound_text import group_text

    value = {
        "puts": [
            {
                "title": "<script>untrusted title</script>",
                "ref_key": "R1",
                "gist": "Core evidence",
                "contexts_json": None,
                "spec": None,
            }
        ],
        "deletes": ["R2"],
        "completion": None,
    }
    english = group_text(value)
    chinese = group_text(value, chinese=True)
    assert "Add or replace (1)" in english and "Remove (1)\n- R2" in english
    assert "Key point: Core evidence" in english
    assert "新增／取代 (1)" in chinese and "刪除 (1)\n- R2" in chinese
    assert "contexts_json" not in english and "null" not in english
    assert "<script>untrusted title</script>" in english
