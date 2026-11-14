"""Imported research packages open their own exact originals in the real desktop."""

import hashlib
import os
import sqlite3
import threading
import time
from contextlib import closing

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from lineage_package_fixture import lineage_archive as lineage_archive
from PySide6.QtWidgets import QApplication
from test_lineage_import_originals import loaded as loaded
from test_lineage_jobs import work
from test_lineage_package_publish import incoming as incoming

from paper_daily import (
    lineage_bound_originals,
    lineage_import_originals,
    lineage_originals,
    lineage_packages,
    lineage_sets,
    llm,
)
from paper_daily.ai_types import Settings
from paper_daily.desktop.lineage_dialog import LineageDialog


def until(app, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def scene(loaded, monkeypatch):
    app = QApplication.instance() or QApplication([])
    incoming, owner, row = loaded
    monkeypatch.setattr(llm, "settings", lambda *_a, **_k: Settings("none"))
    dialog = LineageDialog(
        incoming[0],
        owner.paper_id,
        owner=owner,
        document=None,
        legacy_root=incoming[0].parent / "pdf",
        current_view=lambda: "imported-paper",
        language="en",
    )
    dialog.show()
    until(app, lambda: not dialog.busy and bool(dialog.saved))
    yield app, dialog, owner, row
    if dialog.busy:
        dialog.cancel()
        until(app, lambda: not dialog.busy)
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("index", [0, 1, 2])
def test_imported_focal_and_peer_originals_display_exact_bytes_without_ai_or_new_grants(
    scene, loaded, index
):
    app, dialog, _owner, row = scene
    incoming = loaded[0]
    before = incoming[0].read_bytes()
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][index]
    assert dialog.open_source(row, source["id"])
    assert not dialog.open_source(row, source["id"])
    until(app, lambda: not dialog.busy)
    viewer = dialog._original_viewer
    assert viewer is not None and not viewer.disposed
    assert hashlib.sha256(bytes(viewer.buffer.data())).hexdigest() == source["document_hash"]
    assert viewer.document.pageCount() >= 1 and dialog.document is None
    assert incoming[0].read_bytes() == before


@pytest.mark.parametrize("failure", ["association", "receipt"])
def test_invalid_import_proof_never_tries_another_reader_or_grants_sources(
    scene, loaded, monkeypatch, failure
):
    app, dialog, _owner, row = scene
    incoming = loaded[0]
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    with closing(sqlite3.connect(incoming[0])) as conn, conn:
        if failure == "association":
            conn.execute(
                "DELETE FROM research_local_source_owners WHERE sha256=?",
                (source["document_hash"],),
            )
        else:
            conn.execute("UPDATE research_lineage_imports SET body_json='{}'")
    before = incoming[0].read_bytes()
    fallback = []

    def forbidden(*_a, **_k):
        fallback.append(True)
        return None

    monkeypatch.setattr(lineage_originals, "prepare", forbidden)
    monkeypatch.setattr(lineage_bound_originals, "prepare", forbidden)
    assert dialog.open_source(row, source["id"])
    until(app, lambda: not dialog.busy)
    assert dialog._original_viewer is None and fallback == []
    assert dialog.status.text() == dialog.t["source_unavailable"]
    with pytest.raises(ValueError):
        work(lineage_packages.collect, incoming[0], [row["paper_id"]])
    assert fallback == []
    assert lineage_sets.saved(incoming[0], row["paper_id"]) == [row]
    assert incoming[0].read_bytes() == before


@pytest.mark.parametrize("change", ["cancel", "view"])
def test_delayed_import_original_read_cannot_open_after_cancel_or_view_change(
    scene, loaded, monkeypatch, change
):
    app, dialog, _owner, row = scene
    incoming = loaded[0]
    source = lineage_sets.decode(row["body_json"])["report"]["sources"][0]
    before = incoming[0].read_bytes()
    entered, release = threading.Event(), threading.Event()
    original = lineage_import_originals.prepare
    calls = []

    def held(*args, **options):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        return original(*args, **options)

    monkeypatch.setattr(lineage_import_originals, "prepare", held)
    assert dialog.open_source(row, source["id"])
    until(app, entered.is_set)
    try:
        if change == "view":
            dialog.current_view = lambda: "another-paper"
            assert not dialog._check()
        else:
            dialog.cancel()
            dialog.cancel()
    finally:
        release.set()
    until(app, lambda: not dialog.busy)
    assert dialog._original_viewer is None and len(calls) == 1
    assert incoming[0].read_bytes() == before
