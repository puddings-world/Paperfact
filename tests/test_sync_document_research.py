"""Document metadata advances independently from immutable verified PDF bytes."""

import hashlib
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from test_sync_reading_state_research import PAPER, database, operation, ref, save

from paper_daily.sync_blobs import BlobError, BlobManifest, BlobStore
from paper_daily.sync_documents import (
    MAX_PDF_BYTES,
    applied_document,
    bind_verified_document,
    desired_document,
    list_desired_documents,
    verify_document,
)
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_research import prepare, research_writer


def pdf_bytes(text="Research", *, encrypted=False):
    with pymupdf.open() as document:
        document.new_page().insert_text((36, 60), text)
        options = (
            {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "reader"}
            if encrypted
            else {}
        )
        return document.tobytes(**options)


def payload(data):
    return {
        "paper_id": PAPER,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "media_type": "application/pdf",
    }


def document(data, *, op_id="document", action="put", incarnation="document-a", parent="a"):
    return operation(
        "paper_document",
        PAPER,
        payload(data) if action == "put" else {},
        op_id=op_id,
        action=action,
        incarnation=incarnation,
        parents=[ref("paper", PAPER, parent)],
    )


def local_blob(store, data):
    manifest = BlobManifest(hashlib.sha256(data).hexdigest(), len(data))
    state = store.begin(manifest)
    if not state["complete"]:
        offset = state["offset"]
        while offset < len(data):
            offset = store.append(manifest, offset, data[offset : offset + store.chunk_bytes])
    return store.finalize(manifest)


def target(path):
    with sqlite3.connect(path) as conn:
        return desired_document(conn, PAPER)


def applied(path):
    with sqlite3.connect(path) as conn:
        return applied_document(conn, PAPER)


def test_metadata_and_intent_commit_without_bytes_and_preserve_legacy_research(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    legacy = tmp_path / "pdf" / "sync_paper.pdf"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy PDF stays untouched")
    cache = tmp_path / "text.txt"
    cache.write_text("existing derived text")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page,anchor) "
            "VALUES(?,'Anchored','old','note',1,'{\"p0\":0}')",
            ("sync:" + PAPER,),
        )
        before = conn.execute("SELECT * FROM notes").fetchall()
    value = document(pdf_bytes())
    save(journal, value)
    save(journal, value)
    assert target(path)["operation_id"] == "document" and applied(path) is None
    assert (
        legacy.read_bytes() == b"legacy PDF stays untouched"
        and cache.read_text() == "existing derived text"
    )
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM notes").fetchall() == before
        assert conn.execute(
            "SELECT operation_id,state FROM research_document_intents"
        ).fetchall() == [("document", "pending")]
        assert list_desired_documents(conn) == [target(path)]
        assert list_desired_documents(conn, after=PAPER) == []


@pytest.mark.parametrize(
    "problem", ["hash", "zero", "bool", "large", "type", "extra", "paper", "parent", "id"]
)
def test_closed_document_manifest_validation(problem):
    value = document(pdf_bytes())
    changes = {
        "hash": ("sha256", "A" * 64),
        "zero": ("size", 0),
        "bool": ("size", True),
        "large": ("size", MAX_PDF_BYTES + 1),
        "type": ("media_type", "text/html"),
        "extra": ("url", "https://example.org/a.pdf"),
        "paper": ("paper_id", "other"),
    }
    if problem in changes:
        key, invalid = changes[problem]
        value["payload"][key] = invalid
    elif problem == "parent":
        value["parents"][0]["id"] = "other"
    else:
        value["entity_id"] = "other"
    with pytest.raises(ValueError):
        canonical_operation(value)


def test_verified_binding_is_transactional_retry_safe_and_independent_of_desired(tmp_path):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    store = BlobStore(tmp_path / "blobs")
    local_blob(store, data)
    wanted = target(path)
    verified = verify_document(store, wanted)
    with pytest.raises(RuntimeError), journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, verified)
        raise RuntimeError("commit interrupted")
    assert applied(path) is None
    with journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, verified)
    assert applied(path) == wanted
    before = path.read_bytes()
    with journal.transaction() as conn:
        changes = conn.total_changes
        assert bind_verified_document(conn, wanted, verified)
        assert conn.total_changes == changes
    assert path.read_bytes() == before
    save(journal, document(pdf_bytes("Replacement"), op_id="replacement"))
    assert target(path)["operation_id"] == "replacement" and applied(path) == wanted
    with journal.transaction() as conn:
        assert not bind_verified_document(conn, wanted, verified)
    prepare(path, workspace_id="workspace", device_id="device")
    assert applied(path) == wanted


