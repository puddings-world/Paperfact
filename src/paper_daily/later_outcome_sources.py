"""Exact original-source adapter for typed later outcomes, never claim authority."""

from __future__ import annotations

import json
from contextlib import closing

from paper_daily import research_generation as generation
from paper_daily import source_snapshots
from paper_daily.sync_source_files import prepare_source, publish_source_in


def stage(context, row):
    if context.table != "paper_later_outcomes" or row["document_hash"] is None:
        return None
    data = context.data
    if data["binding"] is None:
        return None
    from paper_daily.sync_blobs import BlobStore
    from paper_daily.workspace_service import _binding, _paths, _tables

    receipt = next(
        (
            r
            for r in source_snapshots.list_owned(context.db_path)
            if r["request_id"] == context.request_id
        ),
        None,
    )
    if receipt is None or receipt["sha256"] != row["document_hash"]:
        raise ValueError("Later outcome has no exact retained original")
    owner = json.loads(receipt["owner_json"])
    parent = data["observation"]["parents"][0]
    if (
        owner["paper_id"] != context.owner_id
        or owner["parent_lifecycle"] != data["parent_lifecycle"]
        or owner["source_owner_id"] != parent["id"]
    ):
        raise ValueError("Later outcome original owner changed")
    with closing(generation._connect(context.db_path)) as conn:
        client = conn._capture_client
        blob_root, _legacy, registrations = _paths(
            conn, _tables(conn), _binding(conn, _tables(conn))
        )
    blobs = BlobStore(blob_root or context.db_path.parent / "blobs")
    roots = dict(registrations)
    version_root = (
        roots["research_file_paths"][2]
        if "research_file_paths" in roots
        else blobs.root / "research-versions"
    )
    return prepare_source(
        client,
        parent["id"],
        source_snapshots.source_path(context.db_path, receipt),
        document_hash=row["document_hash"],
        parent_incarnation=parent["incarnation"],
        store=blobs,
        version_root=version_root,
        request_id="later-source:" + context.request_id,
    )


def apply_in(conn, context, row, prepared):
    if prepared is None:
        return
    if (
        context.table != "paper_later_outcomes"
        or row["document_hash"] != context.data["document"]["sha256"]
    ):
        raise ValueError("Later source differs from captured outcome")
    publish_source_in(conn, conn._capture_client, prepared)
