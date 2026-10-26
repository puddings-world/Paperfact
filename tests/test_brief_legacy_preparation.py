"""Legacy text-only imports remain usable without claiming verified PDF provenance."""

from contextlib import closing

from test_research_generation import workspace as workspace

from paper_daily import brief, fetch
from paper_daily import research_generation as generation


def test_text_only_preparation_is_unanchored_and_never_used_when_enrolled(workspace, monkeypatch):
    path, client, document = workspace
    document.path.write_bytes(b"%PDF unreadable legacy import")
    monkeypatch.setattr(fetch, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(fetch, "ensure_pdf", lambda row: document.path)
    calls = []

    def prepare(row):
        calls.append(row["id"])
        return document.path, "Imported extracted text"

    monkeypatch.setattr(brief, "prepare", prepare)
    with closing(generation._connect(path)) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone()
        local_pdf, text, observed = brief._observed_pdf(conn, row)
    assert local_pdf is None and observed is None
    assert text == ("Imported extracted text" if client is None else None)
    assert calls == (["paper"] if client is None else [])


def test_valid_legacy_pdf_keeps_exact_bytes_and_skips_unverified_text(workspace, monkeypatch):
    path, _client, document = workspace
    monkeypatch.setattr(fetch, "PDF_DIR", document.path.parent)
    monkeypatch.setattr(fetch, "ensure_pdf", lambda row: document.path)

    def unexpected(row):
        raise AssertionError("Verified PDF must not use unverified cached text")

    monkeypatch.setattr(brief, "prepare", unexpected)
    with closing(generation._connect(path)) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id='paper'").fetchone()
        local_pdf, text, observed = brief._observed_pdf(conn, row)
    assert local_pdf == document.path
    assert "Original experiment" in text
    assert observed.sha256 == document.sha256


def test_managed_missing_document_never_uses_legacy_preparation(tmp_path, monkeypatch):
    from test_document_reader import LOCAL, prepared, register
    from test_sync_document_research import document, pdf_bytes
    from test_sync_reading_state_research import save

    path, journal, blobs, reader, alias, _data = prepared(tmp_path)
    register(path, journal, blobs, reader)
    save(journal, document(pdf_bytes("Absent replacement"), op_id="unavailable-replacement"))
    monkeypatch.setattr(fetch, "PDF_DIR", alias.parent)

    def unexpected(row):
        raise AssertionError("Managed unavailable documents cannot fall back to legacy text")

    monkeypatch.setattr(brief, "prepare", unexpected)
    monkeypatch.setattr(fetch, "ensure_pdf", unexpected)
    with closing(generation._connect(path)) as conn:
        row = conn.execute("SELECT * FROM papers WHERE id=?", (LOCAL,)).fetchone()
        assert brief._observed_pdf(conn, row) == (None, None, None)
