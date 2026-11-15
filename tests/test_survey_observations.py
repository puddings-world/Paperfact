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
    child = """
import os
import sys
from paper_daily.cli_job_protocol import hello_line, read_frame, ready_line
identity, command = sys.argv[2], sys.argv[3:]
sys.stdout.buffer.write(hello_line(identity))
sys.stdout.buffer.flush()
read_frame(sys.stdin.buffer, expected_request_id=identity, expected_command=command)
sys.stdout.buffer.write(ready_line(identity))
sys.stdout.buffer.flush()
print(os.environ['PAPERFACT_DATA'], flush=True)
"""
    monkeypatch.setattr(
        runtime,
        "cli_command",
        lambda *args: [sys.executable, "-c", child, *args],
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


def test_recreated_input_paper_with_identical_content_cannot_publish_old_survey(conn, monkeypatch):
    from paper_daily.research_lifecycle import parent_lifecycle

    seed_survey(conn)
    before = dict(conn.execute("SELECT * FROM papers WHERE id='a'").fetchone())
    lifetimes = []

    def complete(*_args, **_kwargs):
        lifetimes.append(parent_lifecycle(conn, 'paper', 'a'))
        # Restored research can retain the same ID, metadata and saved analyses.
        conn.execute("DELETE FROM papers WHERE id='a'")
        columns = ','.join(before)
        marks = ','.join('?' for _ in before)
        conn.execute(f'INSERT INTO papers({columns}) VALUES({marks})', tuple(before.values()))
        conn.commit()
        lifetimes.append(parent_lifecycle(conn, 'paper', 'a'))
        assert dict(conn.execute("SELECT * FROM papers WHERE id='a'").fetchone()) == before
        return BODY, 'ok'

    monkeypatch.setattr(survey.llm, 'complete', complete)
    success, reason = survey.write('cat', force=True)
    assert lifetimes[0] and lifetimes[1] and lifetimes[0] != lifetimes[1]
    assert not success and 'retained' in reason
    assert survey.get(conn, 'cat')['body'] == 'Original survey'
    saved = receipts(conn)
    assert len(saved) == 1 and saved[0]['status'] == 'candidate'
    assert json.loads(saved[0]['row_json'])['body'] == BODY


def test_older_survey_observation_without_member_lifetimes_requires_review(conn):
    from dataclasses import replace

    seed_survey(conn)
    context = research_generation.begin_generation(conn, table='list_surveys', owner_id='cat')
    data = context.data
    data['inputs'].pop('_paper_lifetimes')
    old = replace(context, _json=json.dumps(data))
    row = dict(list_id='cat', body=BODY, papers=2, spec=survey.SURVEY_SPEC,
               written_at=store.now(), edited=0)
    result = research_generation.publish_generated(old, row=row)
    assert result.status == 'candidate'
    assert survey.get(conn, 'cat')['body'] == 'Original survey'
    saved = receipts(conn)
    assert len(saved) == 1 and saved[0]['status'] == 'candidate'
    assert json.loads(saved[0]['row_json'])['body'] == BODY
    retry = research_generation.retry_publication(store.DB_PATH, result.request_id)
    assert retry.status == 'candidate' and retry.candidate_id == result.candidate_id


def test_survey_evidence_inputs_describe_actual_retained_prompt_without_live_lookup(conn):
    from dataclasses import replace

    from paper_daily import survey_content

    context = research_generation.begin_generation(conn, table='list_surveys', owner_id='cat')
    prompt, count = survey.build_input_from_snapshot(context.inputs, 'cat')
    assert '_paper_lifetimes' not in context.inputs
    record = survey.evidence_inputs(context)
    assert record['list_id'] == 'cat' and record['list_name'] == context.inputs['list']['name']
    assert record['list_lifecycle'] == context.data['parent_lifecycle']
    assert record['prompt_hash'] == survey_content.body_hash(prompt)
    assert len(record['members']) == count
    assert [r['paper_id'] for r in record['members']] == [
        r['paper_id'] for r in context.data['inputs']['_members']]
    paper = next(r for r in context.inputs['papers'] if r['id'] == record['members'][0]['paper_id'])
    card = survey.digest(paper, paper['dive'], paper['context'], paper['later'],
                         min(survey.PER_PAPER_MAX, survey.BUDGET // count))
    assert record['members'][0]['input_hash'] == survey_content.body_hash(card)
    encoded = json.dumps(record)
    assert str(store.DB_PATH) not in encoded and 'db_path' not in encoded
    conn.execute("UPDATE papers SET title='Later title' WHERE id='a'")
    conn.commit()
    assert survey.evidence_inputs(context) == record
    record['members'][0]['title'] = 'Caller mutation'
    assert survey.evidence_inputs(context)['members'][0]['title'] != 'Caller mutation'
    old = context.data
    old['inputs'].pop('_paper_lifetimes')
    with pytest.raises(ValueError, match='not captured'):
        survey.evidence_inputs(replace(context, _json=json.dumps(old)))


@pytest.fixture
def survey_original_context(conn):
    from pathlib import Path

    import pymupdf

    root = Path(store.DB_PATH).parent / 'pdf'
    root.mkdir()
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72),
                         'Original survey evidence. A selected method improves measurement.')
        raw = pdf.tobytes()
    path = root / 'a.pdf'
    path.write_bytes(raw)
    conn.commit()
    context = research_generation.begin_generation(conn, table='list_surveys', owner_id='cat')
    return context, root, raw


def survey_source_sections(corpus):
    return [dict(heading='Captured evidence', statements=[
        dict(text='A proposed result requiring researcher interpretation.',
             interpretation='reported',
             passages=[dict(source_id=corpus.sources[0]['id'], quote='A selected method',
                            page=1, anchor=None)]),
        dict(text='A result for which the original is unavailable.', interpretation='inference',
             passages=[dict(source_id=corpus.sources[1]['id'], quote='A proposed unavailable quote',
                            page=None, anchor=None)]),
    ])]


SURVEY_PROVENANCE = dict(task='survey', backend='codex', requested_model='configured-model',
                         returned_model=None)


def test_survey_sources_check_real_owned_quotes_and_preserve_missing_originals(
    survey_original_context,
):
    from copy import deepcopy

    from paper_daily import survey_content, survey_sources

    context, root, _raw = survey_original_context
    corpus = survey_sources.capture(context, legacy_root=root)
    assert survey_sources.current(corpus)
    assert [r['state'] for r in corpus.sources] == ['captured', 'unavailable']
    pages = survey_sources.pages(corpus)
    assert len(pages) == 1 and pages[0]['source_id'] == corpus.sources[0]['id']
    assert 'A selected method' in pages[0]['pages'][0]['text']
    with pytest.raises(ValueError, match='prompt budget'):
        survey_sources.pages(corpus, max_bytes=1)
    with pytest.raises(ValueError, match='cancelled'):
        survey_sources.pages(corpus, cancelled=lambda: True)
    sections = survey_source_sections(corpus)
    proposal = survey_sources.verify(corpus, sections, provenance=SURVEY_PROVENANCE)
    report = proposal.report
    checked = report['sections'][0]['statements']
    assert checked[0]['passages'][0]['location']['state'] == 'located'
    assert checked[1]['passages'][0]['location'] is None
    assert report['semantic_validation'] == 'not_performed'
    assert survey_content.decode(survey_content.encode(report)) == report
    assert sections == survey_source_sections(corpus)
    report['sections'][0]['statements'][0]['text'] = 'Caller mutation'
    assert proposal.report['sections'][0]['statements'][0]['text'] != 'Caller mutation'
    forged = deepcopy(sections)
    forged[0]['statements'][0]['passages'][0]['location'] = {'state': 'located'}
    with pytest.raises(ValueError):
        survey_sources.verify(corpus, forged, provenance=SURVEY_PROVENANCE)
    missing_quote = deepcopy(sections)
    missing_quote[0]['statements'][0]['passages'][0]['quote'] = 'These words are not in the PDF'
    missing = survey_sources.verify(corpus, missing_quote, provenance=SURVEY_PROVENANCE).report
    assert missing['sections'][0]['statements'][0]['passages'][0]['location']['state'] == 'missing'


def test_survey_sources_do_not_merge_equal_byte_owners_or_follow_replaced_pdf(
    conn, survey_original_context,
):
    from dataclasses import replace

    import pymupdf

    from paper_daily import survey_sources

    _context, root, raw = survey_original_context
    other = root / 'b.pdf'
    other.write_bytes(raw)
    conn.commit()
    context = research_generation.begin_generation(conn, table='list_surveys', owner_id='cat')
    corpus = survey_sources.capture(context, legacy_root=root)
    assert corpus.sources[0]['document_hash'] == corpus.sources[1]['document_hash']
    assert corpus.sources[0]['id'] != corpus.sources[1]['id']
    with pytest.raises(ValueError, match='sealed capture'):
        survey_sources.current(replace(corpus, _snapshots=(object(), None)))
    swapped = replace(corpus, _snapshots=tuple(reversed(corpus._snapshots)))
    with pytest.raises(ValueError, match='capture changed'):
        survey_sources.current(swapped)
    sections = survey_source_sections(corpus)
    sections[0]['statements'][1]['passages'] = []
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72, 72), 'A different new original with unrelated text.')
        (root / 'a.pdf').write_bytes(pdf.tobytes())
    assert not survey_sources.current(corpus)
    proposal = survey_sources.verify(corpus, sections, provenance=SURVEY_PROVENANCE)
    # Old immutable-source proposals remain inspectable; current() denies publication readiness.
    assert proposal.report['sections'][0]['statements'][0]['passages'][0]['location']['state'] \
        == 'located'
    forged = replace(proposal, _json=proposal._json.replace('proposed result', 'invented result'))
    with pytest.raises(ValueError, match='changed after original checks'):
        survey_sources.checked_proposal(forged)


