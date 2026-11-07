"""Explicit private note/source choices, separate from historical attribution.

The native picker stages exactly its selected file. Persisted intent and private
receipt pairs survive restart/backup; only fresh typed and byte verification can
authorize a later canonical note/source transaction. No model or old-path reads.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, note_positions, source_snapshots
from paper_daily.research_review import digest, encode
from paper_daily.sync_files import closed
from paper_daily.sync_files import digest as hash_value
from paper_daily.sync_legacy_sources import path as safe_path

FORMAT = "paperfact.note-source-owner.v1"
_SEAL = object()


def choice_key(data, choice):
    expected = {key: value for key, value in data["expected"].items() if key != "source_choice"}
    expected["version"] = 1
    return digest(
        {
            "record": data["record_hash"],
            "scope": data["scope"],
            "expected": expected,
            "source": choice["source"],
            "page": choice["page"],
            "anchor": choice["anchor"],
        }
    )


def validate_choice(data):
    choice = data["expected"]["source_choice"]
    closed(choice, {"action", "recorded_source", "source", "page", "anchor", "receipt"})
    for key in ("recorded_source", "source"):
        if choice[key] is not None:
            hash_value(choice[key])
    if choice["action"] == "plain":
        if any(choice[key] is not None for key in ("source", "page", "anchor", "receipt")):
            raise ValueError("A plain manual note cannot retain a source position")
    elif choice["action"] == "retained":
        if choice["receipt"] is not None:
            raise ValueError("Historical choices cannot grant a new receiver's file ownership")
        if choice["source"] is None:
            if choice["page"] is not None or choice["anchor"] is not None:
                raise ValueError("Historical plain choices cannot retain a position")
        else:
            note_positions.validate(choice["anchor"])
            if (
                not isinstance(choice["anchor"], dict)
                or "selection" not in choice["anchor"]
                or choice["anchor"]["document_hash"] != choice["source"]
                or type(choice["page"]) is not int
                or choice["page"] != choice["anchor"]["p0"] + 1
            ):
                raise ValueError("Historical source choice needs its exact reviewed passage")
    elif choice["action"] == "mapped":
        note_positions.validate(choice["anchor"])
        if (
            choice["source"] is None
            or not isinstance(choice["anchor"], dict)
            or "selection" not in choice["anchor"]
            or choice["anchor"]["document_hash"] != choice["source"]
            or type(choice["page"]) is not int
            or choice["page"] != choice["anchor"]["p0"] + 1
        ):
            raise ValueError("A mapped note needs its reviewed source and passage")
        row = source_snapshots.validate(choice["receipt"])
        owner = json.loads(row["owner_json"])
        expected = data["expected"]
        wanted = {
            "format": FORMAT,
            "database_identity": expected["database_identity"],
            "binding": expected["binding"],
            "paper_id": expected["paper_id"],
            "source_owner_id": expected["paper_id"],
            "parent_lifecycle": expected["parent_lifecycle"],
            "draft_key": choice_key(data, choice),
        }
        if owner != wanted or row["sha256"] != choice["source"]:
            raise ValueError("Chosen original receipt belongs to another note observation")
    else:
        raise ValueError("Unsupported reviewed note source action")
    if data["source_hash"] != choice["source"] or any(
        data["retained"][key] != choice[key] for key in ("page", "anchor")
    ):
        raise ValueError("Reviewed note differs from its explicit source choice")
    return choice


def apply_choice(payload, choice):
    result = dict(payload)
    result.update(page=choice["page"], anchor=choice["anchor"])
    return result


def _base(review, preview):
    from paper_daily import archived_note_resume as notes

    data = review._verify_preview(preview)
    if data["origin"] != notes.ORIGIN:
        raise ValueError("Choose a receiver note before confirming its original")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        notes.check_base(review, conn, data)
    return data


def _cancel(cancelled):
    if cancelled():
        raise InterruptedError("Note source selection cancelled")


@dataclass(frozen=True, init=False)
class InspectedSource:
    review: object = field(repr=False)
    preview: object = field(repr=False)
    content: bytes = field(repr=False)
    sha256: str
    pages: int
    path: Path = field(repr=False)
    version: tuple = field(repr=False)
    _seal: object = field(repr=False)
    reference: object = field(default=None, repr=False)


def inspect(review, preview, selected, *, cancelled=lambda: False, _reference=None):
    """Worker-only native file selection; never accepts a decoded historical path."""
    import pymupdf

    from paper_daily.sync_documents import MAX_PDF_BYTES
    from paper_daily.sync_legacy_sources import validate_pdf

    _cancel(cancelled)
    _base(review, preview)
    source = safe_path(Path(selected).absolute())
    if _reference is not None:
        from paper_daily.note_source_refs import check

        check(_reference, review, preview)
        if _reference.source != source:
            raise ValueError("Source reference does not own this native file")
    if not source.is_file() or (source.suffix.lower() != ".pdf" and _reference is None):
        raise ValueError("Choose a readable local PDF file")
    with source.open("rb") as stream:
        version = file_change.version(source, stream=stream)
        if not 0 < version[2] <= MAX_PDF_BYTES:
            raise ValueError("Selected original exceeds its byte limit")
        content = stream.read(version[2] + 1)
        if file_change.version(source, stream=stream) != version:
            raise ValueError("Selected original changed while reading")
    _cancel(cancelled)
    if len(content) != version[2] or file_change.version(source) != version:
        raise ValueError("Selected original changed while reading")
    validate_pdf(content)
    with pymupdf.open(stream=content, filetype="pdf") as document:
        if document.needs_pass or document.page_count < 1:
            raise ValueError("Selected original is encrypted or has no readable pages")
        document.load_page(0)
        pages = document.page_count
    _base(review, preview)
    _cancel(cancelled)
    result = object.__new__(InspectedSource)
    for name, value in dict(
        review=review,
        preview=preview,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        pages=pages,
        path=source,
        version=version,
        _seal=_SEAL,
        reference=_reference,
    ).items():
        object.__setattr__(result, name, value)
    return result


def _inspection(review, preview, inspected):
    if (
        not isinstance(inspected, InspectedSource)
        or getattr(inspected, "_seal", None) is not _SEAL
        or inspected.review is not review
        or inspected.preview != preview
    ):
        raise ValueError("Use this note's actual inspected original")
    data = _base(review, preview)
    if file_change.version(inspected.path) != inspected.version:
        raise ValueError("Selected original changed; inspect it again")
    if inspected.reference is not None:
        from paper_daily.note_source_refs import check

        check(inspected.reference, review, preview)
    return data


def page(review, preview, inspected, page_index, *, cancelled=lambda: False):
    import pymupdf

    from paper_daily.pdf_selection_text import level_words

    _cancel(cancelled)
    _inspection(review, preview, inspected)
    if type(page_index) is not int or not 0 <= page_index < inspected.pages:
        raise ValueError("Choose a page in the inspected original")
    with pymupdf.open(stream=inspected.content, filetype="pdf") as document:
        words = [
            {"order": index, "text": word[4]} for index, word in level_words(document[page_index])
        ]
    if sum(len(word["text"].encode()) for word in words) > 1024 * 1024 or len(words) > 100000:
        raise ValueError("Selected page exceeds its text-selection limit")
    _inspection(review, preview, inspected)
    _cancel(cancelled)
    return {"page": page_index, "words": words, "document_hash": inspected.sha256}


def _mapped(data, choice):
    # Caller seals with its own review after validating the complete choice.
    data["expected"].update(version=2, source_choice=choice)
    data["retained"] = apply_choice(data["retained"], choice)
    data.update(
        source_hash=choice["source"],
        apply=False,
        resume_state="verification_required",
        reason="Source choice saved privately; verify it before confirming the note",
    )
    return data


def choose(review, preview, inspected, anchor, *, cancelled=lambda: False):
    import pymupdf

    from paper_daily import archived_note_resume as notes
    from paper_daily import position_source_snapshots as atomic
    from paper_daily.archived_draft_resume import _sealed

    _cancel(cancelled)
    data = _inspection(review, preview, inspected)
    with pymupdf.open(stream=inspected.content, filetype="pdf") as document:
        position = note_positions.select(document, anchor, inspected.sha256, cancelled=cancelled)
    old_choice = data["expected"].get("source_choice")
    choice = dict(
        action="mapped",
        recorded_source=old_choice["recorded_source"] if old_choice else data["source_hash"],
        source=inspected.sha256,
        page=position["p0"] + 1,
        anchor=position,
        receipt=None,
    )
    expected = data["expected"]
    owner = dict(
        format=FORMAT,
        database_identity=expected["database_identity"],
        binding=expected["binding"],
        paper_id=expected["paper_id"],
        source_owner_id=expected["paper_id"],
        parent_lifecycle=expected["parent_lifecycle"],
        draft_key=choice_key(data, choice),
    )
    row = dict(
        request_id="note-choice:" + digest(owner),
        owner_json=encode(owner),
        sha256=inspected.sha256,
        size=len(inspected.content),
        media_type="application/pdf",
    )
    choice["receipt"] = row
    _inspection(review, preview, inspected)
    _cancel(cancelled)
    # A complete private pair can outlive a failed draft save. It is archived as
    # provenance, never an active original or a research/sync operation.
    with review._file_apply_lock:
        _inspection(review, preview, inspected)
        atomic.publish(review.path, row, data=inspected.content)
        data = _mapped(data, choice)
        notes.validate_snapshot(
            data, {"path": str(review.path), "identity": review.identity, "binding": review.binding}
        )
        _cancel(cancelled)
        _base(review, _sealed(review, data))
        return _sealed(review, data)


def clear(review, preview):
    from paper_daily.archived_draft_resume import _sealed

    data = _base(review, preview)
    old_choice = data["expected"].get("source_choice")
    choice = dict(
        action="plain",
        recorded_source=old_choice["recorded_source"] if old_choice else data["source_hash"],
        source=None,
        page=None,
        anchor=None,
        receipt=None,
    )
    return _sealed(review, _mapped(data, choice))


@dataclass(frozen=True, init=False)
class ChosenOwner:
    database: Path = field(repr=False)
    identity: tuple
    binding: object = field(repr=False)
    receipt: dict = field(repr=False)
    files: tuple = field(repr=False)
    store_scope: object = field(repr=False)
    store_binding_present: bool
    _seal: object = field(repr=False)


def chosen_source(review, data):
    from paper_daily import position_source_snapshots as atomic

    choice = data["expected"].get("source_choice")
    if choice is None or choice["action"] != "mapped":
        return None, None
    validate_choice(data)
    row = choice["receipt"]
    receipt = source_snapshots.receipt_path(review.path, row)
    receipt_version = file_change.version(receipt)
    source, version = atomic.verify(review.path, row)
    if file_change.version(receipt) != receipt_version:
        raise ValueError("Chosen original receipt changed during verification")
    # verify() includes an exact receipt comparison and a byte hash; no old path.
    files = ((str(source), version), (str(receipt), file_change.version(receipt)))
    from paper_daily import local_blob_binding as local
    from paper_daily.sync_artifacts import paths
    from paper_daily.sync_blobs import BlobStore

    with closing(review._connect()) as conn:
        registered = paths(conn)
    store = registered[0] if registered else BlobStore(review.path.parent / "blobs")
    scope = local._store(store)
    wanted = (review.binding["workspace_id"], review.binding["device_id"], str(review.path))
    with closing(local._read(scope.index)) as conn:
        declared = local._binding(conn, wanted)
        local._store_current(scope, conn)
    result = object.__new__(ChosenOwner)
    for name, value in dict(
        database=review.path,
        identity=tuple(review.identity),
        binding=review.binding,
        receipt=row,
        files=files,
        store_scope=scope,
        store_binding_present=declared,
        _seal=_SEAL,
    ).items():
        object.__setattr__(result, name, value)
    return source, result


def check_owner(owner, review, prepared, client):
    if (
        not isinstance(owner, ChosenOwner)
        or getattr(owner, "_seal", None) is not _SEAL
        or owner.database != review.path
        or owner.identity != tuple(review.identity)
        or owner.binding != review.binding
        or prepared.database != review.path
        or (prepared.workspace, prepared.device)
        != (client.journal.workspace_id, client.journal.device_id)
        or prepared.store.root != owner.store_scope.root
        or json.loads(prepared.payload)["slot"] != owner.receipt["sha256"]
        or any(file_change.version(safe_path(path)) != version for path, version in owner.files)
    ):
        raise ValueError(
            "Chosen original private receipt or exact source changed; inspect it again"
        )

    from paper_daily import local_blob_binding as local

    wanted = (prepared.workspace, prepared.device, str(review.path))
    try:
        with closing(local._read(owner.store_scope.index)) as conn:
            conn.execute("BEGIN")
            local._store_current(owner.store_scope, conn)
            if local._binding(conn, wanted) != owner.store_binding_present:
                raise ValueError("Chosen original store ownership changed; verify it again")
            item = conn.execute(
                "SELECT size,complete FROM blobs WHERE digest=?", (owner.receipt["sha256"],)
            ).fetchone()
            if item is None or tuple(item) != (owner.receipt["size"], 1):
                raise ValueError("Chosen original store no longer has a complete exact source")
    except sqlite3.Error as error:
        raise ValueError("Chosen original store metadata is unavailable") from error
