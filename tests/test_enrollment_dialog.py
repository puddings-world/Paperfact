"""Reviewed desktop enrollment copies preserve the source and pending readers."""

import json
import sqlite3
import threading
import time
from contextlib import closing

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QScrollArea
from test_imported_source_enrollment import imported as imported
from test_local_source_owners import receiver as receiver
from test_package_import import package as package
from test_package_import import rich_package as rich_package
from test_workspace_enrollment import pdf
from test_workspace_enrollment import source as source

from paper_daily.desktop.enrollment_dialog import COPY, EnrollmentDialog
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.document_reader import DocumentReader
from paper_daily.workspace_service import SnapshotChanged


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait(app, condition, timeout=10):
    end = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() >= end:
            raise AssertionError("Enrollment fixture worker did not finish")
        time.sleep(0.005)
    app.processEvents()


@pytest.fixture
def dialog(app, source):
    opened = []
    view = EnrollmentDialog(source, language="en", open_workspace=opened.append)
    view.opened = opened
    view.show()
    yield view
    if view.busy:
        view.cancel()
        wait(app, lambda: not view.busy)
    view.close()


def check(dialog, app):
    assert dialog.check_content()
    wait(app, lambda: not dialog.busy)
    return dialog.preview


def paths(dialog, tmp_path):
    output, backup = tmp_path / "prepared-copy", tmp_path / "independent.zip"
    dialog.output_path.setText(str(output))
    dialog.backup_path.setText(str(backup))
    return output, backup


def test_actual_preview_prepare_open_preserves_source_and_verified_pdf(
    dialog, app, source, tmp_path
):
    primary = pdf(source)
    original = source.read_bytes()
    assert dialog.preview is None and not dialog.prepare_button.isEnabled()
    plan = check(dialog, app)
    assert plan["supported"] and plan["pdf_count"] == 1
    assert "Papers: 1" in dialog.coverage.toPlainText()
    assert "paper: paper.pdf" in dialog.coverage.toPlainText()
    assert not dialog.opened
    output, backup = paths(dialog, tmp_path)
    assert dialog.prepare_button.isEnabled()
    dialog.prepare_button.click()
    assert dialog.busy and not dialog.prepare_button.isEnabled()
    wait(app, lambda: not dialog.busy)
    assert dialog.result["status"] == "prepared_for_review"
    assert not dialog.result["adopted"] and not dialog.result["uploaded"]
    assert output.is_dir() and backup.is_file() and source.read_bytes() == original
    reader = DocumentReader.from_workspace(output / "papers.db")
    try:
        assert reader.resolve("paper").path.read_bytes() == primary.read_bytes()
    finally:
        reader.close()
    with closing(sqlite3.connect(output / "papers.db")) as conn:
        assert conn.execute("SELECT body FROM notes").fetchone()[0] == "A research note"
        assert not conn.execute("SELECT 1 FROM kv WHERE key='auth.secret'").fetchone()
    assert not dialog.opened and dialog.open_button.isEnabled()
    assert dialog.open_copy() and not dialog.open_copy()
    assert len(dialog.opened) == 1
    assert dialog.opened[0].database_path == output / "papers.db"
    assert "separate window" in dialog.status.text()
    assert dialog.guard.path == source and source.read_bytes() == original


def test_unsupported_coverage_is_visible_and_preparation_disabled(dialog, app, source, tmp_path):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE future_research(body TEXT)")
        conn.execute("INSERT INTO future_research VALUES('private research body')")
    plan = check(dialog, app)
    assert not plan["supported"]
    assert "unsupported table: future_research" in dialog.coverage.toPlainText()
    assert "private research body" not in dialog.coverage.toPlainText()
    output, backup = paths(dialog, tmp_path)
    assert not dialog.prepare_button.isEnabled() and not dialog.prepare_copy()
    assert not output.exists() and not backup.exists()


