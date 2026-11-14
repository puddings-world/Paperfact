"""Exact original-file lifetime dependencies for native Lineage synchronization.

Pins are wire data, not publication authority. The native service checks these
against its workspace-scoped graph in the same acceptance transaction.
"""

from __future__ import annotations

import json
from pathlib import Path

from paper_daily import lineage_address, lineage_content, lineage_wire
from paper_daily.claim_content import closed
from paper_daily.sync_files import file_id
from paper_daily.sync_schema_v2 import _identifier

FIELDS = {"source_id", "paper_id", "file_id", "incarnation"}


def validate(operation):
    """Closed complete source pins; hashes alone cannot identify a file lifetime."""
    if not isinstance(operation, dict):
        raise ValueError("Lineage dependency operation must be an object")
    if not lineage_address.validate(operation):
        raise ValueError("Source dependencies require a typed Lineage operation")
    pins = operation.get("source_dependencies")
    if not isinstance(pins, list) or len(pins) > lineage_content.MAX_SOURCES:
        raise ValueError("Lineage requires its bounded original-file dependencies")
    if operation["action"] == "delete":
        if pins:
            raise ValueError("Lineage retirement has no live original-file dependencies")
        return pins
    expected = lineage_wire.required_originals(operation["payload"])
    if len(pins) != len(expected):
        raise ValueError("Lineage source dependencies omit or add selected originals")
    for pin, selected in zip(pins, expected, strict=True):
        closed(pin, FIELDS)
        if (
            pin["source_id"] != selected["source_id"]
            or pin["paper_id"] != selected["paper_id"]
            or pin["file_id"]
            != file_id(selected["paper_id"], "original_source", selected["document_hash"])
        ):
            raise ValueError("Lineage dependency differs from its exact selected source owner")
        _identifier(pin["incarnation"])
    return pins


def canonical_operation(operation):
    """Dependency-complete codec used by native journal/service admission."""
    validate(operation)
    return lineage_wire.canonical_operation(operation)


def active(get_entity, operation):
    """Check workspace graph lifetimes; caller owns operation schema and transaction.

    False preserves a stale/missing/retired-source conflict. Same-hash restoration
    does not revive an old pin. Deletes remain possible after source retirement.
    This checks neither blob availability nor remote authentication by itself.
    """
    pins = validate(operation)
    if operation["action"] == "delete":
        return True
    parents = {p["id"]: p for p in operation["parents"]}
    for parent in parents.values():
        paper = get_entity("paper", parent["id"])
        if (
            not isinstance(paper, dict)
            or paper.get("active") is not True
            or paper.get("incarnation") != parent["incarnation"]
        ):
            return False
    for pin in pins:
        source = get_entity("research_file", pin["file_id"])
        if (
            not isinstance(source, dict)
            or source.get("active") is not True
            or source.get("incarnation") != pin["incarnation"]
            or source.get("parents") != [parents[pin["paper_id"]]]
        ):
            return False
    return True


def requires_readiness(operation):
    """Recognize source/address markers; full validation follows dispatch."""
    payload = operation.get("payload")
    return (
        "content_address" in operation
        or "source_dependencies" in operation
        or isinstance(payload, dict) and payload.get("feature") == "lineage"
    )


def ready_to_push_in(conn, client, operation):
    """Wait for exact source outcomes, not bytes or a push acknowledgement.

    This local metadata predicate neither authenticates nor reads files. A final
    conflict releases the transfer wait too: graph acceptance must preserve the
    actual conflict rather than recapturing newer source lifetimes. The caller
    owns the transaction. This predicate itself creates no operation or acceptance receipt.
    """
    from paper_daily.sync_client import validate_event
    from paper_daily.sync_journal import MAX_BYTES
    from paper_daily.sync_journal import canonical_operation as source_codec

    canonical_operation(operation)
    journal = client.journal
    if not conn.in_transaction:
        raise ValueError("Source readiness requires its caller transaction")
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if not main or Path(main).resolve() != journal.path.resolve():
        raise ValueError("Source readiness belongs to another research database")
    journal._binding(conn)
    if (operation["workspace_id"], operation["device_id"]) != (
        journal.workspace_id,
        journal.device_id,
    ):
        raise ValueError("Source readiness belongs to another workspace/device")

    def decode(value, maximum):
        if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
            raise ValueError("Source publication metadata exceeds its bound")
        return json.loads(value)

    parents = {p["id"]: p for p in operation["parents"]}

    def check_source(source, pin):
        source_codec(source)
        if (
            source["version"] != 2
            or source["workspace_id"] != journal.workspace_id
            or source["entity_type"] != "research_file"
            or source["action"] != "put"
            or source["operation_id"] != pin["incarnation"]
            or source["incarnation"] != pin["incarnation"]
            or source["entity_id"] != pin["file_id"]
            or source["parents"] != [parents[pin["paper_id"]]]
            or source["payload"].get("feature") != "original_source"
        ):
            raise ValueError("Source publication differs from the exact original dependency")

    ready = True
    for pin in operation["source_dependencies"]:
        received = conn.execute(
            "SELECT event FROM paperfact_sync_graph_receipts WHERE operation_id=?",
            (pin["incarnation"],),
        ).fetchone()
        if received is not None:
            event = decode(received[0], 3 * MAX_BYTES)
            validate_event(event, journal.workspace_id)
            check_source(event["operation"], pin)
            continue
        local = conn.execute(
            "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=?",
            (pin["incarnation"],),
        ).fetchone()
        version = conn.execute(
            "SELECT operation FROM research_file_versions WHERE operation_id=?",
            (pin["incarnation"],),
        ).fetchone()
        if local is None or version is None:
            raise ValueError("Original dependency has no received or local publication")
        source = decode(local[0], MAX_BYTES)
        check_source(source, pin)
        if source["device_id"] != journal.device_id or source_codec(
            decode(version[0], MAX_BYTES)
        ) != source_codec(source):
            raise ValueError("Pending original publication differs from its local owner")
        ready = False
    return ready


