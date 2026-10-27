"""Restored saved slides open through the ordinary app reader and exporters."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

import pytest
from test_slide_revision_recovery import add_source, archive
from test_slide_revision_recovery import revision as revision_fixture
from test_sync_files import LOCAL, PAPER, png
from test_sync_files import codec as codec_fixture
from test_sync_files import pair as pair_fixture

from paper_daily import (
    llm,
    presentation_export,
    presentations,
    recovery_decks,
    slide_revise,
    slide_revision,
    store,
    sync_recovery,
)
from paper_daily.ai_types import Completion

revision = revision_fixture
codec = codec_fixture
pair = pair_fixture
NORMAL_FIGURE = presentations.figure_bytes


def restore_current(revision, tmp_path, monkeypatch):
    destination = tmp_path / "detached"
    sync_recovery.restore_detached(archive(revision, tmp_path), destination)
    monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
    monkeypatch.setattr(presentations, "DECK_DIR", destination / "presentations")
    monkeypatch.setattr(presentations, "figure_bytes", NORMAL_FIGURE)
    monkeypatch.setattr(
        presentations, "collect_evidence", lambda *a, **k: pytest.fail("fresh evidence")
    )
    return destination


@pytest.mark.parametrize("known", [False, True])
def test_restore_normal_open_evidence_and_export_preserve_business_content(
    revision, tmp_path, monkeypatch, known
):
    value = revision[2]
    if known:
        value.source_hash = "a" * 64
    presentations.save_deck(
        value, evidence={"sources": value.sources, "coverage": [], "source_hash": value.source_hash}
    )
    before = presentations.load_deck(LOCAL, "guide")
    destination = restore_current(revision, tmp_path, monkeypatch)
    database = destination / "papers.db"
    contents = database.read_bytes()
    for _ in range(3):
        deck = presentations.load_deck(LOCAL, "guide")
        assert deck.to_dict() == before.to_dict()
        assert slide_revise.evidence(deck)["source_hash"] == before.source_hash
        assert NORMAL_FIGURE(deck, "figure:1") == png("red")
        exported = presentation_export.render_html(deck)
        assert "data:image/png;base64," in exported and "Speaker explanation" in exported
        assert recovery_decks.document_status(deck)["input_digest_known"] is known
        assert deck._recovery_capabilities["publish"] is False
    assert database.read_bytes() == contents
    with closing(sqlite3.connect(database)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert not tables & {
        "paperfact_sync_identity",
        "research_sync_binding",
        "research_file_desired",
    }
    assert not list(destination.rglob(".revision-requests"))
    with pytest.raises(ValueError, match="read-only"):
        presentations.save_deck(deck)
    with pytest.raises(ValueError, match="read-only"):
        slide_revision.begin(deck, 0, "This must not start a job")
    assert not list(destination.rglob(".revision-requests"))
    monkeypatch.setattr(llm, "complete_result", lambda *a, **k: pytest.fail("model invoked"))
    assert slide_revise.revise(deck, 0, "Do not invoke AI")[0] is None
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "other-workspace.db")
    with pytest.raises(ValueError, match="read-only"):
        presentations.save_deck(deck)
    clone = presentations.deck_from_dict(deck.to_dict())
    with pytest.raises(ValueError, match="read-only"):
        presentations.save_deck(clone, observation=deck._file_observation)
    assert not (tmp_path / "other-workspace.db").exists()


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_normal_renderer_rejects_missing_or_modified_png_even_after_load(
    revision, tmp_path, monkeypatch, failure
):
    destination = restore_current(revision, tmp_path, monkeypatch)
    deck = presentations.load_deck(LOCAL, "guide")
    target = next(
        (destination / "presentations").glob(
            "*/assets/" + hashlib.sha256(png("red")).hexdigest() + ".png"
        )
    )
    if failure == "missing":
        target.unlink()
    else:
        data = bytearray(target.read_bytes())
        data[-1] ^= 1
        target.write_bytes(data)
    with pytest.raises((ValueError, OSError)):
        presentation_export.render_html(deck)
    with pytest.raises((ValueError, OSError)):
        presentations.load_deck(LOCAL, "guide")


def test_current_pdf_change_never_relabels_historical_slide_sources(
    revision, tmp_path, monkeypatch
):
    target = add_source(revision)
    value = presentations.load_deck(LOCAL, "guide")
    value.sources[0]["document_hash"] = target.sha256
    presentations.save_deck(
        value, evidence={"sources": value.sources, "coverage": [], "source_hash": value.source_hash}
    )
    destination = restore_current(revision, tmp_path, monkeypatch)
    deck = presentations.load_deck(LOCAL, "guide")
    original = deck.to_dict()
    pdf = destination / "pdf" / (presentations._safe_name(LOCAL) + ".pdf")
    pdf.parent.mkdir(exist_ok=True)
    pdf.write_bytes(b"different current PDF")
    state = recovery_decks.document_status(deck)
    assert {"sha256": target.sha256, "historical": "available", "current_matches": False} in state[
        "documents"
    ]
    assert deck.to_dict() == original
    assert "data:image/png;base64," in presentation_export.render_html(deck)
    (destination / "objects" / target.sha256).unlink()
    assert any(
        row["historical"] == "missing" for row in recovery_decks.document_status(deck)["documents"]
    )


def test_saved_deck_or_database_replacement_invalidates_loaded_assets(
    revision, tmp_path, monkeypatch
):
    destination = restore_current(revision, tmp_path, monkeypatch)
    deck = presentations.load_deck(LOCAL, "guide")
    path = next((destination / "presentations").glob("*/guide.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["title"] = "Unobserved replacement"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        NORMAL_FIGURE(deck, "figure:1")
    with pytest.raises(ValueError, match="provenance"):
        presentations.load_deck(LOCAL, "guide")


@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("recreated", [False, True])
def test_unbound_saved_slot_restores_exact_saved_version(
    codec, tmp_path, monkeypatch, accepted, recreated
):
    source = tmp_path / "source"
    source.mkdir()
    database = source / "papers.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.executescript(store.SCHEMA)
        store._migrate(conn)
        conn.execute(
            "INSERT INTO papers(id,title,title_key,year,venue,source) VALUES(?,?,?,?,?,?)",
            (PAPER, "Paper", "paper", 2026, "Venue", "fixture"),
        )
    monkeypatch.setattr(store, "DB_PATH", database)
    monkeypatch.setattr(presentations, "DECK_DIR", source / "presentations")
    value = codec[0]
    presentations.save_deck(value)
    saved = presentations.load_deck(PAPER, "guide")
    job = slide_revision.begin(saved, 0, "Keep the completed output separate")
    answer = asdict(saved.slides[0])
    answer.update(title="Unaccepted late result", elements=None)
    monkeypatch.setattr(
        llm, "complete_result", lambda *a, **k: Completion(json.dumps({"slide": answer}))
    )
    if accepted:
        assert slide_revision.run(job)[0]
    else:
        with monkeypatch.context() as patch:
            patch.setattr(
                presentations,
                "save_deck",
                lambda *a, **k: (_ for _ in ()).throw(OSError("storage")),
            )
            assert slide_revision.run(job)[0]
    assert job.record["status"] == ("accepted" if accepted else "candidate")
    if recreated:
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute("DELETE FROM papers WHERE id=?", (PAPER,))
            conn.execute(
                "INSERT INTO papers(id,title,title_key,year,venue,source) VALUES(?,?,?,?,?,?)",
                (PAPER, "New paper with same ID", "new paper", 2026, "Venue", "fixture"),
            )
    output = tmp_path / "legacy.zip"
    sync_recovery.create(database, output)
    destination = tmp_path / "restored-legacy"
    sync_recovery.restore_detached(output, destination)
    monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
    monkeypatch.setattr(presentations, "DECK_DIR", destination / "presentations")
    monkeypatch.setattr(presentations, "figure_bytes", NORMAL_FIGURE)
    deck = presentations.load_deck(PAPER, "guide")
    if recreated:
        from paper_daily.sync_slide_recovery import read_detached

        assert deck is None
        assert (
            read_detached(destination / "papers.db", job.request_id)["record"]["result"] is not None
        )
        return
    assert deck.slides[0].title == ("Unaccepted late result" if accepted else saved.slides[0].title)
    assert deck.source_hash == saved.source_hash == ""
    assert NORMAL_FIGURE(deck, "figure:1") == png("red")
    assert slide_revise.evidence(deck)["sources"] == job.record["evidence"]["sources"]
    from paper_daily.sync_slide_recovery import read_detached

    candidate = read_detached(destination / "papers.db", job.request_id)
    assert candidate["record"]["result"]["slides"][0]["title"] == "Unaccepted late result"
    assert candidate["capabilities"]["retry"] is False


def test_missing_original_evidence_is_explicit_never_freshly_collected(
    revision, tmp_path, monkeypatch
):
    restore_current(revision, tmp_path, monkeypatch)
    deck = presentations.load_deck(LOCAL, "guide")
    assert "data:image/png;base64," in presentation_export.render_html(deck)
    with pytest.raises(ValueError, match="no retained evidence"):
        slide_revise.evidence(deck)


def test_actual_desktop_canvas_and_pdf_export_render_restored_images(
    revision, tmp_path, monkeypatch
):
    import time

    import pymupdf

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from paper_daily.desktop.presentation_pane import PresentationPane
    from paper_daily.desktop.presentation_pdf import PdfExport

    destination = restore_current(revision, tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    widget = PresentationPane()
    widget.load(LOCAL, "Restored paper")
    widget.show()
    app.processEvents()
    try:
        assert widget.deck.paper_id == LOCAL
        images = [
            item
            for item in widget.canvas.scene.items()
            if getattr(item, "spec", {}).get("kind") == "figure"
        ]
        assert len(images) == 2 and all(not item.pixmap.isNull() for item in images)
        assert "已還原" in widget.status.text()
        assert widget.slide_title.isReadOnly() and not widget.canvas.view.isInteractive()
        assert (
            not widget.generate_button.isEnabled() and not widget.canvas.revise_button.isEnabled()
        )
        assert widget.export_button.isEnabled() and widget.views.isEnabled()
        assert (
            presentations.generate(
                LOCAL,
                mode="guide",
                audience="Colleagues",
                minutes=10,
                slide_count=4,
                inputs={"original"},
            )[0]
            is None
        )
        before = widget.canvas.snapshot()
        widget.canvas.select_all()
        widget.canvas.remove_selected()
        widget.canvas.add_text()
        widget.canvas.format_selected(size=50)
        assert widget.canvas.snapshot() == before
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        QTest.keyClick(widget.canvas.view, Qt.Key.Key_Delete)
        assert widget.canvas.snapshot() == before
        assert not widget._dirty
        output = tmp_path / "normal-export.pdf"
        job = PdfExport(widget)
        finished, failed = [], []
        job.finished.connect(finished.append)
        job.failed.connect(failed.append)
        job.start(widget.deck, output)
        # The queued renderer owns its already-verified pixels, even if files
        # change before the first QTimer page callback runs.
        next((destination / "presentations").glob("*/assets/*.png")).write_bytes(
            b"changed after start"
        )
        deadline = time.monotonic() + 10
        while not finished and not failed and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert finished == [str(output)] and not failed
        with pymupdf.open(output) as pdf:
            assert pdf.page_count == 1 and len(pdf[0].get_images()) >= 2
        # A later corrupt image cannot produce an apparently successful empty PDF.
        next((destination / "presentations").glob("*/assets/*.png")).write_bytes(b"corrupt")
        rejected = tmp_path / "never-success.pdf"
        second = PdfExport(widget)
        second.failed.connect(failed.append)
        second.start(widget.deck, rejected)
        assert failed and not rejected.exists()
        assert not widget.runner._thread
    finally:
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_old_reader_rejects_replaced_database_but_explicit_reopen_can_read(
    revision, tmp_path, monkeypatch
):
    import shutil

    destination = restore_current(revision, tmp_path, monkeypatch)
    deck = presentations.load_deck(LOCAL, "guide")
    database = destination / "papers.db"
    old = destination / "previous.db"
    database.rename(old)
    shutil.copyfile(old, database)
    with pytest.raises(ValueError, match="workspace changed"):
        NORMAL_FIGURE(deck, "figure:1")
    reopened = presentations.load_deck(LOCAL, "guide")
    assert NORMAL_FIGURE(reopened, "figure:1") == png("red")


def test_running_original_job_can_finish_after_user_opens_detached_workspace(
    revision, tmp_path, monkeypatch
):
    destination = tmp_path / "other-detached"
    sync_recovery.restore_detached(archive(revision, tmp_path), destination)
    before = (destination / "papers.db").read_bytes()
    original = revision[2]
    job = slide_revision.begin(original, 0, "Finish on the captured original")
    provider = llm.complete_result

    def switch_then_complete(*args, **kwargs):
        monkeypatch.setattr(store, "DB_PATH", destination / "papers.db")
        monkeypatch.setattr(presentations, "DECK_DIR", destination / "presentations")
        return provider(*args, **kwargs)

    monkeypatch.setattr(llm, "complete_result", switch_then_complete)
    assert slide_revision.run(job)[0]
    assert job.record["status"] == "accepted"
    assert (destination / "papers.db").read_bytes() == before
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == original.slides[0].title
    monkeypatch.setattr(store, "DB_PATH", revision[0])
    monkeypatch.setattr(presentations, "DECK_DIR", revision[0].parent / "presentations")
    assert presentations.load_deck(LOCAL, "guide").slides[0].title == "Retained completed revision"
