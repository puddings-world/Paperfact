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


# These are display-only snapshots. They neither adopt a cache nor authorize a
# source jump/publication. All bytes stay immutable after the worker returns.
MAX_PREVIEW_ASSETS = 128
MAX_PREVIEW_BYTES = 24 * 1024 * 1024
MAX_PREVIEW_INDEX = 1024 * 1024


@dataclass(frozen=True)
class PreviewRequest:
    root: Path
    options: tuple
    frame: object = None
    source: object = None
    records_json: str | None = None


@dataclass(frozen=True)
class PreviewSnapshot:
    figures: tuple
    revisions: tuple
    notice: str = ""


def capture_preview(root, options, frame=None):
    """Metadata only; capture an existing owned frame, never read a cache here."""
    from paper_daily.desktop.figure_loading import Worker

    source, records = None, None
    if (
        type(frame) is Worker
        and frame.mode == "extract"
        and frame.success
        and frame.ready_emitted
        and frame.source is not None
        and len(frame.figures) <= MAX_PREVIEW_ASSETS
    ):
        source = frame.source
        records = _json(
            [
                dict(
                    label=f.label,
                    caption=f.caption,
                    page=f.page,
                    file=f.path.name,
                    kind=f.kind,
                    **f.meta,
                )
                for f in frame.figures
            ]
        )
    return PreviewRequest(
        Path(root).resolve(), tuple(sorted(options.items())), frame, source, records
    )


def _preview_version(path):
    return file_change.version(path) if path.is_file() else None


def preview_current(preview):
    """Bounded native metadata only; bytes and parsing remain worker-only."""
    try:
        return all(
            path.resolve() == resolved and _preview_version(path) == revision
            for path, revision, resolved in preview.revisions
        )
    except (OSError, ValueError):
        return False


