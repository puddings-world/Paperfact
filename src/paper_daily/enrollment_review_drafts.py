"""Closed private draft history; historical previews never become live authority."""

from __future__ import annotations

from paper_daily.sync_files import closed, digest


def _json_columns(row):
    from paper_daily.enrollment_history import _value

    if row is not None:
        if not isinstance(row, dict):
            raise ValueError("Invalid archived draft SQL snapshot")
        for key, value in row.items():
            if key.endswith("_json") and value is not None:
                _value(value)


def _reference(value):
    from paper_daily.sync_journal import _identifier

    closed(value, {"kind", "id", "incarnation"})
    if value["kind"] not in ("paper", "list", "membership"):
        raise ValueError("Invalid archived draft parent kind")
    _identifier(value["id"])
    _identifier(value["incarnation"])


def _state(value):
    from paper_daily.sync_journal import _identifier

    if value is None:
        return
    closed(value, {"incarnation", "structure_revision", "active", "parents"})
    _identifier(value["incarnation"])
    if (
        type(value["active"]) is not bool
        or type(value["structure_revision"]) is not int
        or value["structure_revision"] < 0
    ):
        raise ValueError("Invalid archived draft graph state")
    if not isinstance(value["parents"], list) or len(value["parents"]) > 3:
        raise ValueError("Invalid archived draft graph parents")
    seen = set()
    for ref in value["parents"]:
        _reference(ref)
        key = (ref["kind"], ref["id"])
        if key in seen:
            raise ValueError("Duplicate archived draft graph parent")
        seen.add(key)


def _payload(operation, payload):
    """Validate a displayed payload using its declared closed operation type."""
    from paper_daily.sync_journal import canonical_operation

    if payload is None:
        return set()
    canonical_operation({**operation, "action": "put" if payload else "delete", "payload": payload})
    sources = set()
    if payload.get("source_document_hash") is not None:
        sources.add(payload["source_document_hash"])
    anchor = payload.get("anchor")
    if isinstance(anchor, dict) and anchor.get("document_hash") is not None:
        sources.add(anchor["document_hash"])
    return sources


def _remote(snapshot, owner):
    from paper_daily.enrollment_history import _value
    from paper_daily.sync_journal import _identifier, canonical_operation

    expected = snapshot["expected"]
    incoming = expected["event"]["operation"]
    workspace = owner["binding"]["workspace_id"]
    if type(expected["outstanding"]) is not bool:
        raise ValueError("Invalid archived draft pending observation")
    if expected["resolved_by"] is not None:
        _identifier(expected["resolved_by"])
    _state(expected["state"])
    head = expected["head"]
    current = None
    sources = set()
    if head is not None:
        closed(head, {"revision", "operation"})
        if type(head["revision"]) is not int or head["revision"] < 0:
            raise ValueError("Invalid archived draft head revision")
        if head["operation"] is not None:
            operation = _value(head["operation"])
            canonical_operation(operation)
            if any(
                operation[key] != incoming[key]
                for key in ("workspace_id", "entity_type", "entity_id")
            ):
                raise ValueError("Archived draft head belongs to another target")
            current = operation["payload"]
            sources.update(_payload(operation, current))
    if (
        incoming["workspace_id"] != workspace
        or snapshot["scope"] != {"kind": incoming["entity_type"], "id": incoming["entity_id"]}
        or snapshot["current"] != current
    ):
        raise ValueError("Archived draft displayed conflict differs from its target")
    refs = (expected["state"] or incoming).get("parents", [])
    parents = expected["parents"]
    if not isinstance(parents, list) or len(parents) != len(refs):
        raise ValueError("Invalid archived draft parent observation")
    for parent, ref in zip(parents, refs, strict=True):
        closed(parent, {"ref", "current"})
        _reference(parent["ref"])
        if parent["ref"] != ref:
            raise ValueError("Archived draft parent reference changed")
        _state(parent["current"])
    for key in ("original", "current", "retained"):
        sources.update(_payload(incoming, snapshot[key]))
    if any(snapshot[key] is not None for key in ("target", "parent_token", "parent_row")):
        raise ValueError("Unknown archived conflict target authority")
    return sources


def source_hashes(row):
    """Keep exact draft text/JSON and enumerate declared originals without old-path I/O."""
    from paper_daily import research_generation as generation
    from paper_daily import research_review_drafts as drafts
    from paper_daily.enrollment_history import _snapshot, _value, generation_sources
    from paper_daily.research_review import encode

    closed(row, drafts.COLUMNS)
    if any(
        not isinstance(value, str)
        for key, value in row.items()
        if key not in {"revision", "save_order"}
    ):
        raise ValueError("Invalid archived draft scalar")
    owner, snapshot = _value(row["owner_json"]), _value(row["preview_json"])
    closed(snapshot, drafts.SNAPSHOT)
    if row["origin"] in {"generation", "sidecar", "archived_resume"}:
        _value(snapshot["expected"])
    elif isinstance(snapshot["expected"], dict):
        head = snapshot["expected"].get("head")
        if isinstance(head, dict) and head.get("operation") is not None:
            _value(head["operation"])
    drafts.validate_record(row)
    sources = {snapshot["source_hash"]} if snapshot["source_hash"] is not None else set()
    if row["origin"] == "remote":
        sources.update(_remote(snapshot, owner))
        return sources
    if row["origin"] == "highlight_resume":
        from paper_daily.highlight_draft_resume import source_hashes as highlight_sources

        sources.update(highlight_sources(snapshot, owner))
        return sources
    if row["origin"] == "claim_resume":
        from paper_daily.claim_draft_resume import source_hashes as claim_sources

        sources.update(claim_sources(snapshot, owner))
        return sources
    if row["origin"] == "archived_note_resume":
        from paper_daily.archived_note_resume import source_hashes as note_sources

        sources.update(note_sources(snapshot, owner))
        return sources
    data = generation.GenerationContext(snapshot["expected"]).data
    for key in ("original", "current", "retained"):
        _json_columns(snapshot[key])
    sources.update(
        generation_sources(
            {
                "request_id": data["request_id"],
                "context_json": snapshot["expected"],
                "row_json": encode(snapshot["retained"]),
                "status": "accepted",
                "candidate_id": None,
                "reason": "private historical draft validation only",
            }
        )
    )
    original = snapshot["original"]
    if original is not None:
        column = generation.REGISTRY[data["table"]][1]
        sources.update(_snapshot(data["table"], original, original.get(column)))
    kind = generation.REGISTRY[data["table"]][0]
    sources.update(
        _snapshot(
            "papers" if kind == "paper" else "lists", snapshot["parent_row"], data["owner_id"]
        )
    )
    if snapshot["target"] is not None:
        closed(snapshot["target"], {"id", "title"})
        if snapshot["target"]["id"] != data["owner_id"] or not isinstance(
            snapshot["target"]["title"], str
        ):
            raise ValueError("Invalid archived draft displayed target")
    for source in sources:
        digest(source)
    return sources