def test_survey_sources_cancellation_selection_and_checks_do_not_write_research(
    conn, survey_original_context, monkeypatch,
):
    from copy import deepcopy

    from paper_daily import survey_sources

    context, root, _raw = survey_original_context
    before = '\n'.join(conn.iterdump())
    with pytest.raises(ValueError, match='cancelled'):
        survey_sources.capture(context, legacy_root=root, cancelled=lambda: True)
    with pytest.raises(ValueError, match='actual distinct input'):
        survey_sources.capture(context, legacy_root=root, selected_ids=['foreign'])
    corpus = survey_sources.capture(context, legacy_root=root, selected_ids=['a'])
    assert corpus.sources[1]['state'] == 'not_selected'
    sections = survey_source_sections(corpus)
    with pytest.raises(ValueError, match='unselected original'):
        survey_sources.verify(corpus, sections, provenance=SURVEY_PROVENANCE)
    selected = deepcopy(sections)
    selected[0]['statements'][1]['passages'] = []
    with pytest.raises(ValueError, match='cancelled'):
        survey_sources.verify(corpus, selected, provenance=SURVEY_PROVENANCE,
                              cancelled=lambda: True)
    monkeypatch.setattr(survey_sources, 'MAX_ORIGINAL_BYTES', 0)
    with pytest.raises(ValueError, match='capture budget'):
        survey_sources.capture(context, legacy_root=root)
    assert '\n'.join(conn.iterdump()) == before


