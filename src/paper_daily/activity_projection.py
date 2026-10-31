"""Bounded read-only suggestions from received research, never viewport telemetry."""

from __future__ import annotations

import json
import re

from paper_daily.sync_client import validate_event

WINDOW = 200
HASH = re.compile(r"[0-9a-f]{64}\Z")


def _key(operation):
    return operation["entity_type"], operation["entity_id"]


def graph_active(graph, key, trail=()):
    if key in trail or len(trail) >= 8:
        return False
    row = graph.get(key)
    if not row or row.get("active") is not True:
        return False
    return all(
        graph.get((parent["kind"], parent["id"]), {}).get("incarnation") == parent["incarnation"]
        and graph_active(graph, (parent["kind"], parent["id"]), (*trail, key))
        for parent in row["parents"]
    )


def _paper(operation):
    if operation["entity_type"] == "paper":
        return operation["entity_id"]
    payload = operation["payload"]
    if isinstance(payload.get("paper_id"), str):
        return payload["paper_id"]
    scope = payload.get("scope", {})
    if scope.get("kind") == "paper":
        return scope["id"]
    return next((p["id"] for p in operation.get("parents", []) if p["kind"] == "paper"), None)


def _same(left, right):
    return json.dumps(left, sort_keys=True, separators=(",", ":")) == json.dumps(
        right, sort_keys=True, separators=(",", ":")
    )


def _resume(operation, note, pending):
    if pending or not note or operation["entity_type"] != "note":
        return None
    anchor = operation["payload"].get("anchor")
    if not isinstance(anchor, dict):
        return None
    source = anchor.get("document_hash")
    if not isinstance(source, str) or HASH.fullmatch(source) is None:
        return None
    if note["paper_id"] != operation["payload"]["paper_id"] or not _same(note["anchor"], anchor):
        return None
    return {"note_id": operation["entity_id"], "source_hash": source, "anchor": anchor}


def project_activity(
    *,
    workspace_id,
    device_id,
    cursor,
    events,
    heads,
    graph,
    papers,
    notes,
    pending=(),
    file_bindings=(),
    resolved=(),
    recent_limit=50,
    continue_limit=20,
    has_more=False,
):
    """Inputs are one existing workspace snapshot. Outputs grant no write authority.

    Applied file bindings are records, not current byte availability proofs.
    Historical accepted rows are not claimed to have ever materialized locally.
    """
    if (
        type(cursor) is not int
        or cursor < 0
        or not isinstance(events, list)
        or len(events) > WINDOW
        or type(recent_limit) is not int
        or not 1 <= recent_limit <= 100
        or type(continue_limit) is not int
        or not 1 <= continue_limit <= 50
    ):
        raise ValueError("Invalid bounded activity window")
    pending, file_bindings, resolved = set(pending), set(file_bindings), set(resolved)
    recent, continuation, seen_papers, seen_sequences = [], [], set(), set()
    for event in sorted(events, key=lambda item: item["sequence"], reverse=True):
        validate_event(event, workspace_id)
        sequence, operation = event["sequence"], event["operation"]
        if sequence > cursor or sequence in seen_sequences:
            raise ValueError("Activity history differs from its received cursor")
        seen_sequences.add(sequence)
        key = _key(operation)
        head = heads.get(key)
        current = bool(head and head["revision"] == sequence)
        active = graph_active(graph, key)
        applied = bool(current and head["applied_revision"] == sequence and key not in pending)
        paper_id = _paper(operation)
        paper = papers.get(paper_id)
        parent = next(
            (
                p
                for p in operation.get("parents", [])
                if p["kind"] == "paper" and p["id"] == paper_id
            ),
            None,
        )
        owner_incarnation = (
            operation.get("incarnation")
            if operation["entity_type"] == "paper"
            else parent["incarnation"]
            if parent
            else None
        )
        visible = bool(
            paper
            and graph_active(graph, ("paper", paper_id))
            and graph[("paper", paper_id)]["incarnation"] == owner_incarnation
        )
        conflict = event["outcome"] == "conflict"
        manifest = operation["entity_type"] in {"paper_document", "research_file"}
        if conflict:
            status = "conflict_retained"
        elif not current or (not active and operation["action"] == "put"):
            status = "accepted_history"
        elif not applied:
            status = "accepted_pending"
        elif manifest and operation["action"] == "put":
            status = (
                "binding_recorded"
                if operation["operation_id"] in file_bindings
                else "manifest_waiting"
            )
        else:
            status = "applied" if active or operation["action"] == "delete" else "accepted_history"
        row = {
            "sequence": sequence,
            "operation_id": operation["operation_id"],
            "entity_type": operation["entity_type"],
            "entity_id": operation["entity_id"],
            "incarnation": operation.get("incarnation"),
            "action": operation["action"],
            "paper_id": paper_id if visible else None,
            "paper_incarnation": owner_incarnation if visible else None,
            "title": str(paper.get("title") or "")[:160] if visible else "",
            "origin": "this_device" if operation["device_id"] == device_id else "other_device",
            "status": status,
            "resolved": operation["operation_id"] in resolved,
            "resume": None,
        }
        # An own conflict remains useful; an accepted own echo is not a new peer change.
        if len(recent) < recent_limit and (conflict or row["origin"] == "other_device"):
            recent.append(row)
        if (
            not conflict
            and current
            and active
            and applied
            and visible
            and operation["action"] == "put"
            and paper_id not in seen_papers
            and operation["entity_type"] in {"note", "reading_state"}
            and len(continuation) < continue_limit
        ):
            suggestion = dict(row)
            suggestion["resume"] = _resume(
                operation, notes.get(operation["entity_id"]), key in pending
            )
            continuation.append(suggestion)
            seen_papers.add(paper_id)
    return {
        "workspace_id": workspace_id,
        "device_id": device_id,
        "cursor": cursor,
        "recent": recent,
        "continue": continuation,
        "window": len(events),
        "has_more": bool(has_more),
        "coverage": "received_note_reading_updates",
    }


def resume_matches(row, *, paper_id, loaded_hash, current_hash):
    """No navigation occurs here. Exact loaded AND current source are required."""
    resume = row.get("resume")
    return bool(
        resume
        and row.get("paper_id") == paper_id
        and isinstance(loaded_hash, str)
        and HASH.fullmatch(loaded_hash)
        and resume["source_hash"] == loaded_hash == current_hash
    )
