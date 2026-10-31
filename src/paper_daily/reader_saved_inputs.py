"""Read-only saved-reader preparation. Capture is metadata-only; reads are worker-only.

This does not install lifecycles, adopt legacy caches, resolve a desired PDF, or
authorize a writer. A caller must already own the paper and actual loaded source.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from paper_daily import annotation_content, file_change, research_chat, sync_capture
from paper_daily import manual_highlight_ops as highlights
from paper_daily import research_generation as generation
from paper_daily.audit_inputs import _connect
from paper_daily.document_reader import ResolvedDocument
from paper_daily.sync_documents import MAX_PDF_BYTES

MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 5000


def worker_only():
    if threading.current_thread() is threading.main_thread():
        raise RuntimeError("Saved-reader preparation requires a worker")


def _json(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_BYTES:
        raise ValueError("Saved-reader snapshot exceeds its supported budget")
    return encoded


def _identity(database):
    info = Path(database).stat()
    if not info.st_ino:
        raise ValueError("Database identity is unavailable")
    return info.st_dev, info.st_ino


def _document(document):
    if not isinstance(document, ResolvedDocument) or not document.available:
        raise ValueError("An actual loaded document is required")
    return {
        "document_lease": id(document),
        "resolver_lease": id(document._owner),
        "mode": document.mode,
        "local_id": document.local_id,
        "paper_id": document.paper_id,
        "path": str(document.path),
        "document_hash": document.sha256,
        "target": document._target,
        "context": document._context,
        "generation": document._generation,
        "identity": document._identity,
    }


@dataclass(frozen=True)
class SavedRequest:
    database: str
    paper_id: str
    database_identity: tuple[int, int]
    owner_json: str
    source_json: str | None


@dataclass(frozen=True)
class SavedSnapshot:
    request: SavedRequest
    payload_json: str

    @property
    def data(self):
        """Return a detached copy, never mutable state retained by the worker."""
        return json.loads(self.payload_json)

    @property
    def chat_snapshot(self):
        return self.data["chat"]


def capture(owner, *, document=None, native_source_version=None):
    """Capture existing ownership and native identities; no SQL, hashing or Markdown.

    native_source_version must come from the native PDF's completed-load witness.
    A missing document is source-unknown, not permission to resolve a current PDF.
    """
    if not isinstance(owner, highlights.HighlightOwner):
        raise ValueError("An existing captured paper owner is required")
    source = None
    if document is not None:
        record = _document(document)
        if (
            document.local_id != owner.paper_id
            or document._owner is None
            or document._owner.db_path != owner.database
            or native_source_version is None
            or file_change.version(document.path) != native_source_version
        ):
            raise ValueError("Loaded source identity changed")
        source = _json({"document": record, "native_version": native_source_version})
    elif native_source_version is not None:
        raise ValueError("A native witness cannot invent document ownership")
    return SavedRequest(
        str(owner.database), owner.paper_id, _identity(owner.database), owner._json, source
    )


def _source(request, document, *, verify_bytes):
    if request.source_json is None:
        if document is not None:
            raise ValueError("The request did not capture this source")
        return None
    expected = json.loads(request.source_json)
    if document is None or json.loads(_json(_document(document))) != expected["document"]:
        raise ValueError("Loaded source identity changed")
    # intact deliberately permits verified A to remain loaded while desired B changes.
    if document._owner is None or not document._owner.intact(document):
        raise ValueError("The loaded source owner changed")
    path = document.path
    if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("Loaded source exceeds its verification budget")
    with path.open("rb") as stream:
        if (
            json.loads(_json(file_change.version(path, stream=stream)))
            != expected["native_version"]
        ):
            raise ValueError("The loaded source bytes changed")
        if verify_bytes and hashlib.file_digest(stream, "sha256").hexdigest() != document.sha256:
            raise ValueError("The loaded source hash changed")
        if (
            json.loads(_json(file_change.version(path, stream=stream)))
            != expected["native_version"]
        ):
            raise ValueError("The loaded source bytes changed")
    return document.sha256


def _tables(conn):
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(conn, tables, table, paper_id, fields):
    if table not in tables:
        return []
    columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    if not set(fields) <= set(columns):
        raise ValueError("Saved-reader table is incomplete")
    lengths = "+".join(
        'COALESCE(length(CAST("' + name.replace('"', '""') + '" AS BLOB)),0)' for name in columns
    )
    count, size = conn.execute(
        f"SELECT count(*),COALESCE(sum({lengths}),0) FROM {table} WHERE paper_id=?",
        (paper_id,),
    ).fetchone()
    if count > MAX_ROWS or size > MAX_BYTES:
        raise ValueError("Saved-reader rows exceed their supported budget")
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE paper_id=? ORDER BY rowid", (paper_id,)
        )
    ]


def _annotation(conn, tables, paper_id, feature):
    table = annotation_content.FEATURES[feature]
    rows = _rows(conn, tables, table, paper_id, annotation_content.FIELDS.split())
    if rows:
        row = annotation_content.validate_row(feature, rows[0])
        return {
            "known": True,
            "row": row,
            "body": annotation_content.decode(feature, row["body_json"]),
        }
    known = (
        "paper_annotation_known" in tables
        and conn.execute(
            "SELECT 1 FROM paper_annotation_known WHERE feature=? AND paper_id=?",
            (feature, paper_id),
        ).fetchone()
        is not None
    )
    return {"known": bool(known), "row": None, "body": None}


def _read(request, document):
    if _identity(request.database) != request.database_identity:
        raise ValueError("The captured database was replaced")
    owner = highlights.HighlightOwner(Path(request.database), request.paper_id, request.owner_json)
    digest = _source(request, document, verify_bytes=True)
    with closing(_connect(Path(request.database))) as conn:
        conn.execute("BEGIN")
        owner.check(conn)
        tables = _tables(conn)
        _rows(conn, tables, "chat", request.paper_id, ("body", "anchor"))
        if "research_chat_links" in tables:
            size = conn.execute(
                "SELECT COALESCE(sum(length(CAST(l.message_id AS BLOB))+"
                "length(CAST(l.exchange_id AS BLOB))+COALESCE(length(CAST(l.reply_to AS BLOB)),0)+"
                "COALESCE(length(CAST(l.source_hash AS BLOB)),0)),0) "
                "FROM research_chat_links l JOIN chat c ON c.id=l.local_id WHERE c.paper_id=?",
                (request.paper_id,),
            ).fetchone()[0]
            if size > MAX_BYTES:
                raise ValueError("Saved chat identities exceed their supported budget")
        if "research_chat_requests" in tables:
            count, size = conn.execute(
                "SELECT count(*),COALESCE(sum(length(CAST(context_json AS BLOB))+"
                "length(CAST(reason AS BLOB))),0) FROM research_chat_requests "
                "WHERE status IN ('prepared','candidate')"
            ).fetchone()
            if count > MAX_ROWS or size > MAX_BYTES:
                raise ValueError("Pending chat summaries exceed their supported budget")
        history = research_chat.history(conn, request.paper_id) if "chat" in tables else []
        chat = {
            "db_path": generation._path(conn),
            "database_identity": generation._identity(request.database),
            "binding": generation._binding(conn),
            "paper_id": request.paper_id,
            "parent_lifecycle": json.loads(owner._json)["parent"],
            "rows": [
                {"row": row, "observation": sync_capture.observe_content(conn, "chat", row)}
                for row in history
            ],
        }
        annotations = {
            feature: _annotation(conn, tables, request.paper_id, feature)
            for feature in ("highlight_analysis", "reading_links")
        }
        dives = _rows(conn, tables, "dives", request.paper_id, ("body",))
        close = _rows(conn, tables, "close_readings", request.paper_id, ("body",))
        records, marks = [], []
        if digest is not None:
            # Preserve the existing observed-edit rows and canonical hidden/source filters.
            records = highlights._read(conn, owner, digest)
            analysis = highlights._analysis(conn, request.paper_id)
            for record in records:
                anchor = json.loads(record["row"]["anchor"])
                from paper_daily.sync_content import validate_anchor

                validate_anchor(anchor)
            view = highlights.HighlightView(
                owner,
                document.path,
                digest,
                _json(records),
                _json(highlights._file_identity(document.path)),
                None,
                _json(analysis),
            )
            marks = view.marks
        observations = {
            name: sync_capture.observe_target(conn, "paper", request.paper_id, feature)
            for name, feature in (
                ("dives", "dive"),
                ("close_readings", "close_reading"),
                ("highlight_analysis", "highlight_analysis"),
                ("reading_links", "reading_links"),
            )
        }
        result = {
            "saved_observations": observations,
            "chat": chat,
            "pending": research_chat.pending_requests(conn, request.paper_id),
            "dives": dives,
            "close_readings": close,
            "annotations": annotations,
            "highlight_records": records,
            "marks": marks,
            "source": {"known": digest is not None, "document_hash": digest},
            "not_prepared": ["figures", "pdf_words", "legacy_cache_previews"],
        }
        owner.check(conn)
        packed = _json(result)
    if _identity(request.database) != request.database_identity:
        raise ValueError("The captured database was replaced")
    _source(request, document, verify_bytes=False)
    return packed


def read(request, *, document=None):
    """Read one immutable payload twice: exact rows/observations, not WAL timestamps."""
    worker_only()
    if not isinstance(request, SavedRequest):
        raise ValueError("A captured saved-reader request is required")
    first = _read(request, document)
    if _read(request, document) != first:
        raise ValueError("Saved research changed during preparation")
    return SavedSnapshot(request, first)


def current(snapshot, *, document=None):
    """Worker-only semantic revalidation; unchanged WAL checkpoints remain valid."""
    worker_only()
    if not isinstance(snapshot, SavedSnapshot):
        return False
    try:
        return read(snapshot.request, document=document).payload_json == snapshot.payload_json
    except (OSError, ValueError, sqlite3.Error):
        return False
