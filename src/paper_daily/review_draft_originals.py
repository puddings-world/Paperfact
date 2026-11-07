"""Independent owned original reads shared by typed research drafts; no Apply authority."""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from paper_daily import file_change, research_review_drafts, sync_source_files
from paper_daily import resumed_draft_originals as reads
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.research_review import MAX_DETAIL, digest
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import digest as hash_value
from paper_daily.sync_files import file_id
from paper_daily.sync_legacy_sources import path as safe_path

_SEAL = object()


@dataclass(frozen=True, init=False)
class DraftReadProof:
    review: object = field(repr=False)
    preview: object = field(repr=False)
    reference: tuple | None = field(repr=False)
    domain: str
    document_hash: str
    signature: str = field(repr=False)
    source_path: Path = field(repr=False)
    data: bytes = field(repr=False)
    pages: int
    file_version: tuple = field(repr=False)
    natives: tuple = field(repr=False)
    indexes: tuple = field(repr=False)
    fence: tuple = field(repr=False)
    _seal: object = field(repr=False)

    def __reduce__(self):
        raise TypeError("Structured original read proofs are process-only")


def _adapter(domain):
    if domain == "claim_resume":
        from paper_daily import claim_draft_resume

        return claim_draft_resume
    if domain == "highlight_resume":
        from paper_daily import highlight_draft_resume

        return highlight_draft_resume
    raise ValueError("Select a supported structured original domain")


def _snapshot(service, conn, preview, reference, domain):
    shown = service._verify_preview(preview) if preview is not None else None
    if reference is None:
        if shown is None:
            raise ValueError("Use a native typed preview or exact saved draft reference")
        return shown, digest(shown)
    if (
        type(reference) is not tuple
        or len(reference) != 2
        or not isinstance(reference[0], str)
        or str(UUID(reference[0])) != reference[0]
        or type(reference[1]) is not int
        or not 1 <= reference[1] <= 2**63 - 1
    ):
        raise ValueError("Use an exact saved structured draft ID and revision")
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_review_drafts'"
    ).fetchone():
        raise ValueError("Save the private structured draft before reading its original")
    lengths = conn.execute(
        "SELECT length(CAST(body AS BLOB)),length(CAST(preview_json AS BLOB))"
        "+length(CAST(owner_json AS BLOB)) FROM research_review_drafts "
        "WHERE draft_id=? AND revision=?",
        reference,
    ).fetchone()
    from paper_daily.annotation_content import MAX_BYTES

    if (
        lengths is None
        or type(lengths[0]) is not int
        or type(lengths[1]) is not int
        or lengths[0] > MAX_BYTES
        or lengths[1] > MAX_DETAIL
    ):
        raise ValueError("Private structured draft changed or exceeds its read limit")
    row = dict(
        conn.execute(
            "SELECT * FROM research_review_drafts WHERE draft_id=? AND revision=?", reference
        ).fetchone()
    )
    research_review_drafts.validate_record(row)
    owner = dict(path=str(service.path), identity=service.identity, binding=service.binding)
    if row["origin"] != domain or json.loads(row["owner_json"]) != owner:
        raise ValueError("Private structured draft belongs to another native owner")
    saved = json.loads(row["preview_json"])
    if shown is not None and any(
        shown[key] != saved[key] for key in ("origin", "id", "source_hash", "retained", "target")
    ):
        raise ValueError("Displayed structured draft differs from the saved source reference")
    return saved, row["fingerprint"]


