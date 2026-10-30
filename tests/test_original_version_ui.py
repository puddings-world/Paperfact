"""Historical original A is inspected separately without replacing current B."""

import hashlib
import os
import threading
from contextlib import closing
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtCore import QThread
from test_claim_evidence_ui import claims as claims_fixture
from test_claim_evidence_ui import generate, wait
from test_claim_evidence_ui import view as view_fixture
from test_highlight_generation import ready as ready_fixture
from test_research_generation import pdf, rows
from test_research_generation import workspace as workspace_fixture

from paper_daily import annotation_reader, llm, manual_highlight_ops, sync_capture
from paper_daily import research_generation as generation
from paper_daily.desktop import original_version
from paper_daily.desktop.claim_evidence import TEXT, ClaimEvidenceDialog
from paper_daily.document_reader import from_workspace


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    return workspace_fixture.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param=True))


@pytest.fixture
def ready(workspace, monkeypatch):
    value = ready_fixture.__wrapped__(workspace, monkeypatch)
    with pymupdf.open(value[2].path) as document:
        document.new_page().insert_text((40, 50), "Second original page: limitations of source A")
        data = document.tobytes()
    value[2].path.write_bytes(data)
    resolved = from_workspace(value[0], legacy_root=value[2].path.parent).resolve("paper")
    return (*value[:2], resolved, *value[3:])


claims = claims_fixture
view = view_fixture


@pytest.fixture
def historical(view):
    generate(view)
    saved = view.d.saved
    source_hash = saved["document_hash"]
    view.d.close()
    pdf(view.ready[2].path, "Current primary B must remain in the original reader")
    current = from_workspace(view.ready[0], legacy_root=view.ready[2].path.parent).resolve("paper")
    owner = manual_highlight_ops.capture_owner(view.ready[0], "paper")
    view.active[:] = [view.ready[0], "paper", 2, current]
    dialog = ClaimEvidenceDialog(
        view.ready[0],
        "paper",
        view.parent,
        legacy_root=current.path.parent,
        current_path=lambda: view.active[0],
        current_view=lambda: tuple(view.active),
        document=current,
        owner=owner,
        source_callback=lambda source: view.jumps.append(source),
        language="en",
    )
    dialog.show()
    wait(view.app, lambda: not dialog.busy and dialog.saved is not None)
    assert dialog.saved == saved and current.sha256 != source_hash
    view.d = dialog
    view.source_hash = source_hash
    view.current = current
    yield view
    dialog.close()
    wait(view.app, lambda: dialog.disposed)
    dialog.deleteLater()
    view.app.processEvents()


def open_original(view):
    assert view.d.open_original()
    wait(view.app, lambda: not view.d.busy)
    assert view.d._original_viewer is not None, (view.d.status.text(), view.d.last_error)
    viewer = view.d._original_viewer
    wait(
        view.app,
        lambda: (
            viewer.disposed
            or (viewer.native and viewer.pdf.pageCount() > 0)
            or (not viewer.native and viewer._rendered_page >= 0)
        ),
    )
    assert not viewer.disposed
    return viewer


def business(database):
    return {
        table: rows(database, f"SELECT * FROM {table}")
        for table in (
            "paper_claim_sets",
            "pdf_highlights",
            "pdf_ai_highlights",
            "notes",
            "research_file_desired",
            "research_file_applied",
            "research_generation_requests",
            "paperfact_sync_operations",
        )
    }


def forbidden(*_args, **_kwargs):
    pytest.fail("Opening original source accessed AI accounts or models")


def test_actual_original_bytes_open_from_pending_desired_without_auth_or_primary_switch(
    historical, monkeypatch
):
    h = historical
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    before, loaded = business(h.ready[0]), h.current.path.read_bytes()
    parsed_threads = []
    parse = original_version.pymupdf.open

    def opened(*args, **kwargs):
        parsed_threads.append(QThread.currentThread() != h.app.thread())
        return parse(*args, **kwargs)

    monkeypatch.setattr(original_version.pymupdf, "open", opened)
    assert h.d.original_button.isVisible()
    assert not any(button.isEnabled() for button in h.d.source_buttons)
    viewer = open_original(h)
    assert viewer.snapshot.document_hash == h.source_hash
    assert hashlib.sha256(viewer.snapshot.data).hexdigest() == h.source_hash
    assert viewer.snapshot.source.suffix != ".pdf"
    assert viewer.snapshot.pages == 2 and all(parsed_threads)
    assert viewer.native == original_version.HAVE_QTPDF
    if viewer.native:
        assert "independent observations" in viewer.pdf.getAllText(0).text()
    else:
        assert viewer.image.pixmap() is not None
    viewer.page.setValue(2)
    if viewer.native:
        assert viewer.view.pageNavigator().currentPage() == 1
    else:
        wait(h.app, lambda: not viewer.busy and viewer._rendered_page == 1)
    viewer.zoom.setCurrentIndex(2)
    if viewer.native:
        assert viewer.view.zoomFactor() == 1.25
    assert not hasattr(viewer.view, "selection")
    assert h.current.path.read_bytes() == loaded and h.d.document is h.current
    assert business(h.ready[0]) == before and len(h.claims[2]) == 1
    assert h.question.text() == "Unsent question" and h.note.toPlainText() == "Unsent notes"
    assert not h.jumps


