"""Actual survey generation and editing preserve the version the researcher saw."""

import json
import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from test_survey import conn as _survey_fixture
from test_sync_capture import bound as _bound_fixture
from test_sync_capture import make, seed

from paper_daily import research_generation, store, survey
from paper_daily.desktop import main, survey_dialog
from paper_daily.sync_capture import StaleCaptureError

conn = _survey_fixture
bound = _bound_fixture
BODY = "## Research history\n" + "A supported explanation of the evidence. " * 100


def seed_survey(conn):
    conn.execute(
        "INSERT INTO list_surveys(list_id,body,papers,spec,written_at,edited) "
        "VALUES('cat','Original survey',2,?,?,0)",
        (survey.SURVEY_SPEC, store.now()),
    )
    conn.commit()


def receipts(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM research_generation_requests")]


def test_generated_prompt_is_exact_captured_snapshot(conn, monkeypatch):
    expected, _ = survey.build_input(conn, "cat")
    calls = []

    def complete(prompt, **kwargs):
        calls.append((prompt, kwargs["task"]))
        return BODY, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("cat") == (True, "ok")
    assert calls == [(expected, "survey")]
    assert survey.get(conn, "cat")["body"] == BODY
    assert receipts(conn)[0]["status"] == "accepted"


@pytest.mark.parametrize("change", ["edit", "metadata", "membership", "order", "dive", "parent"])
def test_changes_during_generation_retain_output_without_overwriting(conn, monkeypatch, change):
    seed_survey(conn)

    def complete(*_args, **_kwargs):
        if change == "edit":
            survey.edit("cat", "Newer manual survey")
        else:
            sql = {
                "metadata": "UPDATE papers SET title='Changed title' WHERE id='a'",
                "membership": "DELETE FROM list_papers WHERE list_id='cat' AND paper_id='a'",
                "order": "UPDATE list_papers SET position=position+5 WHERE list_id='cat'",
                "dive": "UPDATE dives SET body='New explanation' WHERE paper_id='a'",
                "parent": "DELETE FROM lists WHERE id='cat'",
            }[change]
            conn.execute(sql)
            conn.commit()
        return BODY, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    success, reason = survey.write("cat", force=True)
    assert not success and "retained" in reason
    assert survey.get(conn, "cat")["body"] == (
        "Newer manual survey" if change == "edit" else "Original survey"
    )
    candidates = [r for r in receipts(conn) if r["status"] == "candidate"]
    assert len(candidates) == 1
    assert json.loads(candidates[0]["row_json"])["body"] == BODY
    result = research_generation.retry_publication(store.DB_PATH, candidates[0]["request_id"])
    assert result.status == "candidate" and result.candidate_id == candidates[0]["candidate_id"]


def test_repeated_activation_is_busy_without_second_model_call(conn, monkeypatch):
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(1)
        nested = survey.write("cat")
        assert not nested[0] and "already" in nested[1]
        return BODY, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("cat") == (True, "ok")
    assert calls == [1] and len(receipts(conn)) == 1


def test_failure_releases_job_and_retry_can_generate(conn, monkeypatch):
    calls = iter([(None, "provider unavailable"), (BODY, "ok")])
    monkeypatch.setattr(survey.llm, "complete", lambda *_a, **_k: next(calls))
    assert survey.write("cat") == (False, "provider unavailable")
    assert survey.get(conn, "cat") is None
    assert survey.write("cat") == (True, "ok")
    assert len(receipts(conn)) == 1


def test_empty_list_does_not_invoke_provider(conn, monkeypatch):
    conn.execute("DELETE FROM list_papers WHERE list_id='cat'")
    conn.commit()
    monkeypatch.setattr(survey.llm, "complete", lambda *_a, **_k: pytest.fail("No inputs"))
    assert survey.write("cat") == (False, "no papers in list cat")


def test_workspace_switch_during_model_call_saves_only_original_database(
    conn, monkeypatch, tmp_path
):
    original_path = store.DB_PATH
    other = tmp_path / "other.db"
    with sqlite3.connect(other) as db:
        db.executescript(store.SCHEMA)

    def complete(*_args, **_kwargs):
        monkeypatch.setattr(store, "DB_PATH", other)
        return BODY, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("cat") == (True, "ok")
    assert survey.get(conn, "cat")["body"] == BODY
    with sqlite3.connect(other) as db:
        assert db.execute("SELECT COUNT(*) FROM list_surveys").fetchone()[0] == 0
    monkeypatch.setattr(store, "DB_PATH", original_path)


def test_stale_editor_candidate_and_retry_preserve_both_bodies(conn):
    seed_survey(conn)
    with store.connect() as db:
        expected = survey.edit_snapshot(db, "cat")
    survey.edit("cat", "Newer elsewhere")
    ids = []
    for _ in range(2):
        with pytest.raises(StaleCaptureError) as error:
            survey.edit("cat", "My draft", expected=expected)
        ids.append(error.value.candidate_id)
    assert ids[0] == ids[1]
    assert survey.get(conn, "cat")["body"] == "Newer elsewhere"
    candidates = [r for r in receipts(conn) if r["status"] == "candidate"]
    assert len(candidates) == 1
    assert json.loads(candidates[0]["row_json"])["body"] == "My draft"


def test_wrong_list_or_empty_editor_does_not_write(conn):
    seed_survey(conn)
    with store.connect() as db:
        expected = survey.edit_snapshot(db, "cat")
    with pytest.raises(ValueError, match="another list"):
        survey.edit("other", "Wrong", expected=expected)
    with pytest.raises(ValueError, match="nonempty"):
        survey.edit("cat", "  ", expected=expected)
    assert survey.get(conn, "cat")["body"] == "Original survey"


@pytest.fixture
def dialog(conn):
    app = QApplication.instance() or QApplication([])
    seed_survey(conn)
    widget = survey_dialog.SurveyDialog("cat", "Research", main.palette(), language="en")
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_actual_editor_saves_before_accept_and_updates_visible_survey(conn, dialog, monkeypatch):
    def execute(editor):
        editor.editor.setPlainText("Revised from the editor")
        editor.accept()
        assert editor.result() == QDialog.DialogCode.Accepted
        editor.accept()
        return editor.result()

    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", execute)
    dialog._edit()
    assert survey.get(conn, "cat")["body"] == "Revised from the editor"
    assert "Revised from the editor" in dialog.view.toPlainText()
    assert len(receipts(conn)) == 1 and dialog.edit_btn.isEnabled()


def test_actual_stale_editor_keeps_draft_until_cancel(conn, dialog, monkeypatch):
    def execute(editor):
        editor.show()
        editor.editor.setPlainText("My draft")
        survey.edit("cat", "Newer elsewhere")
        editor.accept()
        assert editor.isVisible() and editor.text() == "My draft"
        assert editor.save_status.text() == survey_dialog.SURVEY_EDIT_TEXT["en"]["stale"]
        editor.accept()
        editor.reject()
        return editor.result()

    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", execute)
    dialog._edit()
    assert survey.get(conn, "cat")["body"] == "Newer elsewhere"
    assert len([r for r in receipts(conn) if r["status"] == "candidate"]) == 1


def test_changed_visible_survey_requires_refresh_before_editor(conn, dialog, monkeypatch):
    survey.edit("cat", "Newer elsewhere")
    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", lambda *_a: pytest.fail("Stale view"))
    dialog._edit()
    assert dialog.status.text() == survey_dialog.SURVEY_EDIT_TEXT["en"]["changed"]


@pytest.mark.parametrize("switch", ["list", "workspace"])
def test_context_switch_during_editor_retains_draft_and_does_not_write(
    conn, dialog, monkeypatch, switch
):
    def execute(editor):
        editor.show()
        editor.editor.setPlainText("Unsent")
        if switch == "list":
            dialog.list_id = "other"
        else:
            monkeypatch.setattr(store, "DB_PATH", store.DB_PATH.with_name("other.db"))
        editor.accept()
        assert editor.isVisible() and editor.text() == "Unsent"
        assert editor.save_status.text() == survey_dialog.SURVEY_EDIT_TEXT["en"]["failed"]
        editor.reject()
        return editor.result()

    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", execute)
    dialog._edit()
    assert survey.get(conn, "cat")["body"] == "Original survey"


def test_cancel_and_reentrant_edit_never_create_second_dialog(conn, dialog, monkeypatch):
    calls = []

    def execute(editor):
        calls.append(1)
        dialog._edit()
        editor.reject()
        return editor.result()

    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", execute)
    dialog._edit()
    assert calls == [1] and survey.get(conn, "cat")["body"] == "Original survey"


def test_missing_list_does_not_invoke_provider(conn, monkeypatch):
    monkeypatch.setattr(survey.llm, "complete", lambda *_a, **_k: pytest.fail("No list"))
    assert survey.write("missing") == (False, "no papers in list missing")


def test_enrolled_survey_first_generation_and_edit_replicate(bound, monkeypatch, tmp_path):
    from paper_daily.sync_service import ReferenceService

    seed()
    monkeypatch.setattr(survey.llm, "complete", lambda *_a, **_k: (BODY, "ok"))
    assert survey.write("list") == (True, "ok")
    with store.connect() as db:
        expected = survey.edit_snapshot(db, "list")
    survey.edit("list", "Edited survey", expected=expected)
    pending = bound.journal.pending()
    content = [op for op in pending if op["entity_type"] == "research_content"]
    assert len(content) == 2
    assert content[-1]["payload"]["data"]["body"] == "Edited survey"
    service = ReferenceService(tmp_path / "authority.sqlite")
    token = service.enroll("workspace", "a")
    for operation in pending:
        service.push(token, operation)
    peer = make(tmp_path / "peer.sqlite", "b")
    peer.receive(service.pull(service.enroll("workspace", "b")))
    with peer.journal._connect() as db:
        stored = survey.get(db, "list")
        assert stored["body"] == "Edited survey" and stored["edited"] == 1


def test_enrolled_generation_does_not_publish_over_newer_local_edit(bound, monkeypatch):
    seed()
    monkeypatch.setattr(survey.llm, "complete", lambda *_a, **_k: (BODY, "ok"))
    assert survey.write("list") == (True, "ok")

    def complete(*_a, **_k):
        survey.edit("list", "Newer manual survey")
        return "Replacement " + BODY, "ok"

    monkeypatch.setattr(survey.llm, "complete", complete)
    assert survey.write("list", force=True)[0] is False
    with store.connect() as db:
        assert survey.get(db, "list")["body"] == "Newer manual survey"
        candidates = [r for r in receipts(db) if r["status"] == "candidate"]
        assert len(candidates) == 1
    content = [op for op in bound.journal.pending() if op["entity_type"] == "research_content"]
    assert len(content) == 2  # first generation + user edit; rejected output stays local.


def test_unchanged_editor_does_not_mark_survey_as_manually_edited(conn, dialog, monkeypatch):
    before = survey.get(conn, "cat")

    def execute(editor):
        editor.accept()
        return editor.result()

    monkeypatch.setattr(survey_dialog.NoteEditor, "exec", execute)
    dialog._edit()
    assert survey.get(conn, "cat") == before


def test_legacy_timestamp_edit_preserves_original_provenance_and_stable_retry(conn):
    seed_survey(conn)
    conn.execute("UPDATE list_surveys SET written_at='legacy-time',spec=NULL,papers=NULL")
    conn.commit()
    with store.connect() as db:
        expected = survey.edit_snapshot(db, "cat")
    survey.edit("cat", "Updated legacy survey", expected=expected)
    survey.edit("cat", "Updated legacy survey", expected=expected)
    stored = survey.get(conn, "cat")
    assert stored["body"] == "Updated legacy survey" and stored["edited"] == 1
    assert stored["written_at"] == expected.started_at
    assert stored["papers"] is None and stored["spec"] is None
    saved = receipts(conn)
    assert len(saved) == 1
    assert json.loads(saved[0]["context_json"])["target"]["written_at"] == "legacy-time"


def test_background_process_is_bound_and_survives_closed_dialog(conn, dialog, monkeypatch):
    import sys

    from PySide6.QtTest import QTest

    from paper_daily import runtime

    monkeypatch.setenv("PAPERFACT_DATA", "wrong-inherited-workspace")
    monkeypatch.setattr(
        runtime,
        "cli_command",
        lambda *_args: [sys.executable, "-c", "import os; print(os.environ['PAPERFACT_DATA'])"],
    )
    dialog.show()
    dialog._run_ready()
    job = dialog.job
    assert job is not None
    dialog._run_ready()
    assert dialog.job is job
    dialog.close()
    for _ in range(1000):
        QTest.qWait(10)
        if dialog.job is None:
            break
    assert dialog.job is None
    assert str(store.DB_PATH.parent.resolve()) in dialog._output_tail
    assert "wrong-inherited-workspace" not in dialog._output_tail
    assert not dialog.isVisible()


@pytest.mark.parametrize(
    "language,save,cancel,modes",
    [
        ("en", "Save", "Cancel", ["Edit", "Split", "Preview"]),
        ("zh-TW", "儲存", "取消", ["編輯", "分割", "預覽"]),
    ],
)
def test_editor_controls_match_language(conn, language, save, cancel, modes):
    from PySide6.QtWidgets import QDialogButtonBox

    from paper_daily.desktop.note_editor import NoteEditor

    app = QApplication.instance() or QApplication([])
    editor = NoteEditor("Draft", main.palette(), language=language)
    try:
        buttons = editor.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.StandardButton.Save).text() == save
        assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == cancel
        assert [editor.modes.button(index).text() for index in range(3)] == modes
    finally:
        editor.deleteLater()
        app.processEvents()
