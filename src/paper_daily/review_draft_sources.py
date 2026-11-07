"""Shared original-source staging for independently validated typed review bases."""

from __future__ import annotations

import tempfile
from contextlib import closing
from dataclasses import dataclass
from uuid import uuid4

from paper_daily.research_review import digest


@dataclass(frozen=True)
class SourceIntent:
    kind: str
    owner_id: str
    document: object


def key(data):
    return digest(
        {
            name: data[name]
            for name in (
                "origin",
                "id",
                "record_hash",
                "expected",
                "scope",
                "target",
                "parent_token",
                "parent_row",
                "retained",
                "source_hash",
            )
        }
    )


def check_document(document):
    if document is None:
        return
    from paper_daily.document_reader import document_current

    if document.available:
        if not document_current(document):
            raise ValueError("Currently selected PDF changed; your draft is retained")
    else:
        # Inspect is metadata-only and reports legacy "unchecked"; compare the
        # resolved state captured by callers, including missing/unconfigured.
        now = document._owner.resolve(document.local_id)
        if (now._target, now._context, now.status, now.reason) != (
            document._target,
            document._context,
            document.status,
            document.reason,
        ):
            raise ValueError("Currently selected PDF changed; your draft is retained")



def _owned_cached_source(review, client, store, document_hash):
    """Only a validated recovered draft may request independently owned cache bytes."""
    from paper_daily.review_cached_source import capture
    from paper_daily.sync_blobs import BlobManifest

    owner = capture(review, client, store, document_hash)
    if owner is None:
        return None, None
    return store.verified_path(BlobManifest(document_hash, owner.size)), owner


def check_owner(owner, review, prepared, client):
    from paper_daily.note_source_mapping import ChosenOwner
    from paper_daily.note_source_mapping import check_owner as check_chosen
    from paper_daily.review_cached_source import check

    if isinstance(owner, ChosenOwner):
        check_chosen(owner, review, prepared, client)
    else:
        check(owner, review, prepared, client)


