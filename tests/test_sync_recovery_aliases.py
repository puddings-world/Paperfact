"""Detached reader aliases must be unambiguous on every supported filesystem."""

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pymupdf
import pytest
from test_sync_operations import client, paper
from test_sync_recovery import blob, rewrite

from paper_daily import sync_recovery as recovery
from paper_daily.sync_blobs import BlobStore


def workspace(root, names, applied=None):
    root.mkdir()
    database = root / "papers.db"
    current = client(database, "alias-fixture")
    owned = BlobStore(root / "owned")
    manifests = {}
    for index, local in enumerate(names):
        identity = str(uuid4())
        current.save(current.new_graph_operation("paper", identity, paper(f"Paper {index}")))
        with closing(sqlite3.connect(database)) as conn:
            old = conn.execute(
                "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (identity,)
            ).fetchone()[0]
            conn.execute("UPDATE papers SET id=? WHERE id=?", (local, old))
            conn.execute(
                "UPDATE research_paper_identity SET local_id=? WHERE sync_id=?", (local, identity)
            )
            conn.commit()
        if applied is not None and index not in applied:
            continue
        with pymupdf.open() as document:
            document.new_page().insert_text((40, 50), f"Distinct PDF {index}")
            content = document.tobytes()
        manifest = blob(owned, content)
        manifests[local] = (manifest, content)
        current.save(current.new_graph_operation("paper_document", identity, {
            "paper_id": identity, "sha256": manifest.sha256, "size": manifest.size,
            "media_type": "application/pdf",
        }))
        with closing(sqlite3.connect(database)) as conn:
            target = conn.execute(
                "SELECT target FROM research_document_desired WHERE paper_id=?", (identity,)
            ).fetchone()[0]
            conn.execute("INSERT INTO research_document_applied VALUES(?,?)", (identity, target))
            conn.commit()
    return database, current, owned, manifests


@pytest.mark.parametrize("applied", [{0, 1}, {0}, {1}])
@pytest.mark.parametrize("names", [("paper-a", "PAPER-A"), ("paper:a", "paper/a")])
def test_ambiguous_alias_blocks_backup_without_changing_source_or_publishing(
    tmp_path, names, applied
):
    database, current, owned, manifests = workspace(tmp_path / "source", names, applied)
    before_database, before_pending = database.read_bytes(), current.journal.pending()
    output = tmp_path / "research.zip"
    with pytest.raises(recovery.RecoveryError, match="Ambiguous"):
        recovery.create(database, output, blob_store=owned)
    assert not output.exists()
    assert database.read_bytes() == before_database
    assert current.journal.pending() == before_pending
    for manifest, content in manifests.values():
        assert owned.verified_path(manifest).read_bytes() == content


@pytest.mark.parametrize("name", ["CON", "aux", "NUL", "PrN", "COM1", "lpt9", "con.notes"])
def test_reserved_windows_alias_blocks_backup_without_creating_device_files(tmp_path, name):
    database, current, owned, _ = workspace(tmp_path / "source", [name])
    before_database, before_pending = database.read_bytes(), current.journal.pending()
    output = tmp_path / "research.zip"
    with pytest.raises(recovery.RecoveryError, match="portable"):
        recovery.create(database, output, blob_store=owned)
    assert not output.exists() and not (database.parent / "pdf").exists()
    assert database.read_bytes() == before_database
    assert current.journal.pending() == before_pending


def test_unique_case_sensitive_names_keep_exact_paper_mapping_and_pdf_bytes(tmp_path):
    from paper_daily.document_reader import from_workspace

    names = ["Paper-A", "PAPER-B", "comparison-COM1"]
    database, _current, owned, manifests = workspace(tmp_path / "source", names)
    package = tmp_path / "research.zip"
    recovery.create(database, package, blob_store=owned)
    destination = tmp_path / "restored"
    recovery.restore_detached(package, destination)
    with closing(sqlite3.connect(destination / "papers.db")) as conn:
        assert {row[0] for row in conn.execute("SELECT id FROM papers")} == set(names)
    reader = from_workspace(destination / "papers.db", legacy_root=destination / "pdf")
    for local, (manifest, content) in manifests.items():
        document = reader.resolve(local)
        assert document.available and document.sha256 == manifest.sha256
        assert document.path.name == local + ".pdf"
        assert document.path.read_bytes() == content


def rename_archived_local_paper(manifest, files, old, new):
    for table in manifest["tables"]:
        if table["name"] not in {"papers", "research_paper_identity"}:
            continue
        path = "tables/" + table["name"] + ".jsonl"
        key = "id" if table["name"] == "papers" else "local_id"
        rows = [json.loads(line) for line in files[path].splitlines()]
        for row in rows:
            if row[key] == old:
                row[key] = new
        data = b"".join((json.dumps(row) + "\n").encode() for row in rows)
        files[path] = data
        table["size"], table["sha256"] = len(data), hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("replacement", ["PAPER-A", "CON"])
@pytest.mark.parametrize("applied", [{0, 1}, {0}])
def test_old_unsafe_archive_is_rejected_before_restore_publication(
    tmp_path, replacement, applied
):
    # A missing second PDF is still a collision: its legacy lookup would read
    # the first paper's alias on a case-insensitive filesystem.
    if replacement == "CON" and applied == {0}:
        applied = {1}
    database, _current, owned, _ = workspace(
        tmp_path / "source", ["paper-a", "paper-b"], applied
    )
    safe = tmp_path / "safe.zip"
    recovery.create(database, safe, blob_store=owned)
    unsafe = rewrite(safe, tmp_path / "old-unsafe.zip", lambda manifest, files:
                     rename_archived_local_paper(manifest, files, "paper-b", replacement))
    original = unsafe.read_bytes()
    destination = tmp_path / "new-parent" / "restored"
    with pytest.raises(recovery.RecoveryError):
        recovery.inspect(unsafe)
    with pytest.raises(recovery.RecoveryError):
        recovery.restore_detached(unsafe, destination)
    assert unsafe.read_bytes() == original
    assert not destination.parent.exists()