def test_survey_sources_use_registered_managed_original_not_legacy_alias(tmp_path):
    import hashlib
    from contextlib import closing

    from test_document_reader import LOCAL, prepared, register
    from test_sync_document_research import pdf_bytes
    from test_sync_reading_state_research import STAMP

    from paper_daily import survey_sources

    path, journal, blobs, reader, alias, raw = prepared(tmp_path)
    register(path, journal, blobs, reader)
    alias.write_bytes(pdf_bytes('A different alias must not replace the managed original.'))
    with closing(research_generation._connect(path)) as db:
        db.execute("INSERT INTO lists(id,name,created_at) VALUES('survey','Native source',?)",
                   (STAMP,))
        db.execute("INSERT INTO list_papers(list_id,paper_id,position,added_at) "
                   "VALUES('survey',?,0,?)", (LOCAL, STAMP))
        db.commit()
        context = research_generation.begin_generation(db, table='list_surveys', owner_id='survey')
    corpus = survey_sources.capture(context, legacy_root=reader.legacy_root)
    assert corpus._documents[0].managed
    assert corpus.sources[0]['document_hash'] == hashlib.sha256(raw).hexdigest()
    sections = [dict(heading='Registered source', statements=[
        dict(text='A proposed reading of the registered original.', interpretation='reported',
             passages=[dict(source_id=corpus.sources[0]['id'], quote='Research',
                            page=1, anchor=None)]),
    ])]
    proposal = survey_sources.verify(corpus, sections, provenance=SURVEY_PROVENANCE)
    report = proposal.report
    assert report['sections'][0]['statements'][0]['passages'][0]['location']['state'] == 'located'
    receipts = survey_sources.retain_originals(proposal)
    owner = json.loads(receipts[0]['owner_json'])
    assert owner['paper_id'] == LOCAL
    assert owner['source_owner_id'] == corpus._documents[0].paper_id
    assert survey_sources.retained_originals(proposal, receipts)[0][0].read_bytes() == raw
    assert survey_sources.current(corpus)