@pytest.mark.parametrize("change", ["delete", "parent", "removed", "corrupt", "symlink"])
def test_late_or_invalidated_verification_cannot_bind(tmp_path, monkeypatch, change):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    store = BlobStore(tmp_path / "blobs")
    final = local_blob(store, data)
    wanted = target(path)
    verified = verify_document(store, wanted)
    if change == "delete":
        save(journal, document(data, op_id="detach", action="delete"))
    elif change == "parent":
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE research_paper_projection SET incarnation='changed'")
    elif change == "removed":
        final.unlink()
    elif change == "corrupt":
        final.write_bytes(b"x" * len(data))
    else:
        original = Path.lstat
        # Simulate the OS reporting a replaced link; Windows link creation needs privilege.
        monkeypatch.setattr(
            Path,
            "lstat",
            lambda path: (
                SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
                if path == final
                else original(path)
            ),
        )
    with journal.transaction() as conn:
        assert not bind_verified_document(conn, wanted, verified)
    assert applied(path) is None


@pytest.mark.parametrize("kind", ["html", "truncated", "encrypted", "bad_digest"])
def test_unreadable_or_mismatching_bytes_are_never_verified(tmp_path, kind):
    path = tmp_path / "research.db"
    journal = database(path)
    data = pdf_bytes(encrypted=kind == "encrypted")
    if kind == "html":
        data = b"<html>not a PDF</html>"
    elif kind == "truncated":
        data = data[: data.rfind(b"%%EOF")]
    save(journal, document(data))
    store = BlobStore(tmp_path / "blobs")
    final = local_blob(store, data)
    if kind == "bad_digest":
        final.write_bytes(b"x" * len(data))
    with pytest.raises((ValueError, BlobError)):
        verify_document(store, target(path))
    assert applied(path) is None


def test_metadata_failure_rolls_back_intent_and_missing_parent_never_creates_paper(tmp_path):
    path = tmp_path / "research.db"
    journal = database(path)
    value = document(pdf_bytes())

    def interrupted(conn, operation):
        research_writer(conn, operation)
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError):
        save(journal, value, interrupted)
    assert target(path) is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM research_document_intents").fetchone()[0] == 0
        conn.execute("DELETE FROM research_paper_projection")
    with pytest.raises(ValueError, match="current projected paper"):
        save(journal, value)
    assert target(path) is None


def test_delete_retains_verified_applied_document_and_stale_retirement_cannot_detach_restore(
    tmp_path,
):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    wanted = target(path)
    store = BlobStore(tmp_path / "blobs")
    final = local_blob(store, data)
    with journal.transaction() as conn:
        assert bind_verified_document(conn, wanted, verify_document(store, wanted))
    save(journal, document(data, op_id="delete", action="delete"))
    assert target(path) is None and applied(path) == wanted and final.read_bytes() == data
    save(journal, document(data, op_id="restored", incarnation="new-document"))
    restored = target(path)
    save(journal, document(data, op_id="retire-old", action="delete"))
    assert target(path) == restored


def test_plain_claim_and_changed_workspace_cannot_authorize_binding(tmp_path):
    path = tmp_path / "research.db"
    journal, data = database(path), pdf_bytes()
    save(journal, document(data))
    wanted = target(path)
    with pytest.raises(ValueError, match="verification snapshot"), journal.transaction() as conn:
        bind_verified_document(conn, wanted, {"available": True})
    store = BlobStore(tmp_path / "blobs")
    local_blob(store, data)
    verified = verify_document(store, wanted)
    with journal.transaction() as conn:
        assert not bind_verified_document(conn, dict(wanted, workspace_id="other"), verified)
