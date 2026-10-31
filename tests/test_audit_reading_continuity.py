"""Ordinary persisted reading state is not a changed scientific input."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from test_source_fact_dialog import open_child, wait
from test_source_fact_dialog import scene as scene_fixture
from test_source_fact_dialog import source as source_fixture

from paper_daily import audit_fact_extraction, llm, research_audit, store
from paper_daily.desktop import ui_state

scene, source = scene_fixture, source_fixture


@pytest.fixture(autouse=True)
def candidate_source_identity():
    expected = Path(__file__).resolve().parents[1] / "src/paper_daily/audit_fact_extraction.py"
    assert Path(audit_fact_extraction.__file__).resolve() == expected


@pytest.mark.parametrize("change", ["opened_at", "note_body"])
def test_pending_comparison_distinguishes_reading_state_from_saved_research(
    scene, monkeypatch, change
):
    child = open_child(scene)
    capture = child.capture
    database = scene.source._owner.db_path
    monkeypatch.setattr(store, "DB_PATH", database)
    entered, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", held)
    try:
        assert child.generate() and not child.generate()
        wait(scene.app, entered.is_set)
        if change == "opened_at":
            ui_state.save("ui.paper.opened:paper", "2026-10-31T00:00:00+00:00")
            assert ui_state.flush()
        else:
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("UPDATE notes SET body='Changed scientific content' WHERE id=1")
        assert not capture.current(), "Control must really change the database/WAL fence"
        child._tick()
        release.set()
        wait(scene.app, lambda: not child.busy)
        assert scene.counts["model"] == 1
        assert scene.question.text() == "Unsent question"
        assert scene.note.toPlainText() == "Unsent note"
        if change == "opened_at":
            assert child.report is not None
            text = child.output.toPlainText()
            assert "50 participants" in text and "audit-request" in text
            assert child.generate_button.isEnabled()
            with closing(sqlite3.connect(database)) as conn:
                assert conn.execute("SELECT body FROM notes ORDER BY id").fetchall() == [
                    ("50 participants",), ("60 participants",)
                ]
        else:
            assert child.report is None and not child.output.toPlainText()
            assert not child.generate_button.isEnabled()
            with closing(sqlite3.connect(database)) as conn:
                assert conn.execute("SELECT body FROM notes WHERE id=1").fetchone() == (
                    "Changed scientific content",
                )
    finally:
        release.set()
        wait(scene.app, lambda: not child.busy)


@pytest.mark.parametrize("renew", [False, True], ids=["strict-default", "reading-owner"])
@pytest.mark.parametrize("change", ["opened_at", "note_body"])
def test_producer_renews_only_unchanged_scientific_inputs_without_a_second_call(
    scene, monkeypatch, renew, change
):
    capture, owner = scene.audit.captured, scene.audit.owner
    database = scene.source._owner.db_path
    monkeypatch.setattr(store, "DB_PATH", database)

    def completion(prompt, **kwargs):
        reply = scene.complete(prompt, **kwargs)
        if change == "opened_at":
            ui_state.save("ui.paper.opened:paper", "2026-10-31T00:00:00+00:00")
            assert ui_state.flush()
        else:
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute("UPDATE notes SET body='Changed scientific content' WHERE id=1")
        return reply

    monkeypatch.setattr(llm, "complete_result", completion)

    def execute():
        options = {"reading_owner": owner} if renew else {}
        job = audit_fact_extraction.ExtractionJob.prepare(capture, ["notes:1"], **options)
        return job.run()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        if renew and change == "opened_at":
            result = future.result(timeout=15)
            assert result.current()
            fresh = result.sheet._capture
            assert fresh is not capture and fresh.current() and not capture.current()
            assert fresh._state_json == capture._state_json
            assert fresh._items_json == capture._items_json
            assert fresh.snapshot._source_json == capture.snapshot._source_json
            assert fresh.snapshot._bytes == capture.snapshot._bytes
            assert result.execution["requested_model"] == "audit-request"
            assert result.execution["reported_model"] == "audit-reported"
            assert result.sheet.report["facts"][0]["evidence"][0]["location"]["state"] == "located"
        else:
            with pytest.raises(research_audit.AuditError) as caught:
                future.result(timeout=15)
            assert caught.value.code == "saved_content_changed"
    assert scene.counts["model"] == 1
    assert not capture.current()


@pytest.mark.parametrize("change", ["cancel", "config", "source", "replace_database"])
def test_reading_interference_never_hides_cancellation_account_source_or_native_changes(
    scene, monkeypatch, change, tmp_path
):
    import os

    child = open_child(scene)
    monkeypatch.setattr(store, "DB_PATH", scene.source._owner.db_path)
    entered, release = threading.Event(), threading.Event()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return scene.complete(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", held)
    try:
        assert child.generate()
        wait(scene.app, entered.is_set)
        ui_state.save("ui.paper.opened:paper", "2026-10-31T00:00:00+00:00")
        assert ui_state.flush()
        if change == "cancel":
            child.cancel()
        elif change == "config":
            scene.config.write_text('{"different":"account"}', encoding="utf-8")
        elif change == "source":
            scene.source.path.write_bytes(b"actual changed source")
        else:
            replacement = tmp_path / "replacement.sqlite"
            with (
                closing(sqlite3.connect(scene.source._owner.db_path)) as old,
                closing(sqlite3.connect(replacement)) as new,
            ):
                old.backup(new)
            os.replace(replacement, scene.source._owner.db_path)
        child._tick()
        release.set()
        wait(scene.app, lambda: not child.busy)
        assert child.report is None and not child.output.toPlainText()
        assert scene.counts["model"] == 1
        assert scene.question.text() == "Unsent question"
        assert scene.note.toPlainText() == "Unsent note"
    finally:
        release.set()
        wait(scene.app, lambda: not child.busy)


def complete_with_reading_write(scene, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", scene.source._owner.db_path)

    def result(prompt, **kwargs):
        response = scene.complete(prompt, **kwargs)
        for stamp in ("2026-10-31T00:00:00+00:00", "2026-10-31T00:00:01+00:00"):
            ui_state.save("ui.paper.opened:paper", stamp)
            assert ui_state.flush()
        return response

    monkeypatch.setattr(llm, "complete_result", result)


def test_renewed_report_source_action_checks_the_exact_original_without_another_model_call(
    scene, monkeypatch
):
    jumps = []
    scene.audit.source_callback = lambda source: jumps.append(source) or True
    child = open_child(scene)
    complete_with_reading_write(scene, monkeypatch)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    assert child.report is not None and child.source_buttons
    assert child.source_buttons[0].isEnabled()
    child.source_buttons[0].click()
    wait(scene.app, lambda: not child.busy)
    assert len(jumps) == 1
    assert jumps[0]["document_hash"] == scene.source.sha256
    assert jumps[0]["page"] == 2
    assert jumps[0]["text"] == "Replication used a held-out cohort of 50 participants."
    assert scene.counts["model"] == 1


def test_accepted_close_releases_the_new_execution_capture_without_gc(scene, monkeypatch):
    import weakref

    from PySide6.QtCore import QCoreApplication, QEvent

    child = open_child(scene)
    complete_with_reading_write(scene, monkeypatch)
    assert child.generate()
    wait(scene.app, lambda: not child.busy)
    assert child._execution_capture is not child.capture
    fresh = weakref.ref(child._execution_capture)
    retained_text = child.output.toPlainText()
    assert retained_text and child.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    scene.app.processEvents()
    assert child.disposed and child._execution_capture is None
    assert child.capture is None and child.report is None and child.accepted is None
    assert fresh() is None
    assert child.output.toPlainText() == retained_text
    assert scene.counts["model"] == 1