def test_survey_original_pairs_survive_primary_replacement_and_exact_retry(
    conn, survey_original_context,
):
    import sqlite3
    from contextlib import closing

    from paper_daily import local_source_owners, source_snapshots, survey_sources
    from paper_daily.manual_highlight_ops import capture_owner

    context, root, raw = survey_original_context
    corpus = survey_sources.capture(context, legacy_root=root)
    proposal = survey_sources.verify(corpus, survey_source_sections(corpus),
                                     provenance=SURVEY_PROVENANCE)
    before = '\n'.join(conn.iterdump())
    receipts = survey_sources.retain_originals(proposal)
    assert len(receipts) == 1
    owner = json.loads(receipts[0]['owner_json'])
    assert owner['format'] == source_snapshots.SURVEY_FORMAT
    assert owner['list_id'] == 'cat' and owner['list_lifecycle'] == context.data['parent_lifecycle']
    assert owner['generation_request_id'] == context.request_id
    assert owner['paper_id'] == 'a' and owner['source_id'] == corpus.sources[0]['id']
    assert source_snapshots.list_owned(context.db_path) == receipts
    files = survey_sources.retained_originals(proposal, receipts)
    assert len(files) == 1 and files[0][0].read_bytes() == raw
    assert {item.name for item in files[0][0].parent.iterdir()} == {'receipt.json', 'original.pdf'}
    (root / 'a.pdf').write_bytes(b'New current source bytes')
    assert not survey_sources.current(corpus)
    assert survey_sources.retain_originals(proposal) == receipts
    assert survey_sources.retained_originals(proposal, receipts)[0][0].read_bytes() == raw
    claim_owner = capture_owner(context.db_path, 'a')
    with closing(sqlite3.connect(context.db_path)) as db:
        assert not local_source_owners._owner_matches(db, claim_owner, receipts[0], generated=True)
        assert not local_source_owners._owner_matches(db, claim_owner, receipts[0])
    assert '\n'.join(conn.iterdump()) == before


