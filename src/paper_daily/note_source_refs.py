"""Bounded source intents for a displayed note; never external filesystem paths.

References are choices, not byte capabilities. Each new request resolves only
the recorded/reviewed/current digest of its exact typed note base. Native proofs
last only for one inspection and recheck graph/store/file ownership off the GUI.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change
from paper_daily.research_review import digest
from paper_daily.sync_files import closed, file_id
from paper_daily.sync_files import digest as hash_value
from paper_daily.sync_legacy_sources import path as safe_path

_SEAL = object()


def intents(data):
    """Pure displayed intent, explicitly not an assertion of file availability."""
    if data.get("origin") != "archived_note_resume":
        raise ValueError("Select a receiver note before choosing an original")
    expected = data["expected"]
    choice = expected.get("source_choice")
    values = {
        "recorded": choice["recorded_source"] if choice else data["source_hash"],
        "reviewed": choice["source"] if choice else None,
        "current": expected["document"]["sha256"] if expected["document"] else None,
    }
    return [
        dict(kind=kind, document_hash=value, availability="not_checked")
        for kind, value in values.items()
        if value is not None
    ]


def reference(value):
    closed(value, {"kind", "document_hash"})
    if not isinstance(value["kind"], str) or value["kind"] not in {
        "recorded",
        "reviewed",
        "current",
    }:
        raise ValueError("Choose a recorded, reviewed or current original reference")
    hash_value(value["document_hash"])
    return value


def _metadata(review, preview, ref):
    from paper_daily import note_source_mapping as mapping
    from paper_daily.document_reader import DocumentReader
    from paper_daily.sync_artifacts import desired_file
    from paper_daily.sync_source_files import FEATURE, _inspection_paths

    reference(ref)
    data = mapping._base(review, preview)
    if ref not in [{key: item[key] for key in ("kind", "document_hash")} for item in intents(data)]:
        raise ValueError("Original reference is not declared by this displayed note")
    expected = data["expected"]
    current = DocumentReader.from_workspace(review.path).resolve(expected["paper_id"])
    observed = (
        dict(
            sha256=current.sha256,
            path=str(current.path.resolve()),
            target=current.target,
            managed=current.managed,
        )
        if current.available
        else None
    )
    if observed != expected["document"]:
        raise ValueError("Currently selected original changed; review the receiver note again")
    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        client = conn._capture_client
        graph = client._optimistic_graph(conn)[0]
        parent = graph.get(("paper", expected["paper_sync_id"]))
        if not parent or not parent["active"]:
            raise ValueError("The note's paper is no longer active")
        identity = file_id(expected["paper_sync_id"], FEATURE, ref["document_hash"])
        original = graph.get(("research_file", identity))
        parents = [
            {"kind": "paper", "id": expected["paper_sync_id"], "incarnation": parent["incarnation"]}
        ]
        if original and (not original["active"] or original["parents"] != parents):
            raise ValueError("Deleted or retired original requires explicit restoration")
        operation = desired_file(conn, identity)
        registered = _inspection_paths(conn)
        review._check(conn)
    return data, current, client, operation, registered


def _adopted(review, data):
    from paper_daily.archived_review_drafts import _provenance_rows

    with closing(review._connect()) as conn:
        conn.execute("BEGIN")
        return any(
            row["record_id"] == data["id"] and digest(row) == data["record_hash"]
            for row, _size in _provenance_rows(conn)
        )


def _store_state(review, store, document_hash, *, require_binding=False):
    from paper_daily import local_blob_binding
    from paper_daily.sync_source_files import MAX_PDF_BYTES

    root = safe_path(store.root)
    index = safe_path(root / "index.sqlite")
    native = index.stat()
    wanted = (review.binding["workspace_id"], review.binding["device_id"], str(review.path))
    with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True, timeout=0.05)) as conn:
        conn.execute("BEGIN")
        declared = local_blob_binding._binding(conn, wanted)
        if require_binding and not declared:
            raise ValueError("Recovered source store needs its current receiver binding")
        row = conn.execute(
            "SELECT size,complete FROM blobs WHERE digest=?", (document_hash,)
        ).fetchone()
    after = index.stat()
    if (native.st_dev, native.st_ino) != (after.st_dev, after.st_ino):
        raise ValueError("Original store was replaced while inspecting it")
    if row is None:
        return None
    if type(row[0]) is not int or not 0 < row[0] <= MAX_PDF_BYTES or row[1] != 1:
        raise ValueError("Original store has no complete bounded source")
    return str(root), native.st_dev, native.st_ino, declared, row[0]


@dataclass(frozen=True, init=False)
class ReferenceProof:
    review: object = field(repr=False)
    preview: object = field(repr=False)
    _ref_json: str = field(repr=False)
    source: Path = field(repr=False)
    version: tuple = field(repr=False)
    route: str
    operation: object = field(repr=False)
    store_state: object = field(repr=False)
    receipt: object = field(repr=False)
    _seal: object = field(repr=False)

    @property
    def ref(self):
        return json.loads(self._ref_json)


def _resolve(review, preview, ref):
    from paper_daily import position_source_snapshots, source_snapshots, sync_source_files
    from paper_daily.sync_blobs import BlobManifest

    data, current, _client, operation, registered = _metadata(review, preview, ref)
    source, route, receipt, state = None, "legacy", None, None
    sha = ref["document_hash"]
    if ref["kind"] == "current":
        if not current.available or current.sha256 != sha:
            raise ValueError("The referenced current original is unavailable")
        source, route = current.path, "current"
    choice = data["expected"].get("source_choice")
    if source is None and choice and choice["action"] == "mapped" and choice["source"] == sha:
        row = choice["receipt"]
        receipt_path = source_snapshots.receipt_path(review.path, row)
        version = file_change.version(receipt_path)
        source, _native = position_source_snapshots.verify(review.path, row)
        if file_change.version(receipt_path) != version:
            raise ValueError("Private original receipt changed during inspection")
        receipt, route = (str(receipt_path), version), "private"
    if source is None and registered is not None:
        with closing(review._connect()) as conn:
            conn.execute("BEGIN")
            source = sync_source_files.inspectable(conn, data["expected"]["paper_sync_id"], sha)
        if source is not None:
            state, route = _store_state(review, registered[0], sha), "original"
            if state is None:
                raise ValueError("Owned original lost its complete source metadata")
        elif _adopted(review, data):
            state = _store_state(review, registered[0], sha, require_binding=True)
            if state is not None:
                source = registered[0].verified_path(BlobManifest(sha, state[-1]))
                route = "recovered"
    if source is None:
        from paper_daily.sync_legacy_sources import LegacySources

        with tempfile.TemporaryDirectory(prefix="paperfact-note-reference-") as temporary:
            finder = LegacySources([review.path.parent / "pdf"], temporary)
            finder.require(sha)
            # Only a freshly scanned alias under the fixed trusted root is used.
            # The staged copy can disappear after validation; no old path is read.
            source = next(path for path, value in finder.aliases.items() if value[0] == sha)
    source = safe_path(source)
    proof = object.__new__(ReferenceProof)
    for name, value in dict(
        review=review,
        preview=preview,
        _ref_json=json.dumps(ref, sort_keys=True),
        source=source,
        version=file_change.version(source),
        route=route,
        operation=digest(operation) if operation is not None else None,
        store_state=state,
        receipt=receipt,
        _seal=_SEAL,
    ).items():
        object.__setattr__(proof, name, value)
    check(proof, review, preview)
    return proof


def check(proof, review, preview):
    if (
        not isinstance(proof, ReferenceProof)
        or getattr(proof, "_seal", None) is not _SEAL
        or proof.review is not review
        or proof.preview != preview
    ):
        raise ValueError("Use this note's native inspected source reference")
    data, current, _client, operation, registered = _metadata(review, preview, proof.ref)
    if file_change.version(safe_path(proof.source)) != proof.version:
        raise ValueError("Referenced original bytes changed; inspect it again")
    if proof.route == "current" and (not current.available or current.path != proof.source):
        raise ValueError("Current source reference changed")
    if proof.route == "private":
        if file_change.version(safe_path(proof.receipt[0])) != proof.receipt[1]:
            raise ValueError("Private source reference receipt changed")
    elif proof.route in {"original", "recovered"}:
        if registered is None or (
            proof.route == "original"
            and (digest(operation) if operation else None) != proof.operation
        ):
            raise ValueError("Original source ownership changed")
        if proof.route == "recovered" and not _adopted(review, data):
            raise ValueError("Recovered original lost its complete historical owner")
        state = _store_state(
            review,
            registered[0],
            proof.ref["document_hash"],
            require_binding=proof.route == "recovered",
        )
        if state != proof.store_state:
            raise ValueError("Referenced original store binding or completeness changed")
    elif proof.route == "legacy" and not proof.source.is_relative_to(review.path.parent / "pdf"):
        raise ValueError("Legacy source reference escaped its trusted root")


def inspect(review, preview, ref, *, cancelled=lambda: False):
    from paper_daily import note_source_mapping

    note_source_mapping._cancel(cancelled)
    proof = _resolve(review, preview, ref)
    inspected = note_source_mapping.inspect(
        review, preview, proof.source, cancelled=cancelled, _reference=proof
    )
    if inspected.sha256 != ref["document_hash"]:
        raise ValueError("Referenced original differs from its declared digest")
    check(proof, review, preview)
    object.__setattr__(inspected, "reference", proof)
    return inspected
