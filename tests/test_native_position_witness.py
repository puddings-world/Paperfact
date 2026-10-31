"""Native file load completion, same-count replacement/ABA and late Ready guards."""

import os

import pytest
from test_reading_position_controller import idle, recorded, until
from test_reading_position_controller import reader as reader_fixture
from test_reading_positions import pdf_bytes, records, view

from paper_daily import file_change
from paper_daily import reading_positions as positions
from paper_daily.desktop import pdfpane

reader = reader_fixture


def test_source_mutation_after_worker_validation_before_native_jump_never_moves(
    reader, monkeypatch
):
    app, widget, controller, database, path, _gates = reader
    before = recorded(reader)
    actual = widget.pdf.go_to_position
    delivered = []

    def replaced(page, **kwargs):
        assert kwargs["source_version"] is not None
        delivered.append(page)
        path.write_bytes(pdf_bytes(4, "Changed in native delivery gap"))
        return actual(page, **kwargs)

    monkeypatch.setattr(widget.pdf, "go_to_position", replaced)
    assert controller.resume()
    idle(app, controller)
    assert delivered == [4]
    assert widget.pdf.current_page() == 0
    assert widget.pdf.position_source_version() is None
    assert not controller.remember_button.isEnabled()
    assert "Reopen this PDF" in controller.status.text()
    assert records(database, positions.RECEIPTS) == before


def test_native_position_jump_requires_explicit_proof_when_supplied_and_preserves_other_callers(
    reader,
):
    app, widget, _controller, _database, _path, _gates = reader
    assert not widget.pdf.go_to_position(4, source_version=None)
    assert not widget.pdf.go_to_position(4, source_version=("unverified",))
    assert widget.pdf.current_page() == 0
    assert widget.pdf.go_to_position(4)
    app.processEvents()
    assert widget.pdf.current_page() + 1 == 4


@pytest.mark.parametrize("change", ["B", "ABA"])
def test_later_highlight_hash_cannot_stamp_same_path_B_or_ABA_on_native_A(reader, change):
    app, widget, controller, database, path, _gates = reader
    original = path.read_bytes()
    before = path.stat()
    native = widget.pdf.position_identity()
    witness = widget.pdf.position_source_version()
    controller.invalidate()
    path.write_bytes(pdf_bytes(4, "B, with the SAME page count"))
    if change == "ABA":
        path.write_bytes(original)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    widget._highlight_view = view(database, path)
    widget._pdf_fingerprint = widget._highlight_view.fingerprint
    assert widget.pdf.position_identity() == native
    assert widget.pdf.position_source_version() == witness
    assert file_change.version(path) != witness
    assert controller.bind()
    idle(app, controller)
    assert controller.view is None
    assert not controller.remember_button.isEnabled()
    assert not controller.resume_button.isEnabled()
    assert "Reopen this PDF" in controller.status.text()
    assert records(database, positions.TABLE) == []
    assert records(database, positions.RECEIPTS) == []
    # Only a real, explicit native reload can establish the new exact source.
    assert widget.pdf.load(path)
    app.processEvents()
    until(app, lambda: controller.view is not None and not controller.busy)
    assert widget.pdf.position_source_version() == controller.view.original_version
    assert controller.remember()
    idle(app, controller)
    assert records(database, positions.TABLE)[0][1] == widget._pdf_fingerprint


def test_unavailable_native_witness_leaves_reading_available_but_position_disabled(
    reader, monkeypatch
):
    app, widget, controller, database, path, _gates = reader
    monkeypatch.setattr(pdfpane._LoadWitness, "_version", lambda _self: None)
    controller.invalidate()
    assert widget.pdf.load(path)
    app.processEvents()
    idle(app, controller)
    assert widget.pdf.page_count() == 4 and widget.pdf.isVisible()
    assert widget.pdf.position_source_version() is None
    assert controller.view is None and not controller.remember()
    assert "Reopen this PDF" in controller.status.text()
    assert records(database, positions.TABLE) == []


def test_file_replaced_between_native_open_and_ready_completion_has_no_version_proof(
    reader, monkeypatch
):
    app, widget, controller, database, path, _gates = reader
    controller.invalidate()
    replacement = pdf_bytes(4, "Changed during native completion")
    if isinstance(widget.pdf, pdfpane._QtPdfPane):
        original = pdfpane.QPdfDocument.load

        def delayed_ready(document, filename):
            result = original(document, filename)
            path.write_bytes(replacement)
            return result

        monkeypatch.setattr(pdfpane.QPdfDocument, "load", delayed_ready)
    else:
        import pymupdf

        original = pymupdf.open

        def delayed_ready(*args, **kwargs):
            document = original(*args, **kwargs)
            path.write_bytes(replacement)
            return document

        monkeypatch.setattr(pymupdf, "open", delayed_ready)
    assert widget.pdf.load(path)
    app.processEvents()
    idle(app, controller)
    assert widget.pdf.position_source_version() is None
    assert widget.pdf.page_count() == 4
    assert controller.view is None and not controller.remember()
    assert records(database, positions.TABLE) == []


if pdfpane.HAVE_QTPDF:

    def test_reused_native_document_ready_cannot_resurrect_old_load_proof(tmp_path):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(pdf_bytes())
        b.write_bytes(pdf_bytes(4, "Different same-count native document"))
        pane = pdfpane._QtPdfPane()
        assert pane.load(a)
        assert pane.position_source_version() is not None
        identity = pane.position_identity()
        pane._doc.load(str(b))
        assert pane._doc.status() == pdfpane.QPdfDocument.Status.Ready
        assert pane.position_identity() == identity
        assert pane.position_source_version() is None
        pane.unload()
        pane.deleteLater()
        app.processEvents()

    def test_late_ready_from_rejected_candidate_never_rebinds_existing_native_document(
        tmp_path, monkeypatch
    ):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
        a.write_bytes(pdf_bytes())
        b.write_bytes(pdf_bytes(4, "B"))
        pane = pdfpane._QtPdfPane()
        assert pane.load(a)
        native, witness = pane.position_identity(), pane.position_source_version()
        status = pdfpane.QPdfDocument.status
        captured = []

        def delayed(document):
            if document is pane._doc:
                return status(document)
            captured.append(document)
            return pdfpane.QPdfDocument.Status.Loading

        monkeypatch.setattr(pdfpane.QPdfDocument, "status", delayed)
        assert not pane.load(b)
        candidate = captured[0]
        monkeypatch.setattr(pdfpane.QPdfDocument, "status", status)
        candidate.statusChanged.emit(pdfpane.QPdfDocument.Status.Ready)
        assert pane.position_identity() == native
        assert pane.position_source_version() == witness
        pane.unload()
        pane.deleteLater()
        app.processEvents()
