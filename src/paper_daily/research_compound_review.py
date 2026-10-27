"""Typed review of retained citation, followup and resource groups; no SQL replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper_daily import research_compound as compound
from paper_daily import research_generation as generation
from paper_daily import sync_capture
from paper_daily.research_lifecycle import parent_lifecycle


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _rows(conn, table, owner, key=None):
    column = compound.TABLES[table][1]
    fields = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    size = "+".join(f'coalesce(length(CAST("{f}" AS BLOB)),0)' for f in fields)
    where = "paper_id=?" + (f' AND "{column}"=?' if key is not None else "")
    args = (owner, key) if key is not None else (owner,)
    lengths = conn.execute(
        f'SELECT {size} FROM "{table}" WHERE {where} LIMIT ?', (*args, compound.MAX_ROWS + 1)
    ).fetchall()
    if len(lengths) > compound.MAX_ROWS or sum(r[0] for r in lengths) > compound.MAX_BYTES:
        raise ValueError("Displayed research group exceeds its supported size")
    return compound._inventory(conn, table, owner, key)


def _documents(conn, owner):
    """Desired/applied metadata stays independent of whether local bytes exist."""
    tables = _tables(conn)
    mapping = (
        conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (owner,)
        ).fetchone()
        if "research_paper_identity" in tables
        else None
    )
    portable = mapping[0] if mapping else None
    result = {"portable": portable, "desired": None, "applied": None}
    for name in ("desired", "applied"):
        table = "research_document_" + name
        if portable and table in tables:
            length = conn.execute(
                f'SELECT length(CAST(target AS BLOB)) FROM "{table}" WHERE paper_id=?', (portable,)
            ).fetchone()
            if length and length[0] > 4096:
                raise ValueError("Document metadata exceeds its supported size")
            row = conn.execute(f'SELECT * FROM "{table}" WHERE paper_id=?', (portable,)).fetchone()
            result[name] = dict(row) if row else None
    return result


def _same_owner(conn, original, owner):
    data = original.data
    return (
        owner == original.owner_id
        and generation._path(conn) == data["db_path"]
        and generation._identity(data["db_path"]) == data["database_identity"]
        and generation._binding(conn) == data["binding"]
        and parent_lifecycle(conn, "paper", owner) == data["parent_lifecycle"]
    )


def _local_document(conn, original, owner, *, archived=False, handles=None):
    from paper_daily.document_reader import from_workspace

    data = original.data
    # Only this workspace's original source root is an IO hint. Imported paths
    # remain provenance, never instructions to read a different workspace.
    owned = (
        generation._path(conn) == data["db_path"]
        and generation._identity(data["db_path"]) == data["database_identity"]
        and generation._binding(conn) == data["binding"]
    )
    root = (
        Path(data["document"]["path"]).parent
        if owned and not archived and data["document"]
        else None
    )
    reader = from_workspace(generation._path(conn), legacy_root=root)
    document = reader.resolve(owner)
    if handles is not None:
        handles.append(document)
    return {
        "mode": document.mode,
        "status": document.status,
        "sha256": document.sha256,
        "target": document.target,
    }


def _text_input(conn, original, *, archived=False):
    data = original.data
    source = data["text_source"]
    if (
        archived
        or not source
        or not (
            generation._path(conn) == data["db_path"]
            and generation._identity(data["db_path"]) == data["database_identity"]
            and generation._binding(conn) == data["binding"]
        )
    ):
        return None
    path = Path(source["path"])
    if any(generation._is_link(p) for p in (path, *path.parents)):
        raise ValueError("Research input cannot traverse links")
    if not path.exists():
        return {"available": False, "sha256": None}
    with path.open("rb") as stream:
        raw = stream.read(3 * 1024 * 1024 + 1)
    if len(raw) > 3 * 1024 * 1024:
        raise ValueError("Research text exceeds its supported size")
    return {"available": True, "sha256": hashlib.sha256(raw).hexdigest()}


def _snapshot(conn, original, mutations, owner, *, archived=False, handles=None):
    table, column = original.table, compound.TABLES[original.table][1]
    fields = [r[1] for r in conn.execute('PRAGMA table_info("papers")')]
    size = "+".join(f'coalesce(length(CAST("{f}" AS BLOB)),0)' for f in fields)
    length = conn.execute(f"SELECT {size} FROM papers WHERE id=?", (owner,)).fetchone()
    if length and length[0] > compound.MAX_BYTES:
        raise ValueError("Displayed parent exceeds its supported size")
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (owner,)).fetchone()
    token = parent_lifecycle(conn, "paper", owner)
    if parent is None or token is None:
        raise ValueError("Selected paper is unavailable or has no local lifecycle")
    keys = [r[column] for r in mutations["puts"]] + mutations["deletes"]
    if sync_capture.enabled(conn):
        conn._capture_graph_cache = conn._capture_client._optimistic_graph(conn)
    observations = [
        sync_capture.observe_target(conn, "paper", owner, compound.TABLES[table][0], key)
        for key in keys
    ]
    graph = conn._capture_client._optimistic_graph(conn)[0] if sync_capture.enabled(conn) else {}
    lifecycles = [
        graph.get(("research_content", item["entity_id"])) if item else None
        for item in observations
    ]
    documents = _documents(conn, owner)
    graph_parent = (
        sync_capture.observe(conn, "paper", documents["portable"])
        if sync_capture.enabled(conn)
        else None
    )
    if graph_parent and not graph_parent["active"]:
        raise ValueError("Selected paper is deleted in the synchronized workspace")
    prefix = "resources:" if original.data["phase"] == "resources" else "followups.checked."
    completion = conn.execute("SELECT value FROM kv WHERE key=?", (prefix + owner,)).fetchone()
    value = {
        "owner": owner,
        "graph_parent": graph_parent,
        "completion": completion[0] if completion else None,
        "parent": dict(parent),
        "epoch": token,
        "rows": _rows(conn, table, owner, original.data["key"]),
        "observations": observations,
        "lifecycles": lifecycles,
        "documents": documents,
        "local_document": _local_document(
            conn, original, owner, archived=archived, handles=handles
        ),
        "input_text": _text_input(conn, original, archived=archived),
    }
    generation._json(value)
    return value


def mutations_for(record, owner):
    compound.validate_request_record(record)
    original = compound.Context(record["context_json"])
    mutations = json.loads(record["mutations_json"])
    for row in mutations["puts"]:
        row["paper_id"] = owner
    return original, mutations


def _restore_item(lifecycle, parent):
    return bool(parent and lifecycle) and (
        not lifecycle["active"]
        or any(ref["incarnation"] != parent["incarnation"] for ref in lifecycle["parents"])
    )


def _requires_restore(current, mutations):
    return any(
        _restore_item(value, current["graph_parent"])
        for value in current["lifecycles"][: len(mutations["puts"])]
    )


def _archived_source_operation(conn, token):
    if "recovery_records" not in _tables(conn):
        return None
    if token["predecessor"]:
        choices = [
            ("paperfact_sync_operations", "operation_id", token["predecessor"], "envelope"),
            ("paperfact_sync_graph_receipts", "operation_id", token["predecessor"], "event"),
        ]
    else:
        choices = [("paperfact_sync_inbox", "sequence", token["revision"], "event")]
    for table, key, identity, field in choices:
        matches = conn.execute(
            "SELECT data FROM recovery_records WHERE table_name=? "
            "AND length(CAST(data AS BLOB))<=1048576 AND json_valid(data) "
            f"AND json_extract(data,'$.{key}')=? LIMIT 2",
            (table, identity),
        ).fetchall()
        operations = []
        for match in matches:
            value = json.loads(json.loads(match[0])[field])
            operations.append(value["operation"] if field == "event" else value)
        if operations:
            if any(value != operations[0] for value in operations[1:]):
                raise ValueError("Ambiguous archived source receipt")
            return operations[0]
    return None


def _source_hash(conn, original):
    data = original.data
    if data["document"]:
        return data["document"]["sha256"]
    if not data["phase"].startswith("edit_") or data["binding"] is None:
        return None
    token = compound._token(original, data["key"])
    tables = _tables(conn)
    row = None
    same_workspace = generation._binding(conn) == data["binding"]
    if same_workspace and token["predecessor"] and "paperfact_sync_operations" in tables:
        row = conn.execute(
            "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=? "
            "AND length(CAST(envelope AS BLOB))<=262144",
            (token["predecessor"],),
        ).fetchone()
        operation = json.loads(row[0]) if row else None
    elif same_workspace and token["revision"] and "paperfact_sync_inbox" in tables:
        row = conn.execute(
            "SELECT event FROM paperfact_sync_inbox WHERE sequence=? "
            "AND length(CAST(event AS BLOB))<=1048576",
            (token["revision"],),
        ).fetchone()
        operation = json.loads(row[0])["operation"] if row else None
    else:
        operation = None
    if operation is None:
        operation = _archived_source_operation(conn, token)
    if operation is None:
        return None
    from paper_daily.sync_journal import canonical_operation

    canonical_operation(operation)
    if (
        operation["workspace_id"] != data["binding"]["workspace_id"]
        or operation["entity_type"] != "research_content"
        or operation["entity_id"] != token["entity_id"]
        or operation.get("incarnation") != token["incarnation"]
        or operation["action"] != "put"
    ):
        raise ValueError("Original source receipt differs from the captured reference")
    return operation["payload"]["source_document_hash"]


def preview(conn, record, *, owner=None, confirmed=False, archived=False):
    compound.validate_request_record(record)
    if record["status"] != "candidate":
        raise ValueError("This compound request has no retained candidate")
    original = compound.Context(record["context_json"])
    owner = owner or original.owner_id
    original, mutations = mutations_for(record, owner)
    source = _source_hash(conn, original)
    view = {
        "original": {"paper": original.paper, "rows": original.rows},
        "retained": mutations,
        "source_hash": source,
        "scope": {"kind": "paper", "id": owner},
        "editable": False,
    }
    try:
        current = _snapshot(conn, original, mutations, owner, archived=archived)
    except (ValueError, OSError):
        view.update(apply=False, reason="Choose an available paper to review this retained group")
        return view
    same = not archived and _same_owner(conn, original, owner)
    current_hash = current["local_document"]["sha256"]
    aligned = source is None or source == current_hash
    restore = _requires_restore(current, mutations)
    capable = same and aligned and not restore or confirmed
    # A review must show the full resulting group, including explicit deletions.
    view.update(
        current={"paper": current["parent"], "rows": current["rows"]},
        expected=current,
        parent_token=current["epoch"],
        parent_row=current["parent"],
        target={"id": owner, "title": current["parent"]["title"]},
        requires_confirmation=confirmed,
        apply=capable,
        reason=(
            "Historical source hash is retained; this group is not verified "
            "against the current PDF. "
            "Confirm the selected paper before applying."
            if confirmed and not aligned
            else "Confirm restoring deleted records into the explicitly selected paper"
            if confirmed and restore
            else "Choose the target explicitly to review restoration of deleted records"
            if restore and not confirmed
            else "Confirm the explicitly selected paper before applying this complete group"
            if confirmed
            else "Choose the target paper explicitly; original ownership or PDF differs"
            if not capable
            else "Review additions, replacements and deletions before applying the complete group"
        ),
    )
    return view


def _restore_group(conn, context, mutations, current, source_hash):
    from paper_daily import sync_content

    client = conn._capture_client
    graph = client._optimistic_graph(conn)

    def save(operation):
        result = client.journal.apply_in(conn, operation, client.writer)
        if result["applied"]:
            client._overlay_optimistic(graph, operation)
        conn._capture_graph_cache = graph

    with sync_capture.suppress_capture(conn):
        existing = {r[compound.TABLES[context.table][1]] for r in current["rows"]}
        for key in mutations["deletes"]:
            if key not in existing:
                continue
            identity = sync_content.content_id(
                {"kind": "paper", "id": current["documents"]["portable"]},
                compound.TABLES[context.table][0],
                key,
            )
            operation = client.new_graph_operation_in(
                conn, "research_content", identity, {}, action="delete"
            )
            save(operation)
        for index, row in enumerate(mutations["puts"]):
            payload = sync_content.content_payload(conn, context.table, row)
            payload["source_document_hash"] = source_hash
            identity = sync_content.content_id(payload["scope"], payload["feature"], payload["key"])
            operation = client.new_graph_operation_in(
                conn,
                "research_content",
                identity,
                payload,
                restore=_restore_item(current["lifecycles"][index], current["graph_parent"]),
            )
            save(operation)
        compound._apply(
            conn, context, {"puts": [], "deletes": [], "completion": mutations["completion"]}
        )
    conn._capture_graph_cache = None


def apply_in(conn, record, data, receipt):
    """One caller-owned transaction includes typed rows, outbox and review receipt."""
    original, mutations = mutations_for(record, data["scope"]["id"])
    if mutations != data["retained"]:
        raise ValueError("Retained group differs from its typed source")
    if _documents(conn, data["scope"]["id"]) != data["expected"]["documents"]:
        raise ValueError("Displayed document version changed; retained work is unchanged")
    handles = []
    archived = data["origin"] == "compound_recovery"
    current = _snapshot(
        conn, original, mutations, data["scope"]["id"], archived=archived, handles=handles
    )
    if current != data["expected"]:
        raise ValueError("Displayed group, parent or PDF changed; retained work is unchanged")
    # Revalidate against the displayed target's current manual/curated records.
    # Explicit reattachment never grants permission to overwrite protected rows.
    target = original.data
    target.update(owner_id=current["owner"], rows=current["rows"])
    context = compound.Context(generation._context_json(target))
    compound._validate(context, mutations)
    observations = current["observations"]
    sources = {o["entity_id"]: data["source_hash"] for o in observations if o}
    with sync_capture.expecting(conn, observations, source_hashes=sources):
        if _requires_restore(current, mutations):
            if not data["requires_confirmation"]:
                raise ValueError("Deleted records require an explicitly confirmed target")
            _restore_group(conn, context, mutations, current, data["source_hash"])
        else:
            compound._apply(conn, context, mutations)
        receipt()
        from paper_daily.document_reader import document_current

        if any(document.available and not document_current(document) for document in handles):
            raise ValueError("Displayed PDF changed during application; retained work is unchanged")
        if _text_input(conn, original, archived=archived) != current["input_text"]:
            raise ValueError("Displayed source text changed during application")
        conn.commit()