def test_cancelled_survey_original_group_reuses_only_complete_pairs(
    conn, survey_original_context,
):
    from paper_daily import source_snapshots, survey_sources

    context, root, raw = survey_original_context
    (root / 'b.pdf').write_bytes(raw)
    corpus = survey_sources.capture(context, legacy_root=root)
    proposal = survey_sources.verify(corpus, survey_source_sections(corpus),
                                     provenance=SURVEY_PROVENANCE)
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) >= 3

    before = '\n'.join(conn.iterdump())
    with pytest.raises(ValueError, match='cancelled'):
        survey_sources.retain_originals(proposal, cancelled=cancelled)
    partial = source_snapshots.list_owned(context.db_path)
    assert len(partial) == 1
    assert source_snapshots.source_path(context.db_path, partial[0]).read_bytes() == raw
    receipts = survey_sources.retain_originals(proposal)
    assert len(receipts) == 2
    assert len(source_snapshots.list_owned(context.db_path)) == 2
    assert {r['request_id'] for r in partial}.issubset({r['request_id'] for r in receipts})
    assert all(path.read_bytes() == raw for path, _version in
               survey_sources.retained_originals(proposal, receipts))
    assert survey_sources.retain_originals(proposal) == receipts
    assert '\n'.join(conn.iterdump()) == before


def test_survey_original_receipt_or_byte_corruption_cannot_gain_association(
    survey_original_context,
):
    from copy import deepcopy

    from paper_daily import source_snapshots, survey_sources

    context, root, _raw = survey_original_context
    corpus = survey_sources.capture(context, legacy_root=root)
    proposal = survey_sources.verify(corpus, survey_source_sections(corpus),
                                     provenance=SURVEY_PROVENANCE)
    receipts = survey_sources.retain_originals(proposal)
    changed = deepcopy(receipts)
    owner = json.loads(changed[0]['owner_json'])
    owner['list_lifecycle'] = '0' * 32
    changed[0]['owner_json'] = json.dumps(owner)
    with pytest.raises(ValueError, match='exact input observation'):
        source_snapshots.validate(changed[0])
    with pytest.raises(ValueError, match='association differs'):
        survey_sources.retained_originals(proposal, changed)
    malformed = deepcopy(receipts[0])
    invalid_owner = json.loads(malformed['owner_json'])
    invalid_owner['format'] = []
    malformed['owner_json'] = json.dumps(invalid_owner)
    with pytest.raises(ValueError, match='Unsupported source snapshot owner'):
        source_snapshots.validate(malformed)
    with pytest.raises(ValueError, match='checked proposal'):
        survey_sources.retain_originals(proposal.report)
    original = survey_sources.retained_originals(proposal, receipts)[0][0]
    original.write_bytes(b'Corrupted archived original')
    with pytest.raises(ValueError):
        survey_sources.retained_originals(proposal, receipts)
    with pytest.raises(ValueError):
        survey_sources.retain_originals(proposal)
    assert original.read_bytes() == b'Corrupted archived original'
    assert context.target is None


def test_detached_backup_keeps_survey_original_as_inactive_provenance(survey_original_context):
    import sqlite3
    import zipfile
    from contextlib import closing

    from paper_daily import source_snapshots, survey_sources, sync_recovery

    context, root, raw = survey_original_context
    corpus = survey_sources.capture(context, legacy_root=root)
    proposal = survey_sources.verify(corpus, survey_source_sections(corpus),
                                     provenance=SURVEY_PROVENANCE)
    receipts = survey_sources.retain_originals(proposal)
    (root / 'a.pdf').unlink()
    archive = context.db_path.parent / 'survey-originals.zip'
    sync_recovery.create(context.db_path, archive, legacy_root=root)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read('objects/' + receipts[0]['sha256']) == raw
    destination = context.db_path.parent / 'detached-survey'
    sync_recovery.restore_detached(archive, destination)
    assert source_snapshots.list_owned(destination / 'papers.db') == []
    with closing(sqlite3.connect(destination / 'papers.db')) as db:
        kept = [json.loads(r[0]) for r in db.execute(
            'SELECT data FROM recovery_records WHERE table_name=?', (source_snapshots.TABLE,))]
        assert not db.execute("SELECT 1 FROM sqlite_master "
                              "WHERE name='paperfact_sync_identity'").fetchone()
    assert kept == receipts
    assert (destination / 'objects' / receipts[0]['sha256']).read_bytes() == raw
