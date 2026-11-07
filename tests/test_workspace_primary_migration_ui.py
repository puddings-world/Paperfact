"""Actual contextual local-primary preparation, with isolated native workspaces."""

import hashlib
import inspect
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QPlainTextEdit, QWidget
from test_legacy_primary_migration import dump, pdf
from test_legacy_primary_migration import make as make_fixture
from test_workspace_dialog import app as app_fixture
from test_workspace_dialog import wait

from paper_daily import legacy_primary_migration, llm, store, updates
from paper_daily.desktop import main
from paper_daily.desktop.account_status import AccountStatus
from paper_daily.desktop.ai_dialog import AIStatusButton
from paper_daily.desktop.window_workspace import WindowWorkspace
from paper_daily.desktop.workspace_dialog import WorkspaceDialog
from paper_daily.document_reader import from_workspace
from paper_daily.sync_source_files import resolved
from paper_daily.workspace_primary_migration import MigrationSource

make = make_fixture

app = app_fixture


def test_actual_workspace_offers_contextual_local_pdf_review(make, app):

    fixture = make()

    pending = fixture.client.journal.pending()

    view = WorkspaceDialog(fixture.database, language="en")

    try:
        view.show()

        wait(app, lambda: view._ready and not view.busy)

        entry = getattr(view, "primary_migration", None)

        assert entry is not None, "Workspace/Backup has no explicit local-PDF migration action"

        assert "local PDF" in entry.review_button.text()

        assert not entry.review_button.isEnabled(), "Unowned caller must not stage local files"

        assert fixture.client.journal.pending() == pending

    finally:
        if view.busy:
            view.cancel()

            wait(app, lambda: not view.busy)

        view.close()


def forbid_new_gui_io(monkeypatch):
    gui = threading.get_ident()
    calls = []
    targets = (
        "/src/paper_daily/workspace_primary_migration.py",
        "/src/paper_daily/desktop/primary_migration_review.py",
        "/src/paper_daily/desktop/workspace_dialog.py",
    )

    def new_stack():
        frame = inspect.currentframe().f_back
        try:
            for _ in range(24):
                if frame is None:
                    break
                name = frame.f_code.co_filename.replace("\\", "/").lower()
                if name.endswith(targets) or (
                    name.endswith("/src/paper_daily/desktop/main.py")
                    and frame.f_code.co_name == "_workspace_settings"
                ):
                    return True
                frame = frame.f_back
            return False
        finally:
            del frame

    def guard(kind, actual):
        def checked(*args, **kwargs):
            if new_stack():
                ident = threading.get_ident()
                calls.append((kind, ident))
                assert ident != gui, "New migration SQL/hash executed on the GUI thread"
            return actual(*args, **kwargs)

        return checked

    monkeypatch.setattr(sqlite3, "connect", guard("sql", sqlite3.connect))
    monkeypatch.setattr(hashlib, "sha256", guard("hash", hashlib.sha256))
    return calls


