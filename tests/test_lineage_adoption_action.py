"""Actual saved Lineage actions verify PDFs before separate explicit sync admission."""

from threading import Event

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog
from test_lineage_direct_adoption import selected as selected
from test_lineage_import_review import corpus as corpus
from test_lineage_import_review import dump
from test_lineage_import_review import native_shared as native_shared
from test_lineage_import_review import shared as shared
from test_lineage_jobs import routes
from test_lineage_matching_adoption import legacy as legacy
from test_sync_files import codec as codec
from test_sync_files import pair as pair
from test_workspace_dialog import wait

from paper_daily import ai_choices, lineage_sets, llm
from paper_daily import research_generation as generation
from paper_daily.desktop.lineage_dialog import LineageDialog
from paper_daily.lineage_direct_adoption import DirectAdoption
from paper_daily.manual_highlight_ops import observe_owner


@pytest.fixture
def scene(selected, monkeypatch):
    app = QApplication.instance() or QApplication([])
    service, paths, row, client = selected
    configured = routes()
    monkeypatch.setattr(llm, "settings", lambda *_a, **_k: configured.settings("lineage"))
    monkeypatch.setattr(ai_choices, "connection_label", lambda *_a, **_k: "Fixture AI")
    owner = observe_owner(
        client.journal.path,
        row["paper_id"],
        expected_native=generation._identity(client.journal.path),
    )
    current = ["fixture-view"]
    dialog = LineageDialog(
        client.journal.path,
        row["paper_id"],
        owner=owner,
        document=None,
        legacy_root=client.journal.path.parent / "pdf",
        current_view=lambda: current[0],
        language="en",
    )
    dialog.show()
    wait(app, lambda: not dialog.busy and bool(dialog.saved), timeout=20)
    index = next(
        i for i, saved in enumerate(dialog.saved) if saved["corpus_key"] == row["corpus_key"]
    )
    dialog.results.setCurrentIndex(index)
    app.processEvents()
    yield app, dialog, current
    if dialog.busy:
        dialog.cancel()
        wait(app, lambda: not dialog.busy, timeout=20)
    dialog.close()
    dialog.deleteLater()


def choose(monkeypatch, selected):
    _service, paths, row, _client = selected
    sequence = iter(
        [
            paths[source["id"]]
            for source in lineage_sets.decode(row["body_json"])["report"]["sources"]
            if source["availability"] == "available"
        ]
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(next(sequence)), ""))


def test_picker_cancellation_and_verified_preview_do_not_apply_until_second_click(
    scene, selected, monkeypatch
):
    app, dialog, _current = scene
    action, client, row = dialog.adoption, selected[3], selected[2]
    assert action.button.isEnabled() and action.isVisible()
    before = dump(client)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    assert not action.start() and not dialog.busy and dump(client) == before
    choose(monkeypatch, selected)
    assert action.start() and not action.start()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert action.plan is not None and "Confirm inclusion" in action.button.text()
    assert "Science/model records stay unchanged" in dialog.status.text()
    assert dump(client) == before
    assert action.start() and not action.start()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.status.text() == dialog.t["queued_sync"]
    assert row in lineage_sets.saved(client.journal.path, row["paper_id"])
    assert not action.start() and not action.isVisible()
    assert dialog.refresh()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert not action.isVisible()


@pytest.mark.parametrize("action_kind", ["cancel", "close", "switch"])
def test_pending_direct_verification_drains_without_native_adoption(
    scene, selected, monkeypatch, action_kind
):
    app, dialog, current = scene
    entered, release = Event(), Event()
    original = DirectAdoption.prepare

    def held(self, *args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DirectAdoption, "prepare", held)
    choose(monkeypatch, selected)
    before = dump(selected[3])
    assert dialog.adoption.start() and entered.wait(3)
    try:
        if action_kind == "cancel":
            dialog.cancel()
        elif action_kind == "close":
            assert not dialog.close()
        else:
            current[0] = "another-paper-view"
            dialog._check()
    finally:
        release.set()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.adoption.plan is None and dump(selected[3]) == before
    if action_kind == "close":
        assert dialog.disposed


def test_bad_pdf_selection_keeps_science_and_allows_retry(scene, selected, monkeypatch, tmp_path):
    app, dialog, _current = scene
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"wrong original")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(invalid), ""))
    before = dump(selected[3])
    assert dialog.adoption.start()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.adoption.plan is None and "Could not verify" in dialog.status.text()
    assert dump(selected[3]) == before
    choose(monkeypatch, selected)
    assert dialog.adoption.start()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.adoption.plan is not None
    dialog.adoption.reset_button.click()
    assert dialog.adoption.plan is None and not dialog.adoption.reset_button.isVisible()
    assert dump(selected[3]) == before


@pytest.mark.parametrize("action_kind", ["close", "switch"])
def test_pending_explicit_apply_can_be_cancelled_without_adopting(
    scene, selected, monkeypatch, action_kind
):
    app, dialog, current = scene
    choose(monkeypatch, selected)
    assert dialog.adoption.start()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.adoption.plan is not None
    entered, release = Event(), Event()
    original = DirectAdoption.apply

    def held(self, *args, **kwargs):
        entered.set()
        assert release.wait(8)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DirectAdoption, "apply", held)
    before = dump(selected[3])
    assert dialog.adoption.start() and entered.wait(3)
    try:
        if action_kind == "close":
            assert not dialog.close()
        else:
            current[0] = "changed-before-commit"
            dialog._check()
    finally:
        release.set()
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dump(selected[3]) == before


def test_changed_saved_row_between_worker_and_gui_delivery_requires_refresh(
    scene, selected, monkeypatch
):
    from paper_daily import sync_capture

    app, dialog, _current = scene
    choose(monkeypatch, selected)
    assert dialog.adoption.start()
    worker = dialog._worker
    assert worker.wait(12000)
    assert dialog.adoption.plan is None
    with selected[3].journal.transaction() as conn, sync_capture.suppress_capture(conn):
        conn.execute(
            "UPDATE paper_lineage_sets SET written_at=? WHERE corpus_key=?",
            ("2026-11-10T00:00:00+00:00", selected[2]["corpus_key"]),
        )
    changed = dump(selected[3])
    wait(app, lambda: not dialog.busy, timeout=20)
    assert dialog.adoption.plan is None and dialog._needs_refresh
    assert dialog.status.text() == dialog.t["refresh_needed"]
    assert dump(selected[3]) == changed