def test_empty_workspace_can_prepare_without_inventing_pdf_or_analysis(app, tmp_path):
    from paper_daily import store

    root = tmp_path / "empty-source"
    root.mkdir()
    database = root / "papers.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.commit()
    view = EnrollmentDialog(database, language="en", open_workspace=lambda _: None)
    try:
        plan = check(view, app)
        assert plan["supported"] and plan["pdf_count"] == 0
        output, backup = paths(view, tmp_path)
        assert view.prepare_copy()
        wait(app, lambda: not view.busy)
        assert view.result and backup.exists()
        with closing(sqlite3.connect(output / "papers.db")) as conn:
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0
    finally:
        view.close()


def test_rapid_preview_clicks_and_close_wait_for_worker(dialog, app, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.plan
    calls = []

    def held(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "plan", held)
    assert dialog.check_content()
    wait(app, entered.is_set)
    assert not dialog.check_content() and not dialog.prepare_copy()
    assert not dialog.close() and not dialog.disposed
    assert "Stopping" in dialog.status.text()
    release.set()
    wait(app, lambda: dialog.disposed)
    assert calls == [1] and dialog.preview is None


def test_preparation_close_and_rapid_repeat_publish_nothing(dialog, app, tmp_path, monkeypatch):
    assert check(dialog, app)["supported"]
    output, backup = paths(dialog, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.prepare
    calls = []

    def held(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "prepare", held)
    assert dialog.prepare_copy()
    wait(app, entered.is_set)
    assert not dialog.prepare_copy() and not dialog.check_content()
    assert not dialog.close()
    release.set()
    wait(app, lambda: dialog.disposed)
    assert calls == [1] and not output.exists() and not backup.exists()


@pytest.mark.parametrize("phase", ["check", "prepare"])
def test_workspace_switch_while_pending_drops_result_and_outputs(
    dialog, app, tmp_path, monkeypatch, phase
):
    active = [dialog.guard.path]
    dialog.guard.current_path = lambda: active[0]
    if phase == "prepare":
        check(dialog, app)
        paths(dialog, tmp_path)
    entered, release = threading.Event(), threading.Event()
    name = "plan" if phase == "check" else "prepare"
    original = getattr(dialog.service, name)

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, name, held)
    assert dialog.check_content() if phase == "check" else dialog.prepare_copy()
    wait(app, entered.is_set)
    active[0] = tmp_path / "other.sqlite"
    dialog._check_source()
    release.set()
    wait(app, lambda: not dialog.busy)
    assert dialog._invalid and dialog.result is None
    assert "workspace changed" in dialog.status.text()
    assert not (tmp_path / "prepared-copy").exists() and not (tmp_path / "independent.zip").exists()
    assert not dialog.open_copy()


def test_failure_retry_preserves_paths_and_request_and_hides_raw_error(
    dialog, app, tmp_path, monkeypatch
):
    check(dialog, app)
    output, backup = paths(dialog, tmp_path)
    original = dialog.service.prepare
    requests = []

    def failed(*args, **kwargs):
        requests.append(kwargs["request_id"])
        raise OSError("fixture-private-content")

    monkeypatch.setattr(dialog.service, "prepare", failed)
    assert dialog.prepare_copy()
    wait(app, lambda: not dialog.busy)
    assert "fixture-private" not in dialog.status.text()
    assert dialog.output_path.text() == str(output) and dialog.backup_path.text() == str(backup)
    assert not output.exists() and not backup.exists() and dialog.prepare_button.isEnabled()

    def retry(*args, **kwargs):
        requests.append(kwargs["request_id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "prepare", retry)
    assert dialog.prepare_copy()
    wait(app, lambda: not dialog.busy)
    assert dialog.result and requests[0] == requests[1]


def test_source_change_failure_requires_new_preview(dialog, app, tmp_path, monkeypatch):
    check(dialog, app)
    paths(dialog, tmp_path)
    monkeypatch.setattr(
        dialog.service, "prepare", lambda *a, **k: (_ for _ in ()).throw(SnapshotChanged("private"))
    )
    assert dialog.prepare_copy()
    wait(app, lambda: not dialog.busy)
    assert dialog.preview is None and not dialog.prepare_button.isEnabled()
    assert "Check the coverage again" in dialog.status.text()


def test_cancelled_choosers_and_busy_owner_start_no_job(dialog, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    dialog.choose_output()
    dialog.choose_backup()
    assert not dialog.busy and not dialog.output_path.text() and not dialog.backup_path.text()
    dialog.writers_busy = lambda: True
    assert not dialog.check_content() and "current research jobs" in dialog.status.text()


def test_open_failure_is_retryable_without_repreparing(dialog, app, tmp_path):
    check(dialog, app)
    output, backup = paths(dialog, tmp_path)
    assert dialog.prepare_copy()
    wait(app, lambda: not dialog.busy)

    def fail(_):
        raise OSError("private open error")

    dialog._open_workspace = fail
    assert not dialog.open_copy() and dialog.open_button.isEnabled()
    assert "private open" not in dialog.status.text()
    dialog._open_workspace = dialog.opened.append
    assert dialog.open_copy() and len(dialog.opened) == 1 and output.exists() and backup.exists()


def test_workspace_entry_is_singleton_and_parent_close_waits_for_child(app, source, monkeypatch):
    window = WorkspaceDialog(source, language="en")
    window.show()
    wait(app, lambda: window._ready and not window.busy)
    try:
        window.enrollment_button.click()
        child = window._enrollment_dialog
        window._enrollment_settings()
        assert window._enrollment_dialog is child
        entered, release = threading.Event(), threading.Event()
        original = child.service.plan

        def held(*args, **kwargs):
            entered.set()
            assert release.wait(8)
            return original(*args, **kwargs)

        monkeypatch.setattr(child.service, "plan", held)
        assert child.check_content()
        wait(app, entered.is_set)
        assert not window.close() and not child.disposed
        release.set()
        wait(app, lambda: window.disposed and child.disposed)
    finally:
        if not window.disposed:
            window.close()


def test_bilingual_labels_are_real_unicode_and_compact_view_scrolls(dialog, app):
    assert COPY["zh-TW"]["title"] == "\u6e96\u5099\u5de5\u4f5c\u5340\u526f\u672c"
    assert "?" not in COPY["zh-TW"]["intro"]
    dialog.resize(440, 500)
    app.processEvents()
    assert dialog.width() <= 460
    assert dialog.progress.minimum() == dialog.progress.maximum() == 0
    assert dialog.coverage.isReadOnly()
    scroll = dialog.findChild(QScrollArea)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.widget().width() <= scroll.viewport().width()


def test_guard_rechecks_workspace_at_actual_publication_without_poll(
    dialog, app, tmp_path, monkeypatch
):
    check(dialog, app)
    output, backup = paths(dialog, tmp_path)
    active = [dialog.guard.path]
    dialog.guard.current_path = lambda: active[0]
    original = dialog.service.prepare

    def change_at_ready(*args, **kwargs):
        emit = kwargs["progress"]

        def change(message):
            if "ready for explicit review" in message:
                active[0] = tmp_path / "different-workspace.db"
            emit(message)

        return original(*args, **dict(kwargs, progress=change))

    monkeypatch.setattr(dialog.service, "prepare", change_at_ready)
    assert dialog.prepare_copy()
    wait(app, lambda: not dialog.busy)
    assert dialog._invalid and dialog.result is None
    assert not output.exists() and not backup.exists()


def test_native_database_replacement_during_pending_preview_needs_no_gc(
    dialog, app, source, tmp_path, monkeypatch
):
    import os
    import shutil

    entered, release = threading.Event(), threading.Event()
    original = dialog.service.plan

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "plan", held)
    assert dialog.check_content()
    wait(app, entered.is_set)
    replacement = tmp_path / "replacement.db"
    shutil.copy2(source, replacement)
    os.replace(replacement, source)
    dialog._check_source()
    release.set()
    wait(app, lambda: not dialog.busy)
    assert dialog._invalid and dialog.preview is None and dialog.result is None


def test_new_binding_during_pending_preview_is_not_rendered_ready(dialog, app, source, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.plan

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "plan", held)
    assert dialog.check_content()
    wait(app, entered.is_set)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE research_sync_binding(id INTEGER,workspace TEXT,origin TEXT)")
        conn.execute("INSERT INTO research_sync_binding VALUES(1,'changed','device')")
    release.set()
    wait(app, lambda: not dialog.busy)
    assert dialog._invalid and dialog.preview is None
    assert "workspace changed" in dialog.status.text()


def test_bound_source_is_not_materialized_for_first_enrollment(dialog, app, source, monkeypatch):
    from paper_daily.desktop import enrollment_dialog as module

    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE paperfact_sync_identity(id INTEGER,workspace TEXT,device TEXT)")
        conn.execute("INSERT INTO paperfact_sync_identity VALUES(1,'existing','device')")
    monkeypatch.setattr(
        module,
        "from_workspace",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Source cache must not be materialized")
        ),
    )
    plan = check(dialog, app)
    assert not plan["supported"] and not dialog.prepare_button.isEnabled()
    assert "paperfact_sync_identity" in dialog.coverage.toPlainText()


@pytest.mark.parametrize("target", ["existing", "source", "relative", "same_path"])
def test_invalid_output_paths_never_replace_source_or_existing_files(
    dialog, app, source, tmp_path, target
):
    check(dialog, app)
    before = source.read_bytes()
    output, backup = paths(dialog, tmp_path)
    if target == "existing":
        output.mkdir()
        (output / "keep.txt").write_text("keep")
    elif target == "source":
        dialog.output_path.setText(str(source.parent))
    elif target == "relative":
        dialog.output_path.setText("relative-copy")
    else:
        dialog.backup_path.setText(str(output))
    started = dialog.prepare_copy()
    if target == "relative":
        assert not started
    else:
        assert started
        wait(app, lambda: not dialog.busy)
    assert dialog.result is None and source.read_bytes() == before and not backup.exists()
    if target == "existing":
        assert (output / "keep.txt").read_text() == "keep"


def test_actual_imported_original_and_null_note_prepare_through_desktop(app, imported, tmp_path):
    from paper_daily import local_source_owners, source_provenance
    from paper_daily.sync_source_files import resolved

    database, _root, current_hash, original_hash, body = imported
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("UPDATE lists SET note=NULL")
    before = database.read_bytes()
    view = EnrollmentDialog(database, language="en", open_workspace=lambda _: None)
    try:
        plan = check(view, app)
        assert plan["supported"], plan["blockers"]
        assert plan["pdf_count"] == plan["imported_source_receipts"] == 1
        assert "Archived source receipts: 1" in view.coverage.toPlainText()
        output, backup = paths(view, tmp_path)
        assert view.prepare_copy()
        wait(app, lambda: not view.busy)
        assert view.result and backup.exists() and database.read_bytes() == before
        with closing(sqlite3.connect(output / "papers.db")) as conn:
            assert conn.execute("SELECT note FROM lists").fetchone()[0] is None
            assert not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name=?", (local_source_owners.TABLE,)
            ).fetchone()
            assert len(source_provenance.archived(conn)) == 1
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='ref:example'"
            ).fetchone()[0]
            assert resolved(conn, portable, original_hash).is_file()
            assert (
                json.loads(conn.execute("SELECT body_json FROM paper_claim_sets").fetchone()[0])
                == body
            )
        reader = DocumentReader.from_workspace(output / "papers.db")
        try:
            assert reader.resolve("ref:example").sha256 == current_hash
        finally:
            reader.close()
    finally:
        view.close()


def test_incomplete_binding_refuses_before_creating_worker(dialog, source):
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("CREATE TABLE paperfact_sync_identity(id INTEGER,workspace TEXT,device TEXT)")
    assert not dialog.check_content() and not dialog.busy
    assert dialog._invalid and dialog.preview is None


def test_old_worker_phase_signal_cannot_change_new_work_status(dialog, app, monkeypatch):
    check(dialog, app)
    old = object()
    entered, release = threading.Event(), threading.Event()
    original = dialog.service.plan

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(dialog.service, "plan", held)
    assert dialog.check_content()
    wait(app, entered.is_set)
    before = dialog.status.text()
    dialog._stage(old, "Creating independent backup")
    assert dialog.status.text() == before
    release.set()
    wait(app, lambda: not dialog.busy)


def test_invalid_folder_name_is_explained_without_work(dialog, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("../bad", True))
    dialog.choose_output()
    assert not dialog.output_path.text() and not dialog.busy
    assert dialog.status.text() == dialog.t["paths"]
