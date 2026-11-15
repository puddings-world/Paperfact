"""Finish a durable report after interruption, using no AI or remote transport."""

from contextlib import closing
from dataclasses import replace
from threading import Event

import pytest
from test_survey_evidence_ui import app as app
from test_survey_evidence_ui import wait_until
from test_survey_publication import prepared as prepared
from test_sync_capture import bound as bound

from paper_daily import llm, store, survey_publication, survey_reader, survey_sources
from paper_daily import research_generation as generation
from paper_daily.desktop.main import LIGHT
from paper_daily.desktop.survey_dialog import SurveyDialog
from paper_daily.sync_artifacts import applied_file, desired_file
from paper_daily.sync_files import list_file_id


def proposal_after(client, root, text):
    with closing(generation._connect(client.journal.path)) as connection:
        context = generation.begin_generation(connection, table="list_surveys", owner_id="list")
    corpus = survey_sources.capture(context, legacy_root=root)
    return survey_sources.verify(
        corpus,
        [
            dict(
                heading="Saved report",
                statements=[
                    dict(
                        text=text,
                        interpretation="synthesis",
                        passages=[
                            dict(
                                source_id=corpus.sources[0]["id"],
                                quote="A selected method",
                                page=1,
                                anchor=None,
                            )
                        ],
                    )
                ],
            )
        ],
        provenance=dict(
            task="survey",
            backend="openai",
            requested_model="synthetic",
            returned_model="synthetic-returned",
        ),
    )