def projection_reason_in(conn, client, operation):
    """Classify native receive against actual local graph/projection metadata.

    Parent/source pending or deferred reasons preserve the existing row. Missing,
    deleted or replaced lifetimes hide it while retaining the original put, not
    an invented empty retirement. The receive transaction owns event acceptance,
    writer authorization and cursor commit; this is no substitute for them and
    does not itself write a journal entry or accepted service event.
    """
    canonical_operation(operation)
    journal = client.journal
    if not conn.in_transaction:
        raise ValueError("Lineage receive inspection requires its caller transaction")
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), None)
    if not main or Path(main).resolve() != journal.path.resolve():
        raise ValueError("Lineage receive inspection belongs to another research database")
    journal._binding(conn)
    if operation["workspace_id"] != journal.workspace_id:
        raise ValueError("Lineage receive inspection belongs to another workspace")
    # The sender may be another enrolled device. Do not require local sender ID.
    if operation["action"] == "delete":
        return None
    # Receive has validated and inserted this contiguous prefix, but commits
    # its cursor only after projection. Use actual inbox evidence here rather
    # than treating just-received own acknowledgements as outstanding again.
    received = conn.execute(
        "SELECT sequence FROM paperfact_sync_inbox ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    cursor = received[0] if received is not None else 0
    outstanding = {
        (op["entity_type"], op["entity_id"]) for op in client._pending_graph(conn, cursor)
    }
    parents = {p["id"]: p for p in operation["parents"]}
    dependencies = [("parent", parent, None) for parent in operation["parents"]]
    dependencies.extend(
        (
            "source",
            dict(kind="research_file", id=pin["file_id"], incarnation=pin["incarnation"]),
            [parents[pin["paper_id"]]],
        )
        for pin in operation["source_dependencies"]
    )
    # Protect any outstanding dependency before inspecting earlier missing or
    # retired sources. The selected source order must not decide draft safety.
    for role, dependency, _expected in dependencies:
        if (dependency["kind"], dependency["id"]) in outstanding:
            return role + "_pending"
    for role, dependency, expected_parents in dependencies:
        key = dependency["kind"], dependency["id"]
        state = client._graph_entity(conn, *key)
        if state is None:
            return role + "_missing"
        if not state["active"]:
            return role + "_deleted"
        if state["incarnation"] != dependency["incarnation"] or (
            expected_parents is not None and state["parents"] != expected_parents
        ):
            return role + "_incarnation"
        projected = conn.execute(
            "SELECT h.revision,h.applied_revision,p.active,p.reason "
            "FROM paperfact_sync_heads h JOIN paperfact_sync_graph_projection p "
            "USING(entity_type,entity_id) WHERE h.entity_type=? AND h.entity_id=?",
            key,
        ).fetchone()
        if (
            projected is None
            or projected["revision"] != projected["applied_revision"]
            or not projected["active"]
            or projected["reason"] is not None
        ):
            return role + "_deferred"
    from paper_daily.lineage_capacity import local_room_in
    from paper_daily.sync_content import _local_scope

    local = _local_scope(conn, operation["payload"]["scope"], required=False)
    if local is not None and not local_room_in(conn, local, operation["content_address"]["key"]):
        return "projection_capacity"
    return None