def test_repeated_open_reuses_one_read_only_window_and_keeps_current_jump_disabled(historical):
    h = historical
    viewer = open_original(h)
    for _ in range(20):
        assert not h.d.open_original()
    assert h.d._original_viewer is viewer and len(h.claims[2]) == 1
    passage = h.d.saved["report"]["claims"][0]["passages"][0]
    assert h.d.open_source(passage)
    wait(h.app, lambda: not h.d.busy)
    assert not h.jumps and h.d._original_viewer is viewer


def test_missing_or_damaged_original_never_falls_back_to_current_pdf_and_can_retry(historical):
    h = historical
    viewer = open_original(h)
    path, original = viewer.snapshot.source, viewer.snapshot.data
    viewer.close()
    path.unlink()
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and h.d.status.text() in {
        TEXT["en"]["original_unavailable"],
        TEXT["en"]["original_failed"],
    }
    assert h.current.sha256 != h.source_hash and not h.jumps
    path.write_bytes(b"not the stored original")
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None
    path.write_bytes(original)
    assert open_original(h).snapshot.document_hash == h.source_hash
    assert len(h.claims[2]) == 1


@pytest.mark.parametrize("changed", ["paper", "workspace", "cancel", "close"])
def test_pending_prepare_rejects_late_open_on_switch_cancel_or_close(
    historical, monkeypatch, changed
):
    h = historical
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare", blocked)
    assert h.d.open_original() and not h.d.open_original()
    wait(h.app, entered.is_set)
    if changed == "paper":
        h.active[1] = "another-paper"
        h.d._check()
    elif changed == "workspace":
        h.active[0] = h.ready[0].with_name("another.sqlite")
        h.d._check()
    elif changed == "cancel":
        h.d.cancel()
    else:
        assert not h.d.close()
    release.set()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and not h.jumps
    assert h.question.text() == "Unsent question" and h.note.toPlainText() == "Unsent notes"


def test_metadata_changed_after_worker_verification_is_rejected_before_gui_open(
    historical, monkeypatch
):
    h = historical
    prepare = original_version.prepare

    def late(*args, **kwargs):
        snapshot = prepare(*args, **kwargs)
        with closing(generation._connect(h.ready[0])) as conn:
            observed = sync_capture.observe_target(conn, "paper", "paper", "claims")
            with sync_capture.expecting(conn, [observed]):
                conn.execute("DELETE FROM paper_claim_sets WHERE paper_id='paper'")
                conn.commit()
        return snapshot

    monkeypatch.setattr(original_version, "prepare", late)
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and not h.jumps
    assert annotation_reader.saved(h.ready[0], "paper", "claims") == {"claims": [], "known": True}


def test_mutation_with_restored_mtime_invalidates_open_snapshot_without_rewriting_current(
    historical,
):
    h = historical
    viewer = open_original(h)
    before = h.current.path.read_bytes()
    path = viewer.snapshot.source
    stat = path.stat()
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    viewer.check()
    wait(h.app, lambda: viewer.disposed)
    assert h.d._original_viewer is None and h.current.path.read_bytes() == before
    assert h.d.status.text() == TEXT["en"]["original_changed"]


def test_fallback_arrows_coalesce_and_parent_close_waits_for_active_render(historical, monkeypatch):
    h = historical
    factory = original_version.OriginalVersionDialog
    monkeypatch.setattr(
        original_version,
        "OriginalVersionDialog",
        lambda *args, **kwargs: factory(*args, **kwargs, native=False),
    )
    entered, release = threading.Event(), threading.Event()
    render = original_version.render_page
    calls = []

    def blocked(snapshot, page, cancelled):
        calls.append((page, QThread.currentThread() != h.app.thread()))
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return render(snapshot, page, cancelled)

    monkeypatch.setattr(original_version, "render_page", blocked)
    assert h.d.open_original()
    wait(h.app, entered.is_set)
    viewer = h.d._original_viewer
    for _ in range(10):
        viewer.page.setValue(2)
        viewer.page.setValue(1)
    viewer.page.setValue(2)
    release.set()
    wait(h.app, lambda: not viewer.busy and viewer._rendered_page == 1)
    assert calls == [(0, True), (1, True)]
    assert viewer.image.pixmap() is not None
    entered.clear()
    release.clear()

    def closing(snapshot, page, cancelled):
        entered.set()
        assert release.wait(10)
        return render(snapshot, page, cancelled)

    monkeypatch.setattr(original_version, "render_page", closing)
    viewer.page.setValue(1)
    wait(h.app, entered.is_set)
    assert not h.d.close() and not h.d.disposed
    release.set()
    wait(h.app, lambda: h.d.disposed)
    assert viewer.disposed and viewer.snapshot is None
    assert h.question.text() == "Unsent question" and h.note.toPlainText() == "Unsent notes"