@pytest.fixture(params=["first", "update"])
def pending(request, prepared, monkeypatch):
    client, _server, _token, _files, root, proposal = prepared
    if request.param == "update":
        survey_publication.publish(survey_publication.prepare(proposal))
        proposal = proposal_after(client, root, "A later saved report.")
    staged = survey_publication.prepare(proposal)
    with closing(generation._connect(client.journal.path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        intent = survey_publication.publish_in(connection, staged)
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("Unexpected AI"))
    from paper_daily.desktop import ai_access

    monkeypatch.setattr(ai_access, "requires_ai", lambda *a, **k: pytest.fail("Unexpected login"))
    return client, root, proposal, intent


def state(client):
    with client.journal.transaction() as connection:
        desired = desired_file(connection, list_file_id("list"))
        applied = applied_file(connection, list_file_id("list"))
        count = connection.execute("SELECT count(*) FROM research_file_versions").fetchone()[0]
    return desired, applied, count


def open_report(client):
    dialog = SurveyDialog("list", "Research", LIGHT, language="en")
    dialog.show()
    pane = dialog.saved_report
    wait_until(lambda: pane.future is None and pane.saved is not None)
    dialog.report_tabs.setCurrentIndex(1)
    return dialog, pane


def close_report(dialog, pane):
    dialog.close()
    wait_until(lambda: pane.disposed)
    dialog.deleteLater()


def test_reopened_report_finishes_exact_saved_intent_without_new_versions(pending, app):
    client, _root, proposal, intent = pending
    dialog, pane = open_report(client)
    assert pane.saved.data["update_pending"] and pane.finish.isEnabled()
    assert not dialog.source_btn.isEnabled()
    dialog._run_sources()
    assert dialog.job is None
    close_report(dialog, pane)
    dialog, pane = open_report(client)
    before = state(client)
    try:
        assert pane.saved._desired == intent and pane.finish.isEnabled()
        pane.finish.click()
        pane.finish.click()
        pane.finish_pending()
        wait_until(
            lambda: (
                pane.future is None
                and pane.saved is not None
                and not pane.saved.data["update_pending"]
            )
        )
        assert pane.saved.data["report"] == proposal.report
        assert pane.finish.isHidden() and dialog.source_btn.isEnabled()
        assert state(client) == (intent, intent, before[2])
        assert survey_reader.inspect(pane.saved, 0, 0, 0)["located"]
    finally:
        close_report(dialog, pane)


def test_completion_failure_retains_old_applied_state_and_can_retry(pending, app, monkeypatch):
    client, _root, proposal, intent = pending
    dialog, pane = open_report(client)
    actual = survey_publication.complete_pending
    calls = []

    def flaky(*args, **options):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("Synthetic local activation failure")
        return actual(*args, **options)

    monkeypatch.setattr(survey_publication, "complete_pending", flaky)
    before = state(client)
    try:
        pane.finish.click()
        wait_until(lambda: pane.future is None)
        assert pane.status.text() == pane.words["finish_failed"] and pane.finish.isEnabled()
        assert state(client) == before
        pane.finish.click()
        wait_until(
            lambda: (
                pane.future is None
                and pane.saved is not None
                and not pane.saved.data["update_pending"]
            )
        )
        assert pane.saved.data["report"] == proposal.report and len(calls) == 2
        assert state(client) == (intent, intent, before[2])
    finally:
        close_report(dialog, pane)


def test_close_cancels_completion_then_fresh_dialog_can_finish(pending, app, monkeypatch):
    client, _root, _proposal, intent = pending
    dialog, pane = open_report(client)
    actual = survey_publication.complete_pending
    entered, release = Event(), Event()
    calls = []

    def held(*args, **options):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return actual(*args, **options)

    monkeypatch.setattr(survey_publication, "complete_pending", held)
    before = state(client)
    try:
        pane.finish.click()
        wait_until(entered.is_set)
        pane.finish.click()
        pane.finish_pending()
        assert len(calls) == 1
        dialog.close()
        assert pane.closing and pane.cancelled.is_set()
        release.set()
        wait_until(lambda: pane.disposed)
        assert state(client) == before
    finally:
        release.set()
        close_report(dialog, pane)
    monkeypatch.setattr(survey_publication, "complete_pending", actual)
    dialog, pane = open_report(client)
    try:
        pane.finish.click()
        wait_until(
            lambda: (
                pane.future is None
                and pane.saved is not None
                and not pane.saved.data["update_pending"]
            )
        )
        assert state(client) == (intent, intent, before[2])
    finally:
        close_report(dialog, pane)


def test_old_or_changed_read_cannot_activate_a_newer_pending_report(pending):
    client, root, _proposal, _intent = pending
    old = survey_reader.read(client.journal.path, "list")
    assert old.data["update_pending"]
    newer = survey_publication.prepare(proposal_after(client, root, "A concurrent report."))
    with closing(generation._connect(client.journal.path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        survey_publication.publish_in(connection, newer)
    before = state(client)
    with pytest.raises(ValueError, match="changed after selection"):
        survey_reader.complete_pending(old)
    with pytest.raises(ValueError, match="observed pending"):
        survey_reader.complete_pending(replace(old, _desired=before[0]))
    assert state(client) == before
    saved = survey_reader.read(client.journal.path, "list")
    survey_reader.complete_pending(saved)
    assert state(client) == (before[0], before[0], before[2])


def test_workspace_switch_drops_completion_delivery_and_keeps_original_target(
    pending,
    app,
    monkeypatch,
    tmp_path,
):
    client, _root, _proposal, intent = pending
    dialog, pane = open_report(client)
    actual = survey_publication.complete_pending
    entered, release = Event(), Event()

    def held(*args, **options):
        entered.set()
        assert release.wait(5)
        return actual(*args, **options)

    monkeypatch.setattr(survey_publication, "complete_pending", held)
    try:
        pane.finish.click()
        wait_until(entered.is_set)
        other = tmp_path / "other.sqlite"
        monkeypatch.setattr(store, "DB_PATH", other)
        release.set()
        wait_until(lambda: pane.future is None)
        assert pane.saved is None and pane.status.text() == pane.words["stale"]
        assert not pane.finish.isEnabled() and not other.exists()
        assert state(client)[1] == intent
    finally:
        release.set()
        close_report(dialog, pane)


def test_storage_rebinding_during_materialization_keeps_report_pending(
    pending, monkeypatch, tmp_path
):
    from paper_daily import sync_artifacts
    from paper_daily.sync_blobs import BlobStore

    client, _root, _proposal, _intent = pending
    saved = survey_reader.read(client.journal.path, "list")
    actual = sync_artifacts.materialize
    before = state(client)

    def changed(*args, **options):
        directory = actual(*args, **options)
        with client.journal.transaction() as connection:
            # Simulate a concurrent migration/restore. Ordinary registration refuses moves.
            other = BlobStore(tmp_path / "other-blobs")
            connection.execute(
                "UPDATE research_file_paths SET blob_root=?,version_root=? WHERE id=1",
                (str(other.root), str(tmp_path / "other-versions")),
            )
        return directory

    monkeypatch.setattr(sync_artifacts, "materialize", changed)
    with pytest.raises(ValueError, match="changed"):
        survey_reader.complete_pending(saved)
    assert state(client) == before


def test_same_binding_database_copy_cannot_receive_an_old_read_completion(pending, tmp_path):
    import sqlite3

    from paper_daily.sync_deck_publication import runtime

    client, _root, _proposal, _intent = pending
    saved = survey_reader.read(client.journal.path, "list")
    before = state(client)
    replacement = tmp_path / "replacement.sqlite"
    with (
        closing(sqlite3.connect(client.journal.path)) as source,
        closing(sqlite3.connect(replacement)) as target,
    ):
        source.backup(target)
    replacement.replace(client.journal.path)
    with pytest.raises(ValueError, match="database changed"):
        survey_reader.complete_pending(saved)
    assert state(runtime(database=client.journal.path)) == before