@pytest.fixture
def native(make, app, monkeypatch):
    created = []

    def create(queried="A", *, actual_main=False, language="en"):
        fixture = make(queried)
        if actual_main:
            monkeypatch.setattr(main, "PDF_DIR", fixture.path.parent)
            monkeypatch.setattr(llm, "SETTINGS_PATH", fixture.root / "model.json")
            monkeypatch.setattr(llm, "settings", lambda *a, **k: llm.Settings("none"))
            monkeypatch.setattr(llm, "task_routes", lambda: {})
            monkeypatch.setattr(AccountStatus, "check", lambda *a, **k: None)
            monkeypatch.setattr(
                AIStatusButton, "refresh", lambda button: button.setText("AI fixture")
            )
            monkeypatch.setattr(main.ReaderPage, "_check_resources", lambda *_: None)
            monkeypatch.setattr(main.ReaderPage, "_prepare_reading_highlights", lambda *_: None)
            monkeypatch.setattr(updates, "check", lambda *a, **k: None)
            parent = main.MainWindow()
            parent.show()
            app.processEvents()
            parent.reader_page.note_edit.setPlainText("Keep unsent original note")
            parent.reader_page.ask_box.setText("Keep unsent original question")
            io = forbid_new_gui_io(monkeypatch)
            parent.workspace_action.trigger()
            view = parent._workspace_dialog
        else:
            parent = QWidget()
            parent._workspace_owner = WindowWorkspace.capture()
            parent.destroyed.connect(parent._workspace_owner.close)
            parent.draft = QPlainTextEdit(parent)
            parent.draft.setPlainText("Keep unsent original note and question")
            source = MigrationSource.capture(parent._workspace_owner, fixture.path.parent)
            io = forbid_new_gui_io(monkeypatch)
            view = WorkspaceDialog(
                fixture.database,
                parent,
                language=language,
                migration_source=source,
                current_path=lambda: store.DB_PATH,
            )
            view.show()
        created.append((view, parent, actual_main, fixture))
        wait(app, lambda: view._ready and not view.busy)
        assert view._primary_controller.source.owner is parent._workspace_owner
        assert view._primary_controller.source.legacy_root == fixture.path.parent
        assert view.primary_migration.review_button.isEnabled()
        return SimpleNamespace(view=view, parent=parent, fixture=fixture, io=io)

    yield create
    for view, parent, actual_main, fixture in reversed(created):
        monkeypatch.setattr(store, "DB_PATH", fixture.database)
        if view.busy:
            view.cancel()
            wait(app, lambda view=view: not view.busy, timeout=30)
        view.close()
        if actual_main:
            parent.reader_page.ask_box.clear()
            parent.reader_page.note_edit.clear()
        parent.close()
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def review_and_select(ui, app, identity="paper"):
    panel = ui.view.primary_migration
    panel.review_button.click()
    wait(app, lambda: not ui.view.busy)
    assert panel.catalog is not None and panel.table.topLevelItemCount() > 0
    item = next(
        panel.table.topLevelItem(i)
        for i in range(panel.table.topLevelItemCount())
        if panel.table.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == identity
    )
    panel.table.setCurrentItem(item)
    panel.table.setFocus()
    QTest.keyClick(panel.table, Qt.Key.Key_Space)
    assert item.checkState(0) == Qt.CheckState.Checked
    assert panel.stage_button.isEnabled()
    return panel


def stage_selected(ui, app):
    panel = review_and_select(ui, app)
    panel.stage_button.click()
    wait(app, lambda: not ui.view.busy)
    assert panel.plan is not None
    assert ui.fixture.document.sha256 in panel.summary.text()
    assert panel.commit_button.isEnabled()
    assert not ui.view.backup_button.isEnabled()
    return panel


def check_recovered(database, fixture):
    current = from_workspace(database).resolve("paper")
    assert current.available and current.managed
    assert current.sha256 == fixture.document.sha256
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM paper_later_outcomes").fetchone())
        assert row["body_json"] == fixture.recorded["body_json"]
        if fixture.original_bytes is None:
            assert row["document_hash"] is None
        else:
            portable = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id='paper'"
            ).fetchone()[0]
            assert (
                resolved(conn, portable, row["document_hash"]).read_bytes()
                == fixture.original_bytes
            )
            assert row["document_hash"] != current.sha256