def _information(service, preview, reference, sha, domain):
    adapter = _adapter(domain)
    with closing(reads._connect(service)) as conn:
        conn.execute("BEGIN")
        service._check(conn)
        if service.recovery or service.binding is None or conn._capture_client is None:
            raise ValueError("Original inspection requires this editable managed workspace")
        data, private = _snapshot(service, conn, preview, reference, domain)
        if data["origin"] != domain or data["source_hash"] != sha:
            raise ValueError("Original is outside this declared structured draft")
        owner = dict(path=str(service.path), identity=service.identity, binding=service.binding)
        expected = adapter.validate_snapshot(data, owner)
        origin, identity = adapter._reference(data["id"])
        record = service._record(conn, origin, identity)
        baseline, _original, _body = adapter._scientific(conn, origin, identity, record)
        if baseline != data["retained"]:
            raise ValueError("The declared retained claim source changed")
        paper = expected["paper_id"]
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (paper,)
        ).fetchone()
        client = conn._capture_client
        graph = client._optimistic_graph(conn)[0]
        parent = graph.get(("paper", expected["paper_sync_id"]))
        if (
            mapping is None
            or mapping[0] != expected["paper_sync_id"]
            or not parent
            or not parent["active"]
            or parent_lifecycle(conn, "paper", paper) != expected["parent_lifecycle"]
        ):
            raise ValueError("Structured original parent identity or lifetime changed")
        identity = file_id(mapping[0], sync_source_files.FEATURE, sha)
        state = graph.get(("research_file", identity))
        parents = [dict(kind="paper", id=mapping[0], incarnation=parent["incarnation"])]
        if state and (not state["active"] or state["parents"] != parents):
            raise ValueError("The declared original was deleted or retired")
        registered = sync_source_files._inspection_paths(conn)
        if registered is None:
            raise ValueError("Original source storage is unavailable")
        store, _versions = registered
        paths = conn.execute(
            "SELECT workspace,blob_root,version_root FROM research_file_paths WHERE id=1"
        ).fetchone()
        source = sync_source_files.inspectable(conn, mapping[0], sha)
        operation = desired_file(conn, identity)
        cache = None
        if source is None:
            from paper_daily.archived_review_drafts import _provenance_rows
            from paper_daily.review_cached_source import capture

            # Only complete adopted history grants access to its private immutable bytes.
            recovered = origin == "archived_draft" and any(
                row["record_id"] == data["id"] and digest(row) == data["record_hash"]
                for row, _size in _provenance_rows(conn)
            )
            if not recovered or operation is not None:
                raise ValueError("Declared original is not independently available on this device")
            observed = capture(service, client, store, sha)
            if observed is None:
                raise ValueError("Recovered original is unavailable in its owned private store")
            source = store.verified_path(BlobManifest(sha, observed.size))
            cache = (str(observed.index), observed.native, observed.binding, observed.size)
        source = safe_path(source)
        signature = digest(
            dict(
                private=private,
                source=str(source),
                operation=operation,
                cache=cache,
                paths=tuple(paths),
                paper=mapping[0],
                epoch=expected["parent_lifecycle"],
            )
        )
        service._check(conn)
        return source, signature, store.root


def prepare(service, preview, document_hash, *, domain, reference=None, cancelled=lambda: False):
    """Worker-only read: no source staging, schema, current-PDF activation or write grant."""
    hash_value(document_hash)
    reads._check(cancelled)
    source, signature, root = _information(service, preview, reference, document_hash, domain)
    indexes = (service.path, root / "index.sqlite")
    fence = reads._fence(indexes)
    natives = tuple(
        (path, reads._native(path))
        for path in (service.path, root, root / "objects", root / "index.sqlite")
    )
    version = file_change.version(source)
    size = source.stat().st_size
    if not 0 < size <= MAX_PDF_BYTES:
        raise ValueError("Original PDF exceeds its read bound")
    with source.open("rb") as stream:
        data = stream.read(size + 1)
    if (
        len(data) != size
        or hashlib.sha256(data).hexdigest() != document_hash
        or file_change.version(source) != version
    ):
        raise ValueError("Original source bytes changed during reading")
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("Original is not a readable PDF")
        pages = pdf.page_count
    reads._check(cancelled)
    again = _information(service, preview, reference, document_hash, domain)
    if again != (source, signature, root) or reads._fence(indexes) != fence:
        raise ValueError("Original read metadata changed; retry the same source")
    proof = object.__new__(DraftReadProof)
    for key, value in dict(
        review=service,
        preview=preview,
        reference=reference,
        domain=domain,
        document_hash=document_hash,
        signature=signature,
        source_path=source,
        data=data,
        pages=pages,
        file_version=version,
        natives=natives,
        indexes=indexes,
        fence=fence,
        _seal=_SEAL,
    ).items():
        object.__setattr__(proof, key, value)
    if gui_status(proof) != "ready":
        raise ValueError("Original changed before delivery")
    return proof


def gui_status(proof):
    """Bounded native admission only; no SQL, PDF parsing or hashing on the GUI thread."""
    if (
        not isinstance(proof, DraftReadProof)
        or getattr(proof, "_seal", None) is not _SEAL
        or proof.review.closed
        or getattr(proof, "domain", None) not in {"claim_resume", "highlight_resume"}
    ):
        return "revoked"
    try:
        if any(reads._native(path) != identity for path, identity in proof.natives):
            return "revoked"
        if file_change.version(safe_path(proof.source_path)) != proof.file_version:
            return "revoked"
        return "ready" if reads._fence(proof.indexes) == proof.fence else "recheck"
    except (OSError, ValueError):
        return "revoked"


def revalidate(proof, *, cancelled=lambda: False):
    if not isinstance(proof, DraftReadProof) or getattr(proof, "_seal", None) is not _SEAL:
        raise ValueError("Use an actual structured original read proof")
    if gui_status(proof) == "revoked":
        raise ValueError("Original read owner or bytes changed")
    result = prepare(
        proof.review,
        proof.preview,
        proof.document_hash,
        domain=proof.domain,
        reference=proof.reference,
        cancelled=cancelled,
    )
    if result.signature != proof.signature:
        raise ValueError("Original read scope changed; retain text and reopen its source")
    return result