def verify(review, preview, adapter, *, document_check=check_document):
    """Worker-only. The typed adapter must recheck its own actual displayed base."""
    from paper_daily.document_reader import DocumentReader
    from paper_daily.sync_artifacts import paths
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.sync_legacy_sources import LegacySources
    from paper_daily.sync_source_files import inspectable, prepare_source

    data = review._verify_preview(preview)
    with review._file_apply_lock:
        identity = key(data)
        # Explicit re-verification revokes any older application permission for
        # this same immutable preview before admitting replacement proofs.
        review._resume_sources.pop(identity, None)
        review._resume_documents.pop(identity, None)
        review._resume_cache_owners.pop(identity, None)
        with closing(review._connect()) as conn:
            conn.execute("BEGIN")
            expected = adapter.check_base(review, conn, data)
            intent = adapter.source_intent(expected)
            if not isinstance(intent, SourceIntent):
                raise ValueError("A typed current source intent is required")
            client = getattr(conn, "_capture_client", None)
            registered = paths(conn) if data["source_hash"] is not None else None
            paper = parent = source = cache_owner = None
            recovered = False
            if data["source_hash"] is not None:
                if client is None or intent.kind != "paper":
                    raise ValueError("Source-bound drafts require an enrolled paper workspace")
                mapping = conn.execute(
                    "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
                    (intent.owner_id,),
                ).fetchone()
                if mapping is None:
                    raise ValueError("Selected paper is not enrolled")
                paper = mapping[0]
                state = client._optimistic_graph(conn)[0].get(("paper", paper))
                if not state or not state["active"]:
                    raise ValueError("Selected paper is no longer active")
                parent = state["incarnation"]
                from paper_daily.sync_files import file_id
                from paper_daily.sync_source_files import FEATURE

                original = client._optimistic_graph(conn)[0].get(
                    ("research_file", file_id(paper, FEATURE, data["source_hash"]))
                )
                parents = [{"kind": "paper", "id": paper, "incarnation": parent}]
                if original and (not original["active"] or original["parents"] != parents):
                    raise ValueError("Deleted or retired original needs explicit restoration")
                source = inspectable(conn, paper, data["source_hash"])
                if source is None and registered is not None:
                    from paper_daily.archived_review_drafts import _provenance_rows

                    # Only an actual complete adopted backup authorizes this
                    # private-byte recovery route. A cache file alone cannot
                    # replace missing source evidence in an ordinary workspace.
                    recovered = any(
                        row["record_id"] == data["id"] and digest(row) == data["record_hash"]
                        for row, _size in _provenance_rows(conn)
                    )
        document, prepared = None, None
        if intent.kind == "paper":
            document = DocumentReader.from_workspace(review.path).resolve(intent.owner_id)
            observed = None
            if document.available:
                observed = {
                    "sha256": document.sha256,
                    "path": str(document.path.resolve()),
                    "target": document.target,
                    "managed": document.managed,
                }
            if observed != intent.document:
                raise ValueError(
                    "Currently selected PDF changed; explicitly review the target again"
                )
        if data["source_hash"] is not None:
            chooser = getattr(adapter, "chosen_source", None)
            if chooser is not None:
                chosen, owner = chooser(review, data)
                if chosen is not None:
                    source, cache_owner = chosen, owner
            if registered is None:
                store, version_root = (
                    BlobStore(review.path.parent / "blobs"),
                    review.path.parent / "research-versions",
                )
            else:
                store, version_root = registered
            with tempfile.TemporaryDirectory(prefix="paperfact-draft-source-") as temporary:
                if source is None and registered is not None and recovered:
                    source, cache_owner = _owned_cached_source(
                        review, client, store, data["source_hash"])
                if source is None:
                    finder = LegacySources([review.path.parent / "pdf"], temporary)
                    finder.require(data["source_hash"])
                    source = finder.objects[data["source_hash"]]
                prepared = prepare_source(
                    client,
                    paper,
                    source,
                    document_hash=data["source_hash"],
                    parent_incarnation=parent,
                    store=store,
                    version_root=version_root,
                    request_id=str(uuid4()),
                )
            with closing(review._connect()) as conn:
                conn.execute("BEGIN")
                adapter.check_base(review, conn, data)
                if not prepared.proof.matches(prepared.proof_operation):
                    raise ValueError("Original bytes changed during draft verification")
            validate = getattr(adapter, "validate_source", None)
            if validate is not None:
                validate(data, prepared)
        with closing(review._connect()) as conn:
            conn.execute("BEGIN")
            adapter.check_base(review, conn, data)
            document_check(document)
            if cache_owner is not None:
                check_owner(cache_owner, review, prepared, conn._capture_client)
        identity = key(data)
        if prepared is not None:
            review._resume_sources[identity] = prepared
        review._resume_documents[identity] = document
        if cache_owner is not None:
            review._resume_cache_owners[identity] = cache_owner
        while len(review._resume_documents) > 64:
            oldest = next(iter(review._resume_documents))
            review._resume_documents.pop(oldest)
            review._resume_sources.pop(oldest, None)
            review._resume_cache_owners.pop(oldest, None)
        data.update(
            apply=True,
            resume_state="ready",
            reason=(
                "Retained original verified; compare and confirm the selected target"
                if data["source_hash"] is not None
                else "No source PDF was recorded; review this as manual text and confirm the target"
            ),
        )
        from paper_daily.archived_draft_resume import _sealed

        return _sealed(review, data)


def publish_in(review, conn, data):
    """Caller has already checked its typed base; source/receipt share its commit."""
    from paper_daily.sync_source_files import publish_source_in

    identity = key(data)
    if identity not in review._resume_documents:
        raise ValueError("Verify the retained original in this session before applying")
    check_document(review._resume_documents[identity])
    if data["source_hash"] is not None:
        prepared = review._resume_sources.get(identity)
        if prepared is None:
            raise ValueError("Verify the retained original in this session before applying")
        owner = review._resume_cache_owners.get(identity)
        if owner is not None:
            check_owner(owner, review, prepared, conn._capture_client)
        publish_source_in(conn, conn._capture_client, prepared)


def require_verification(review, preview):
    """Demote only this displayed draft; preserve its base/body and perform no I/O."""
    from paper_daily.archived_draft_resume import _sealed
    from paper_daily.review_draft_resumption import ORIGINS

    data = review._verify_preview(preview)
    if data["origin"] not in ORIGINS:
        raise ValueError("Select a resumed draft")
    identity = key(data)
    review._resume_sources.pop(identity, None)
    review._resume_documents.pop(identity, None)
    review._resume_cache_owners.pop(identity, None)
    data.update(apply=False, resume_state="verification_required",
                reason="Verify the original again; your draft and displayed target are retained")
    return _sealed(review, data)
