"""Archive exact selected originals before Lineage calls; no active owner grant."""

from __future__ import annotations

import re
from pathlib import Path

from paper_daily import (
    claim_content,
    lineage_content,
    lineage_sets,
    research_lineage,
    source_snapshots,
)
from paper_daily import position_source_snapshots as atomic_sources

FORMAT = source_snapshots.LINEAGE_FORMAT


def validate_owner(owner, row):
    """Serialized observation only, never permission to publish research."""
    for name in ("corpus_id", "generation_request_id"):
        lineage_sets.uuid(owner[name])
    claim_content.digest(owner["source_id"])
    identity = owner["source_identity"]
    claim_content.closed(identity, lineage_content.IDENTITY_FIELDS)
    claim_content.text(identity["title"], 2000)
    for name in lineage_content.IDENTITY_FIELDS - {"title"}:
        claim_content.text(identity[name], 1000, nullable=True)
    if owner["source_id"] != lineage_content.source_id(identity, row["sha256"]):
        raise ValueError("Lineage observation differs from its selected source identity")
    if (owner["paper_id"] == owner["focal_paper_id"] and
            owner["parent_lifecycle"] != owner["focal_lifecycle"]):
        raise ValueError("Lineage focal and source lifecycle observations disagree")
    claim_content.text(owner["focal_paper_id"], 4096)
    if not isinstance(owner["focal_lifecycle"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", owner["focal_lifecycle"]
    ):
        raise ValueError("Invalid lineage focal lifecycle observation")
    if row["request_id"] != "lineage:" + claim_content.hashed(
        [owner, row["sha256"], row["size"]]
    ):
        raise ValueError("Lineage source observation differs from its exact request")


def retain(corpus, *, corpus_id, request_id, cancelled=lambda: False):
    """Worker-only durable private pairs; retry never grants a claim or graph owner.

    All available originals are retained before a model call. Missing selected
    peers have no receipt. Partial/cancelled staging can leave complete archive
    pairs, which are safe to back up but are never active research authority.
    """
    from paper_daily.lineage_jobs import _worker

    _worker()
    lineage_sets.uuid(corpus_id)
    lineage_sets.uuid(request_id)
    data = research_lineage._checked(corpus)
    research_lineage.current(corpus)
    database = Path(data["database"])
    focal = data["observed"][0]
    selected = []
    for source, prior, snapshot in zip(
        corpus.sources, data["observed"], corpus._snapshots, strict=True
    ):
        if cancelled():
            raise research_lineage.LineageError("cancelled")
        if snapshot is None:
            continue
        metadata, raw = research_lineage.evidence._checked_snapshot(snapshot)
        owner = dict(
            format=FORMAT, database_identity=data["database_identity"], binding=data["binding"],
            paper_id=prior["local_id"], parent_lifecycle=prior["lifecycle"],
            source_owner_id=metadata["paper_id"], corpus_id=corpus_id,
            generation_request_id=request_id, source_id=source["id"],
            source_identity=source["identity"],
            focal_paper_id=focal["local_id"], focal_lifecycle=focal["lifecycle"],
        )
        row = dict(
            request_id="lineage:" + claim_content.hashed(
                [owner, source["document_hash"], len(raw)]),
            owner_json=research_lineage._json(owner), sha256=source["document_hash"],
            size=len(raw), media_type="application/pdf",
        )
        source_snapshots.validate(row)
        selected.append((row, raw))
    # Preflight all typed observations before publishing even the first pair.
    for row, raw in selected:
        if cancelled():
            raise research_lineage.LineageError("cancelled")
        research_lineage.current(corpus)
        atomic_sources.publish(database, row, data=raw)
    if cancelled():
        raise research_lineage.LineageError("cancelled")
    research_lineage.current(corpus)
    return [row for row, _raw in selected]
