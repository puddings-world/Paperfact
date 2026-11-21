"""Exchange selected ordinary-reader PDF originals without replacing a local file."""

import hashlib
import os
import shutil
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path, PureWindowsPath

from paper_daily.document_reader import _owned_path, _safe_name
from paper_daily.drive_list_originals import DriveListOriginals
from paper_daily.drive_list_records import ListReviewRequired
from paper_daily.drive_paper_baseline import published_bindings
from paper_daily.drive_sync_objects import MAX_OBJECT
from paper_daily.file_change import version
from paper_daily.native_primary_publication import _WORKSPACE_MARKERS
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.workspace_service import _read, _tables


def _document(path, memory):
    import pymupdf

    _owned_path(path)
    changed = version(path)
    stat = path.stat()
    if not path.is_file() or stat.st_nlink != 1 or not 0 < stat.st_size <= MAX_OBJECT:
        raise ListReviewRequired("Review the local PDF file type, size or ownership")
    cached = memory.get(path)
    if cached and cached[0] == changed:
        return cached[1]
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ListReviewRequired("The local original is missing its PDF header")
        stream.seek(max(0, stat.st_size - 4096))
        if b"%%EOF" not in stream.read():
            raise ListReviewRequired("The local PDF is incomplete")
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    try:
        with pymupdf.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass or doc.page_count < 1:
                raise ValueError("Unreadable PDF")
            doc.load_page(0)
    except (RuntimeError, ValueError) as exc:
        raise ListReviewRequired("The PDF could not be opened for reading") from exc
    if version(path) != changed:
        raise ListReviewRequired("PDF changed while preparing its original")
    manifest = BlobManifest(digest, stat.st_size)
    if len(memory) >= 10000:
        memory.clear()
    memory[path] = changed, manifest
    return manifest


def _install(index, path, blobs, manifest, expected):
    verified = index.objects.get(manifest, blobs, expected=expected)
    path.parent.mkdir(exist_ok=True)
    _owned_path(path)
    with tempfile.TemporaryDirectory(dir=path.parent) as staging:
        copy = Path(staging) / "original.pdf"
        shutil.copyfile(verified, copy)
        if _document(copy, {}) != expected:
            raise ListReviewRequired("Downloaded PDF does not match its selected original")

        def publish():
            index.check()
            _owned_path(path)
            try:
                os.link(copy, path)
            except FileExistsError as exc:
                raise ListReviewRequired("A local PDF appeared; sync again") from exc

        index.ticket.checkpoint(publish)


def exchange_originals(directory, cache, store, list_id, revision, ticket, memory):
    database = store.workspace.path
    root = _owned_path(database.parent / "pdf")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        generation = conn.execute("PRAGMA data_version").fetchone()

        def check_local():
            if conn.execute("PRAGMA data_version").fetchone() != generation:
                raise ListReviewRequired("Research changed during PDF sync; sync again")

        if _tables(conn) & _WORKSPACE_MARKERS:
            raise ListReviewRequired("Use enrolled workspace sync for managed originals")
        index = DriveListOriginals(directory, cache, store, list_id, revision, ticket,
                                  check_local=check_local)
        _, _, remote = index._read()
        if not remote and not root.exists():
            return
        selected = {row[0] for row in conn.execute(
            "SELECT paper_id FROM list_papers WHERE list_id=?", (list_id,)
        )}
        with _read(store.path) as settings:
            bindings = {local: paper for paper, local in
                        published_bindings(settings, index.members).items()}
        if set(bindings) != selected or set(bindings.values()) != set(index.members):
            raise ListReviewRequired("Refresh the bibliography before synchronizing originals")
        # A single enumeration avoids one failed filesystem lookup per missing original.
        present = None
        if len(bindings) > 32:
            try:
                with os.scandir(root) as entries:
                    present = {entry.name.casefold() for entry in entries
                               if entry.name.lower().endswith(".pdf")}
            except FileNotFoundError:
                present = set()
        names = None
        blobs = None
        conflicts = []
        for local, paper in bindings.items():
            ticket.check()
            name = _safe_name(local)
            path = root / (name + ".pdf")
            item = remote.get(paper)
            if not item and present is not None and path.name.casefold() not in present:
                continue
            exists = path.exists()
            if not item and not exists:
                continue
            if names is None:
                ids = conn.execute("SELECT id FROM papers")
                names = Counter(_safe_name(row[0]).casefold() for row in ids)
            if names[name.casefold()] != 1 or PureWindowsPath(path.name).is_reserved():
                raise ListReviewRequired("Review papers with an ambiguous PDF filename")
            _owned_path(path)
            expected = (BlobManifest(item["manifest"]["sha256"], item["manifest"]["size"])
                        if item else None)
            if exists:
                found = _document(path, memory)
                if expected and found != expected:
                    title = conn.execute("SELECT title FROM papers WHERE id=?", (local,)).fetchone()
                    conflicts.append(title[0] if title and title[0] else local)
                    continue
                if not expected:
                    index.publish(paper, index.members[paper], path, found)
            else:
                if blobs is None:
                    blobs = BlobStore(cache / directory.folder / "verified")
                _install(index, path, blobs, item["manifest"], expected)
        index.check()
        return conflicts
