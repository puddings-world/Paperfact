"""Read-only exact originals declared by a freshly resumed text or note draft.

This capability is process-only. It publishes nothing and is independent of
claim, deck and collected-material permissions. GUI admission uses native fences;
intervening database writes require semantic revalidation on a worker.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from paper_daily import archived_draft_resume as resume
from paper_daily import file_change, sync_capture, sync_source_files
from paper_daily import review_draft_resumption as resumption
from paper_daily.sync_files import file_id, read_json
from paper_daily.sync_legacy_sources import path as safe_path

_SEAL = object()


def _native(path):
    info = safe_path(path).stat()
    return info.st_dev, info.st_ino


def _fence(paths):
    result = []
    for path in paths:
        for entry in (Path(path), Path(str(path) + "-wal")):
            safe_path(entry)
            result.append((str(entry), file_change.version(entry) if entry.exists() else None))
    return tuple(result)


def _connect(review):
    if review.closed or _native(review.path) != tuple(review.identity):
        raise ValueError("Draft review is closed or its workspace was replaced")
    conn = sqlite3.connect(
        review.path.as_uri() + "?mode=ro",
        uri=True,
        factory=sync_capture.CaptureConnection,
        timeout=0.025,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _check(cancelled):
    if cancelled():
        raise ValueError("Draft original read cancelled")


def _metadata(review, preview, prepared, current_document, cache_owner=None):
    data = review._verify_preview(preview)
    if (
        data["origin"] not in resumption.ORIGINS
        or data["source_hash"] is None
        or not data["apply"]
        or data.get("resume_state") != "ready"
    ):
        raise ValueError("Verify the resumed draft's recorded original first")
    with closing(_connect(review)) as conn:
        conn.execute("BEGIN")
        typed = resumption.adapter(data["origin"])
        expected = typed.check_base(review, conn, data)
        intent = typed.source_intent(expected)
        payload = sync_source_files.check_prepared_source_in(conn, conn._capture_client, prepared)
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
            (intent.owner_id,),
        ).fetchone()
        if (
            mapping is None
            or payload["paper_id"] != mapping[0]
            or payload["slot"] != data["source_hash"]
        ):
            raise ValueError("Staged original belongs to another resumed draft")
        registered = conn.execute(
            "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
        ).fetchone()
        wanted = (prepared.workspace, str(prepared.store.root), str(prepared.root))
        if registered is not None and tuple(registered) != wanted:
            raise ValueError("Draft original storage registration changed")
        if registered is None and (
            prepared.store.root != review.path.parent / "blobs"
            or prepared.root != review.path.parent / "research-versions"
        ):
            raise ValueError("Draft original has no current owned storage")
        identity = file_id(payload["paper_id"], sync_source_files.FEATURE, data["source_hash"])
        graph = conn._capture_client._optimistic_graph(conn)[0].get(("research_file", identity))
        parents = [{"kind": "paper", "id": payload["paper_id"], "incarnation": prepared.parent}]
        if graph and (not graph["active"] or graph["parents"] != parents):
            raise ValueError("Draft original was removed or retired")
        if cache_owner is not None:
            from paper_daily.review_draft_sources import check_owner

            check_owner(cache_owner, review, prepared, conn._capture_client)
        resume._check_document(current_document)
        review._check(conn)
    return data


@dataclass(frozen=True, init=False)
class OriginalProof:
    review: object = field(repr=False)
    preview: object = field(repr=False)
    prepared: object = field(repr=False)
    current_document: object = field(repr=False)
    cache_owner: object = field(repr=False)
    document_hash: str
    data: bytes = field(repr=False)
    pages: int
    source_path: Path = field(repr=False)
    file_version: tuple = field(repr=False)
    natives: tuple = field(repr=False)
    files: tuple = field(repr=False)
    fence: tuple = field(repr=False)
    _seal: object = field(repr=False)


def prepare(review, preview, document_hash, *, cancelled=lambda: False, previous=None):
    """Worker: verify this draft/source intent and read/parse exact bounded bytes."""
    _check(cancelled)
    data = review._verify_preview(preview)
    if data["origin"] not in resumption.ORIGINS or data["source_hash"] != document_hash:
        raise ValueError("Select the original declared by this resumed draft")
    key = resume._proof_key(data)
    if previous is None:
        prepared = review._resume_sources.get(key)
        if key not in review._resume_documents or prepared is None:
            raise ValueError("Verify the resumed draft's original in this session first")
        document = review._resume_documents[key]
        cache_owner = review._resume_cache_owners.get(key)
    else:
        if (
            not isinstance(previous, OriginalProof)
            or previous._seal is not _SEAL
            or previous.review is not review
            or previous.preview != preview
        ):
            raise ValueError("Use this draft's actual verified original")
        if gui_status(previous) == "revoked":
            raise ValueError("Draft original or workspace changed")
        prepared, document = previous.prepared, previous.current_document
        cache_owner = previous.cache_owner
    _metadata(review, preview, prepared, document, cache_owner)
    index = safe_path(prepared.store.root / "index.sqlite")
    natives = ((str(review.path), tuple(review.identity)), (str(index), _native(index)))
    before = _fence((review.path, index))
    payload = read_json(prepared.payload.encode())
    size = next(asset["size"] for asset in payload["assets"] if asset["sha256"] == document_hash)
    source, captured = prepared.proof.files[document_hash]
    source = safe_path(source)
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as conn:
        row = conn.execute(
            "SELECT size,complete FROM blobs WHERE digest=?", (document_hash,)
        ).fetchone()
        if row is None or tuple(row) != (size, 1):
            raise ValueError("Draft original is not a complete owned staged object")
    _check(cancelled)
    with source.open("rb") as stream:
        version = file_change.version(source, stream=stream)
        if version != captured or not 0 < size <= sync_source_files.MAX_PDF_BYTES:
            raise ValueError("Draft original bytes changed or exceed their bound")
        content = stream.read(size + 1)
        if file_change.version(source, stream=stream) != version:
            raise ValueError("Draft original changed while reading")
    if len(content) != size or hashlib.sha256(content).hexdigest() != document_hash:
        raise ValueError("Draft original bytes do not match the recorded PDF")
    _check(cancelled)
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("Draft original is not a readable PDF")
        pages = pdf.page_count
        pdf.load_page(0)
    _metadata(review, preview, prepared, document, cache_owner)
    files = [(str(source), version)]
    from paper_daily.note_source_mapping import ChosenOwner

    if isinstance(cache_owner, ChosenOwner):
        files.extend(cache_owner.files)
    if document is not None and document.available:
        files.append((str(document.path), file_change.version(document.path)))
    if before != _fence((review.path, index)):
        raise ValueError("Research metadata changed during original verification; retry")
    _check(cancelled)
    proof = object.__new__(OriginalProof)
    for name, value in dict(
        review=review,
        preview=preview,
        prepared=prepared,
        current_document=document,
        cache_owner=cache_owner,
        document_hash=document_hash,
        data=content,
        pages=pages,
        source_path=source,
        file_version=version,
        natives=natives,
        files=tuple(files),
        fence=before,
        _seal=_SEAL,
    ).items():
        object.__setattr__(proof, name, value)
    if gui_status(proof) != "ready":
        raise ValueError("Draft original changed before delivery")
    return proof


def gui_status(proof):
    """No SQL, PDF parsing, byte hashes or model calls on the GUI thread."""
    if (
        not isinstance(proof, OriginalProof)
        or getattr(proof, "_seal", None) is not _SEAL
        or proof.review.closed
    ):
        return "revoked"
    try:
        if any(_native(path) != native for path, native in proof.natives):
            return "revoked"
        if any(file_change.version(safe_path(path)) != version for path, version in proof.files):
            return "revoked"
        if not proof.prepared.proof.matches(proof.prepared.proof_operation):
            return "revoked"
        return (
            "ready"
            if _fence(path for path, _native_id in proof.natives) == proof.fence
            else "recheck"
        )
    except (OSError, ValueError):
        return "revoked"


def revalidate(proof, *, cancelled=lambda: False):
    if not isinstance(proof, OriginalProof) or getattr(proof, "_seal", None) is not _SEAL:
        raise ValueError("Use an actual resumed-draft original proof")
    return prepare(
        proof.review, proof.preview, proof.document_hash, cancelled=cancelled, previous=proof
    )