def _preview_bytes(path, root, revision, limit):
    """Admit the resolved name and actual opened stream before reading content."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Preview file escaped its captured cache")
    with path.open("rb") as stream:
        if file_change.version(path, stream=stream) != revision or path.resolve() != resolved:
            raise ValueError("Opened preview differs from its captured file")
        blob = stream.read(limit + 1)
        if (
            len(blob) != revision[2]
            or file_change.version(path, stream=stream) != revision
            or path.resolve() != resolved
        ):
            raise ValueError("Preview file changed during its bounded read")
    if _preview_version(path) != revision:
        raise ValueError("Preview file changed after reading")
    return blob, resolved


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate preview field")
        result[name] = value
    return result


def read_preview(snapshot, request, *, document=None, cancelled=lambda: False):
    """Read bounded cache content, explicitly unverified unless an actual frame owns it.

    A matching manifest SHA is consistency, not proof of original provenance.
    Unknown/legacy previews stay readable with no original page/source action.
    """
    import base64
    import math
    import struct

    from paper_daily import figures

    worker_only()
    if not isinstance(snapshot, SavedSnapshot) or not isinstance(request, PreviewRequest):
        raise ValueError("Captured saved content and preview intent are required")
    data = snapshot.data
    if not data["dives"] or not data["close_readings"]:
        return PreviewSnapshot((), ())
    digest = data["source"]["document_hash"]
    managed = document is not None and document.managed
    options = dict(request.options)
    encoded = json.dumps(options, sort_keys=True, separators=(",", ":"))
    relative = (
        Path("documents")
        / digest
        / ("figures-v1-" + hashlib.sha256(encoded.encode()).hexdigest()[:24])
        if managed and digest
        else Path(figures._safe(snapshot.request.paper_id))
    )
    folder = (request.root / relative).resolve()
    if not folder.is_relative_to(request.root):
        raise ValueError("Preview cache escaped its captured root")
    index = folder / "index.json"
    revisions, result = [], []
    verified = False
    try:
        if request.source is not None and request.records_json is not None:
            source = request.source
            if (
                source.document is not document
                or source.view.owner.database != Path(snapshot.request.database)
                or source.view.owner.paper_id != snapshot.request.paper_id
                or source.view.owner._json != snapshot.request.owner_json
                or source.view.fingerprint != digest
            ):
                raise ValueError("Owned figure frame differs from the captured original")
            figures.loaded_current(source)
            rows = json.loads(request.records_json)
            verified = True
        else:
            if not index.resolve().is_relative_to(folder):
                raise ValueError("Preview index escaped its captured cache")
            revision = _preview_version(index)
            if revision is None:
                return PreviewSnapshot(
                    (), (), "Cached figures are unavailable; saved text is unchanged."
                )
            if not 0 < revision[2] <= MAX_PREVIEW_INDEX:
                raise ValueError("Preview index exceeds its budget")
            raw, resolved_index = _preview_bytes(index, folder, revision, MAX_PREVIEW_INDEX)
            rows = json.loads(raw, object_pairs_hook=_unique_pairs)
            revisions.append((index, revision, resolved_index))
        if not isinstance(rows, list) or len(rows) > MAX_PREVIEW_ASSETS:
            raise ValueError("Preview figure count exceeds its budget")
        used, total = set(), 0
        for item in rows:
            if cancelled():
                return PreviewSnapshot((), (), "Figure preview was cancelled.")
            required = {"label", "caption", "page", "file", "kind"}
            allowed = required | {"rect", "document_hash", "cache_key", "asset_sha256"}
            if not isinstance(item, dict) or not required <= item.keys() or item.keys() - allowed:
                raise ValueError("Malformed figure preview")
            label, caption, name = item["label"], item["caption"], item["file"]
            if (
                not isinstance(label, str)
                or not 0 < len(label) <= 1000
                or not isinstance(caption, str)
                or len(caption) > 20000
                or not isinstance(name, str)
                or Path(name).name != name
                or not name.lower().endswith(".png")
                or name in used
                or type(item["page"]) is not int
                or not 1 <= item["page"] <= 100000
                or item["kind"] not in ("figure", "table")
            ):
                raise ValueError("Malformed figure preview")
            used.add(name)
            if "rect" in item and (
                not isinstance(item["rect"], list)
                or len(item["rect"]) != 4
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in item["rect"])
            ):
                raise ValueError("Malformed preview region")
            tagged = item.get("document_hash")
            if tagged is not None and (
                not isinstance(tagged, str)
                or len(tagged) != 64
                or any(c not in "0123456789abcdef" for c in tagged)
                or (digest is not None and tagged != digest)
            ):
                raise ValueError("Preview belongs to another original")
            if managed and tagged != digest:
                raise ValueError("Managed preview has no matching original binding")
            if "cache_key" in item and item["cache_key"] != relative.as_posix():
                raise ValueError("Preview cache binding changed")
            path = (folder / name).resolve()
            if not path.is_relative_to(folder):
                raise ValueError("Preview path escaped its captured cache")
            revision = _preview_version(path)
            if revision is None or not 0 < revision[2] <= MAX_PREVIEW_BYTES:
                raise ValueError("Preview image is missing or exceeds its budget")
            total += revision[2]
            if total > MAX_PREVIEW_BYTES:
                raise ValueError("Preview images exceed their total budget")
            blob, resolved_asset = _preview_bytes(path, folder, revision, MAX_PREVIEW_BYTES)
            expected = item.get("asset_sha256")
            if expected is not None and (
                not isinstance(expected, str) or hashlib.sha256(blob).hexdigest() != expected
            ):
                raise ValueError("Preview bytes differ from the declared snapshot")
            if verified and expected is None:
                raise ValueError("Owned preview has no generated digest")
            if len(blob) < 24 or blob[:8] != b"\x89PNG\r\n\x1a\n" or blob[12:16] != b"IHDR":
                raise ValueError("Preview image is not a supported PNG")
            width, height = struct.unpack(">II", blob[16:24])
            if width <= 0 or height <= 0 or width * height > 32_000_000:
                raise ValueError("Preview dimensions exceed their budget")
            result.append(
                figures.Figure(
                    snapshot.request.paper_id,
                    label,
                    caption,
                    item["page"],
                    path,
                    item["kind"],
                    dict(
                        preview_data_url="data:image/png;base64,"
                        + base64.b64encode(blob).decode("ascii"),
                        preview_unverified=not verified,
                        preview_width=width,
                    ),
                )
            )
            revisions.append((path, revision, resolved_asset))
        preview = PreviewSnapshot(tuple(result), tuple(revisions))
        if not preview_current(preview):
            raise ValueError("Preview closure changed")
        if verified:
            figures.loaded_current(request.source)
        return preview
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return PreviewSnapshot(
            (),
            (),
            "Cached figures could not be checked (missing, malformed, changed, mismatched, "
            "or over budget); saved text is unchanged. Reopen to retry.",
        )