def test_late_source_retirement_rejects_an_already_prepared_snapshot(historical, monkeypatch):
    from paper_daily.sync_files import file_id

    h = historical
    prepare = original_version.prepare

    def retired(*args, **kwargs):
        snapshot = prepare(*args, **kwargs)
        client = h.ready[1]
        identity = file_id(snapshot.portable_id, "original_source", snapshot.document_hash)
        client.save(client.new_graph_operation("research_file", identity, {}, action="delete"))
        return snapshot

    monkeypatch.setattr(original_version, "prepare", retired)
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and h.d.document is h.current and not h.jumps
    assert h.d.saved["report"] and len(h.claims[2]) == 1


def test_deleted_recreated_local_owner_cannot_open_an_old_prepared_source(historical, monkeypatch):
    from paper_daily import store

    h = historical
    prepare = original_version.prepare

    errors = []

    def recreated(*args, **kwargs):
        snapshot = prepare(*args, **kwargs)
        try:
            return recreate(snapshot)
        except Exception as error:
            errors.append((type(error).__name__, str(error)))
            raise

    def recreate(snapshot):
        with (
            closing(generation._connect(h.ready[0])) as conn,
            conn,
            sync_capture.suppress_capture(conn),
        ):
            old = dict(conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone())
            old.update(title="Recreated owner", title_key=store.title_key("Recreated owner"))
            conn.execute("DELETE FROM papers WHERE id='paper'")
            store.upsert_papers(conn, [old])
            conn.commit()
        return snapshot

    monkeypatch.setattr(original_version, "prepare", recreated)
    assert h.d.open_original()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is None and not h.jumps
    assert not errors, errors
    assert rows(h.ready[0], "SELECT title FROM papers") == [{"title": "Recreated owner"}]


def test_account_switch_during_prepare_never_reads_ai_routing(historical, monkeypatch):
    h = historical
    entered, release = threading.Event(), threading.Event()
    prepare = original_version.prepare

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(original_version, "prepare", blocked)
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(llm, "settings", forbidden)
    assert h.d.open_original()
    wait(h.app, entered.is_set)
    h.ready[3].update(account="new-account", model="new-model")
    release.set()
    wait(h.app, lambda: not h.d.busy)
    assert h.d._original_viewer is not None and len(h.claims[2]) == 1


def test_private_unbound_pin_stays_unavailable_without_identity_creation_or_ai(
    tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QApplication, QWidget

    from paper_daily.claim_jobs import ClaimJob

    workspace = workspace_fixture.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param=False))
    ready = ready_fixture.__wrapped__(workspace, monkeypatch)
    claims = claims_fixture.__wrapped__(ready, monkeypatch)
    owner = manual_highlight_ops.capture_owner(ready[0], "paper")
    job = ClaimJob.capture(
        ready[0], "paper", legacy_root=ready[2].path.parent, document=ready[2], owner=owner
    )
    assert job.run().status == "accepted"
    pdf(ready[2].path, "Current B for an unenrolled local workspace")
    current = from_workspace(ready[0], legacy_root=ready[2].path.parent).resolve("paper")
    app, parent = QApplication.instance() or QApplication([]), QWidget()
    dialog = ClaimEvidenceDialog(
        ready[0],
        "paper",
        parent,
        legacy_root=current.path.parent,
        owner=owner,
        document=current,
        language="en",
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and dialog.saved is not None)
    before = rows(ready[0], "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    monkeypatch.setattr(llm, "capture_connections", forbidden)
    monkeypatch.setattr(llm, "complete_result", forbidden)
    try:
        assert dialog.open_original()
        wait(app, lambda: not dialog.busy)
        assert dialog._original_viewer is None
        assert dialog.status.text() == TEXT["en"]["original_unavailable"]
        assert (
            rows(ready[0], "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            == before
        )
        assert len(claims[2]) == 1 and dialog.saved["report"]
    finally:
        dialog.close()
        dialog.deleteLater()
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_unsealed_snapshot_cannot_grant_original_display_authority():
    assert not original_version.metadata_current(object.__new__(original_version.OriginalSnapshot))


def test_original_action_is_available_after_current_reader_source_proof_fails(view):
    generate(view)
    assert not view.d.original_button.isVisible()
    pdf(view.ready[2].path, "Externally replaced current file B")
    current_bytes = view.ready[2].path.read_bytes()
    passage = view.d.saved["report"]["claims"][0]["passages"][0]
    assert view.d.open_source(passage)
    wait(view.app, lambda: not view.d.busy)
    assert not view.jumps and view.d.original_button.isVisible()
    viewer = open_original(view)
    assert viewer.snapshot.document_hash == view.d.saved["document_hash"]
    assert view.ready[2].path.read_bytes() == current_bytes and len(view.claims[2]) == 1
    viewer.close()