@pytest.mark.parametrize("queried", ["A", "unavailable"])
def test_actual_buttons_prepare_review_backup_restore_and_editable_copy(
    native, app, tmp_path, monkeypatch, queried
):
    ui = native(queried)
    panel = stage_selected(ui, app)
    assert not any(
        op["entity_type"] == "paper_document" for op in ui.fixture.client.journal.pending()
    )
    panel.commit_button.click()
    wait(app, lambda: not ui.view.busy)
    assert "Prepared 1 PDFs; 0 remain." in panel.summary.text()
    assert "Backup not created." in ui.view.status.text()
    assert not list(tmp_path.glob("*.zip")) and not ui.view.backup_button.isEnabled()
    ui.view.refresh_button.click()
    wait(app, lambda: not ui.view.busy and ui.view._ready)
    assert ui.view.backup_button.isEnabled()
    archive = tmp_path / "new-backup.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(archive), ""))
    ui.view.backup_button.click()
    wait(app, lambda: not ui.view.busy, timeout=30)
    assert archive.is_file() and "Complete backup created" in ui.view.status.text()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(archive), ""))
    ui.view.inspect_button.click()
    wait(app, lambda: not ui.view.busy)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("detached", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    ui.view.restore_button.click()
    wait(app, lambda: not ui.view.busy, timeout=30)
    detached = tmp_path / "detached/papers.db"
    assert detached.is_file() and ui.view.service.path == ui.fixture.database
    ui.view.recovery_copy_button.click()
    child = ui.view._recovery_adoption_dialog
    assert child.source_field.text() == str(detached) and child.inspection is None
    child.inspect_button.click()
    wait(app, lambda: not child.busy, timeout=30)
    assert child.inspection.report["supported"]
    child.workspace_field.setText(str(tmp_path / "editable"))
    child.backup_field.setText(str(tmp_path / "editable.zip"))
    monkeypatch.setattr(child, "_confirm", lambda *_: True)
    child.prepare_button.click()
    wait(app, lambda: not child.busy, timeout=30)
    assert child.result and not child.result.get("uploaded", False)
    assert (tmp_path / "editable.zip").is_file()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(check_recovered, tmp_path / "editable/papers.db", ui.fixture).result(timeout=20)
    assert ui.parent.draft.toPlainText() == "Keep unsent original note and question"
    assert ui.fixture.path.read_bytes() == ui.fixture.bytes
    assert {kind for kind, _thread in ui.io} == {"sql", "hash"}


def test_actual_stage_and_commit_flood_have_one_worker_and_one_saved_receipt(
    native, app, monkeypatch
):
    ui = native()
    panel = review_and_select(ui, app)
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file
    calls = []

    def held(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        worker = ui.view._worker
        for _ in range(40):
            panel.stage_button.click()
            panel.review_button.click()
        assert ui.view._worker is worker and ui.view.busy and calls == [True]
    finally:
        release.set()
        wait(app, lambda: not ui.view.busy)
    assert panel.plan is not None
    for _ in range(40):
        panel.commit_button.click()
    wait(app, lambda: not ui.view.busy)
    with closing(sqlite3.connect(ui.fixture.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 1
    assert (
        sum(op["entity_type"] == "paper_document" for op in ui.fixture.client.journal.pending())
        == 1
    )


@pytest.mark.parametrize("action", ["cancel", "close"])
def test_actual_stage_cancel_or_close_drains_without_document_mutation(
    native, app, monkeypatch, action
):
    ui = native()
    panel = review_and_select(ui, app)
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file
    before = ui.fixture.client.journal.pending()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        if action == "close":
            assert not ui.view.close()
            assert not ui.view.disposed
        else:
            ui.view.cancel_button.click()
        assert ui.view.busy and ui.view._worker is not None
    finally:
        release.set()
        wait(app, lambda: not ui.view.busy)
    assert ui.fixture.client.journal.pending() == before
    assert ui.fixture.path.read_bytes() == ui.fixture.bytes
    assert ui.parent.draft.toPlainText() == "Keep unsent original note and question"
    assert panel.plan is None
    assert ui.view.disposed == (action == "close")


@pytest.mark.parametrize("change", ["source", "workspace"])
def test_queued_staging_delivery_rejects_changed_source_or_workspace(
    native, app, monkeypatch, tmp_path, change
):
    ui = native()
    panel = review_and_select(ui, app)
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file
    before = ui.fixture.client.journal.pending()

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        worker = ui.view._worker
        release.set()
        assert worker.wait(5000)
        assert ui.view.busy and panel.plan is None
        if change == "source":
            pdf(ui.fixture.path, "Different actual PDF after completed staging")
        else:
            foreign = tmp_path / "next.db"
            with closing(sqlite3.connect(foreign)) as conn, conn:
                conn.execute("CREATE TABLE marker(value)")
                conn.execute("INSERT INTO marker VALUES('untouched')")
            foreign_before = foreign.read_bytes()
            monkeypatch.setattr(store, "DB_PATH", foreign)
        wait(app, lambda: not ui.view.busy)
        assert panel.plan is None and not panel.commit_button.isEnabled()
        assert ui.fixture.client.journal.pending() == before
        if change == "workspace":
            assert foreign.read_bytes() == foreign_before
            replacement = foreign.with_suffix(".replacement")
            replacement.write_bytes(foreign_before)
            os.replace(replacement, foreign)
            assert foreign.read_bytes() == foreign_before
    finally:
        release.set()
        if ui.view.busy:
            wait(app, lambda: not ui.view.busy)


@pytest.mark.parametrize("action", ["restart", "update", "verified", "close"])
def test_actual_main_entry_keeps_worker_owned_before_restart_update_or_close(
    native, app, monkeypatch, tmp_path, action
):
    ui = native(actual_main=True)
    panel = review_and_select(ui, app)
    assert ui.view._primary_controller.source.owner is ui.parent._workspace_owner
    assert ui.view._primary_controller.source.legacy_root == main.PDF_DIR
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file
    launched = []

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    monkeypatch.setattr(updates, "launch_installer", launched.append)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        worker = ui.view._worker
        if action != "restart":
            ui.view.hide()
        if action == "verified":
            banner = ui.parent.update_banner
            banner.release = updates.Release(
                "9.9.9", "Fixture", "", "https://fixture.invalid/release", {}
            )
            banner._ready = tmp_path / "synthetic-installer.exe"
            banner._ready.write_bytes(b"synthetic; never executed")
            banner._verified()
            assert not banner._installing
        elif action == "close":
            assert not ui.parent.close()
        elif action == "restart":
            assert not ui.parent._prepare_restart()
        else:
            assert not ui.parent._prepare_update()
        assert not launched and ui.view.busy and ui.view._worker is worker
        assert not ui.view.disposed and not ui.parent.workspace_changes.disposed
        assert ui.parent.reader_page.note_edit.toPlainText() == "Keep unsent original note"
        assert ui.parent.reader_page.ask_box.text() == "Keep unsent original question"
    finally:
        release.set()
        wait(app, lambda: not ui.view.busy)
    assert ui.parent.reader_page.note_edit.toPlainText() == "Keep unsent original note"
    assert ui.parent.reader_page.ask_box.text() == "Keep unsent original question"
    assert not launched


def test_small_native_staging_review_keeps_full_source_and_actions_reachable(native, app):
    ui = native(language="zh-TW")
    panel = stage_selected(ui, app)
    ui.view.resize(440, 520)
    app.processEvents()
    assert chr(27298) + chr(26597) in panel.review_button.text()
    assert ui.fixture.document.sha256 in panel.summary.text()
    assert ui.view.scroll.horizontalScrollBar().maximum() == 0
    assert panel.summary.sizePolicy().hasHeightForWidth()
    assert panel.summary.height() >= panel.summary.heightForWidth(panel.summary.width())
    ui.view.scroll.ensureWidgetVisible(panel.commit_button)
    app.processEvents()
    assert panel.commit_button.isVisible() and panel.commit_button.isEnabled()
    assert ui.view.rect().contains(ui.view.cancel_button.geometry())
    assert ui.view.rect().contains(ui.view.close_button.geometry())


def test_actual_staging_failure_then_explicit_refresh_retry_has_one_saved_result(
    native, app, monkeypatch
):
    ui = native()
    panel = review_and_select(ui, app)
    actual = legacy_primary_migration.stage_file
    before = ui.fixture.client.journal.pending()
    monkeypatch.setattr(
        legacy_primary_migration,
        "stage_file",
        lambda *a, **k: (_ for _ in ()).throw(OSError("private-fixture-body")),
    )
    panel.stage_button.click()
    wait(app, lambda: not ui.view.busy)
    assert panel.plan is None and "private-fixture-body" not in ui.view.status.text()
    assert ui.fixture.client.journal.pending() == before
    assert ui.fixture.path.read_bytes() == ui.fixture.bytes
    monkeypatch.setattr(legacy_primary_migration, "stage_file", actual)
    ui.view.refresh_button.click()
    wait(app, lambda: not ui.view.busy and ui.view._ready)
    panel = stage_selected(ui, app)
    panel.commit_button.click()
    wait(app, lambda: not ui.view.busy)
    with closing(sqlite3.connect(ui.fixture.database)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_action_receipts").fetchone()[0] == 1


def test_account_configuration_changes_cannot_reroute_local_staging(
    native, app, monkeypatch, tmp_path
):
    ui = native()
    panel = review_and_select(ui, app)
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    def no_account(*args, **kwargs):
        raise AssertionError("Local migration attempted account/model route capture")

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        monkeypatch.setattr(llm, "SETTINGS_PATH", tmp_path / "different-account.json")
        monkeypatch.setattr(llm, "settings", no_account)
        monkeypatch.setattr(llm, "task_routes", no_account)
    finally:
        release.set()
        wait(app, lambda: not ui.view.busy)
    assert panel.plan is not None
    panel.commit_button.click()
    wait(app, lambda: not ui.view.busy)
    assert "Prepared 1 PDFs; 0 remain." in panel.summary.text()
    assert ui.fixture.path.read_bytes() == ui.fixture.bytes


def test_paper_update_while_staging_is_preserved_and_no_old_source_is_published(
    native, app, monkeypatch
):
    ui = native()
    panel = review_and_select(ui, app)
    entered, release = threading.Event(), threading.Event()
    actual = legacy_primary_migration.stage_file

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(8)
        return actual(*args, **kwargs)

    monkeypatch.setattr(legacy_primary_migration, "stage_file", held)
    try:
        panel.stage_button.click()
        wait(app, entered.is_set)
        with store.connect() as conn:
            conn.execute("UPDATE papers SET title='New current title' WHERE id='paper'")
        actor_state = dump(ui.fixture.database)
    finally:
        release.set()
        wait(app, lambda: not ui.view.busy)
    assert panel.plan is None and dump(ui.fixture.database) == actor_state
    assert not any(
        op["entity_type"] == "paper_document" for op in ui.fixture.client.journal.pending()
    )
    assert ui.parent.draft.toPlainText() == "Keep unsent original note and question"
