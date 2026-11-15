"""Trusted native survey publication from sealed captures, not decoded model JSON.

Preparation retains/stages bytes off-lock. Publication owns a savepoint within the
caller's transaction; no credentials, implicit enrollment or model calls occur.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass

from paper_daily import research_generation as generation
from paper_daily import survey_sources, sync_capture, sync_source_files, sync_survey_files
from paper_daily.sync_artifacts import desired_file, paths, stage_bytes, verify_closure
from paper_daily.sync_files import canonical_json, file_id, list_file_id

_SEAL = object()


def _native_in(conn, context, sources):
    client = getattr(conn, "_capture_client", None)
    if client is None:
        return None
    graph = client._optimistic_graph(conn)[0]
    listing = graph.get(("list", context.owner_id))
    if listing is None or not listing["active"]:
        raise ValueError("Survey publication requires an enrolled active list")

    def state(value):
        return {k: v for k, v in value.items() if k != "structure_revision"} if value else None

    identity = list_file_id(context.owner_id)
    rows = []
    for source in sources:
        if source["state"] != "captured":
            continue
        mapped = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (source["paper_id"],)
        ).fetchone()
        paper = graph.get(("paper", mapped[0])) if mapped else None
        if paper is None or not paper["active"]:
            raise ValueError("Survey original requires its actual enrolled paper mapping")
        source_id = file_id(mapped[0], "original_source", source["document_hash"])
        rows.append(
            dict(
                source_id=source["id"],
                paper_id=mapped[0],
                paper_incarnation=paper["incarnation"],
                document_hash=source["document_hash"],
                file_id=source_id,
                metadata=state(graph.get(("research_file", source_id))),
                desired=desired_file(conn, source_id),
            )
        )
    if len(rows) > sync_survey_files.MAX_SOURCES:
        raise ValueError("Survey native publication exceeds its selected-original budget")
    return dict(
        list=state(listing),
        report=state(graph.get(("research_file", identity))),
        desired=desired_file(conn, identity),
        sources=rows,
    )


def observe(context, sources):
    """Capture actual native report absence/version before dispatch; read-only."""
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        if generation._stale(conn, context) is not None:
            raise ValueError("Survey inputs changed before native observation")
        return _native_in(conn, context, sources)


def _request(context, purpose):
    from paper_daily.survey_content import content

    return "survey:" + content.hashed([context.request_id, purpose])


def _check_in(conn, proposal, *, retry=False):
    report = survey_sources.checked_proposal(proposal)
    context = proposal._capture._context
    native = survey_sources._checked(proposal._capture).get("native")
    if native is None:
        raise ValueError("Survey has no pre-dispatch native observation; capture it again")
    reason = generation._stale(conn, context)
    if reason is not None or not survey_sources.current(proposal._capture):
        raise ValueError(reason or "Survey original availability changed")
    if not retry and _native_in(conn, context, report["sources"]) != native:
        raise ValueError("Survey report or native original lifetimes changed")
    return report, context, native


@dataclass(frozen=True, init=False)
class PreparedSurvey:
    proposal: object
    payload: str
    sources: tuple
    proof: object
    proof_operation: dict
    store: object
    root: object
    seal: object


def prepare(proposal, *, cancelled=lambda: False):
    """Stage a checked proposal in its original native workspace, with no SQL write."""
    survey_sources._cancel(cancelled)
    context = (
        proposal._capture._context if isinstance(proposal, survey_sources.SurveyProposal) else None
    )
    if context is None:
        raise ValueError("Survey publication requires its sealed checked proposal")
    with closing(generation._connect(context.db_path)) as conn:
        conn.execute("BEGIN")
        report, context, native = _check_in(conn, proposal)
        client = conn._capture_client
        configured = paths(conn)
        if configured is None:
            raise ValueError("Configure local artifact storage before survey publication")
        graph = native["report"]
        if graph is not None and not graph["active"]:
            raise ValueError("Retired survey report requires explicit reviewed restoration")
    receipts = survey_sources.retain_originals(proposal, cancelled=cancelled)
    originals = survey_sources.retained_originals(proposal, receipts, cancelled=cancelled)
    store, root = configured
    prepared_sources, bindings = [], []
    observations = [
        dict(
            kind="list",
            id=context.owner_id,
            incarnation=native["list"]["incarnation"],
            revision=0,
            depends_on=None,
        )
    ]
    for source, (path, _version) in zip(native["sources"], originals, strict=True):
        survey_sources._cancel(cancelled)
        prepared = sync_source_files.prepare_source(
            client,
            source["paper_id"],
            path,
            document_hash=source["document_hash"],
            parent_incarnation=source["paper_incarnation"],
            store=store,
            version_root=root,
            request_id=_request(context, source["source_id"]),
        )
        existing = source["desired"]
        metadata = source["metadata"]
        parent = dict(kind="paper", id=source["paper_id"], incarnation=source["paper_incarnation"])
        if metadata is not None and (not metadata["active"] or metadata["parents"] != [parent]):
            raise ValueError("Retired original needs explicit reviewed restoration")
        if metadata is not None and (
            existing is None
            or existing["parents"] != [parent]
            or existing["payload"] != json.loads(prepared.payload)
        ):
            raise ValueError("Survey original differs from its observed native publication")
        incarnation = metadata["incarnation"] if metadata else prepared.request
        bindings.append(
            {
                key: source[key]
                for key in (
                    "source_id",
                    "paper_id",
                    "paper_incarnation",
                    "document_hash",
                    "file_id",
                )
            }
            | dict(incarnation=incarnation)
        )
        prepared_sources.append(prepared)
        observations.extend(
            dict(kind=kind, id=identity, incarnation=life, revision=0, depends_on=None)
            for kind, identity, life in (
                ("paper", source["paper_id"], source["paper_incarnation"]),
                ("research_file", source["file_id"], incarnation),
            )
        )
    versions = dict(
        schema_version=2,
        workspace_id=client.journal.workspace_id,
        complete=False,
        entities=observations,
        documents=[],
        inputs_sha256=report["inputs"]["prompt_hash"],
    )
    payload, blobs = sync_survey_files.encode(
        report, context.owner_id, bindings, input_versions=versions
    )
    stage_bytes(store, blobs)
    request = _request(context, "report")
    operation = dict(
        version=2,
        operation_id=request,
        workspace_id=client.journal.workspace_id,
        device_id=client.journal.device_id,
        entity_type="research_file",
        entity_id=list_file_id(context.owner_id),
        action="put",
        base_revision=0,
        depends_on=None,
        payload=payload,
        incarnation=graph["incarnation"] if graph else request,
        parents=[dict(kind="list", id=context.owner_id, incarnation=native["list"]["incarnation"])],
        structure_revision=0,
    )
    proof, _body, _blobs = verify_closure(store, operation)
    survey_sources._cancel(cancelled)
    value = object.__new__(PreparedSurvey)
    for key, item in dict(
        proposal=proposal,
        payload=canonical_json(payload).decode(),
        sources=tuple(prepared_sources),
        proof=proof,
        proof_operation=operation,
        store=store,
        root=root,
        seal=_SEAL,
    ).items():
        object.__setattr__(value, key, item)
    return value


def publish_in(conn, prepared, *, cancelled=lambda: False):
    """Atomically add original ownership and the report/outbox in the caller transaction.

    A caught failure also rolls back this function's writes. Retained archive/blob
    bytes survive as inactive data; no transaction is independently committed.
    """
    if (
        not conn.in_transaction
        or not isinstance(prepared, PreparedSurvey)
        or getattr(prepared, "seal", None) is not _SEAL
    ):
        raise ValueError("Survey publication requires its staged proof and caller transaction")
    survey_sources._cancel(cancelled)
    payload = json.loads(prepared.payload)
    if payload != prepared.proof_operation["payload"] or not prepared.proof.matches(
        prepared.proof_operation
    ):
        raise ValueError("Survey report bytes changed after preparation")
    proposal = prepared.proposal
    context = proposal._capture._context
    request = _request(context, "report")
    # Check binding and retained request before stale-target comparison for exact retries.
    _check_in(conn, proposal, retry=True)
    client = conn._capture_client
    if client is None or (client.journal.workspace_id, client.journal.device_id) != (
        prepared.proof_operation["workspace_id"],
        prepared.proof_operation["device_id"],
    ):
        raise ValueError("Survey publication belongs to another workspace/device")
    existing = conn.execute(
        "SELECT operation FROM research_file_versions WHERE operation_id=?", (request,)
    ).fetchone()
    if existing:
        operation = json.loads(existing[0])
        if (
            operation["payload"] != payload
            or operation["parents"] != prepared.proof_operation["parents"]
            or desired_file(conn, operation["entity_id"]) != operation
            or not sync_survey_files.active(
                lambda kind, identity: client._optimistic_graph(conn)[0].get((kind, identity)),
                operation,
            )
        ):
            raise ValueError("Survey retry no longer matches its exact active publication")
        return operation
    _check_in(conn, proposal)
    registered = paths(conn)
    if registered is None or (registered[0].root, registered[1]) != (
        prepared.store.root,
        prepared.root,
    ):
        raise ValueError("Survey artifact storage binding changed")
    conn.execute("SAVEPOINT survey_publication")
    try:
        for source in prepared.sources:
            survey_sources._cancel(cancelled)
            actual = sync_source_files.publish_source_in(conn, client, source)
            binding = next(
                row for row in payload["source_bindings"] if row["file_id"] == actual["entity_id"]
            )
            if actual["incarnation"] != binding["incarnation"]:
                raise ValueError("Survey original publication changed after preparation")
        survey_sources._cancel(cancelled)
        operation = client.new_graph_operation_in(
            conn, "research_file", list_file_id(context.owner_id), payload, operation_id=request
        )
        with sync_capture.suppress_capture(conn):
            result = client.journal.apply_in(conn, operation, client.writer)
            if not result["applied"]:
                raise ValueError("Survey report was not applied atomically")
        survey_sources._cancel(cancelled)
        conn.execute("RELEASE survey_publication")
    except BaseException:
        conn.execute("ROLLBACK TO survey_publication")
        conn.execute("RELEASE survey_publication")
        raise
    finally:
        conn._capture_graph_cache = None
    return operation


def publish(prepared, *, cancelled=lambda: False):
    """Publish in the captured workspace and materialize outside its SQL write lock.

    An interrupted materialization leaves the exact durable pending intent. Retry
    reuses it; a replaced database or newer report can never receive activation.
    """
    from paper_daily.sync_artifacts import activate, materialize

    if not isinstance(prepared, PreparedSurvey) or getattr(prepared, "seal", None) is not _SEAL:
        raise ValueError("Survey publication requires its staged proof")
    context = prepared.proposal._capture._context
    with closing(generation._connect(context.db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        operation = publish_in(conn, prepared, cancelled=cancelled)
    survey_sources._cancel(cancelled)
    directory = materialize(prepared.store, prepared.root, operation)
    survey_sources._cancel(cancelled)
    with closing(generation._connect(context.db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _check_in(conn, prepared.proposal, retry=True)
        with sync_capture.suppress_capture(conn):
            if not activate(conn, operation, directory):
                raise ValueError("Survey changed before verified local activation")
    return operation


def complete_pending(client, list_id, *, expected=None, expected_database=None,
                     cancelled=lambda: False):
    """Finish verified local bytes after restart, without proposal replay or network.

    Only an actual current persisted native report may activate. Unowned staged
    blobs, detached archives and decoded model JSON cannot create that authority.
    """
    from paper_daily.sync_artifacts import activate, materialize

    survey_sources._cancel(cancelled)
    identity = list_file_id(list_id)
    with client.journal.transaction() as conn:
        database_identity = generation._identity(client.journal.path)
        operation = desired_file(conn, identity)
        configured = paths(conn)
        if expected_database is not None and database_identity != expected_database:
            raise ValueError("Pending survey database changed after selection")
        if expected is not None and operation != expected:
            raise ValueError("Pending survey changed after selection; refresh first")
        if operation is None or configured is None:
            raise ValueError("No owned pending survey report or registered artifact storage")
        if not sync_survey_files.active(
            lambda kind, item: client._optimistic_graph(conn)[0].get((kind, item)), operation
        ):
            raise ValueError("Pending survey original lifetimes are no longer active")
    store, root = configured
    directory = materialize(store, root, operation)
    survey_sources._cancel(cancelled)
    with client.journal.transaction() as conn:
        if generation._identity(client.journal.path) != database_identity:
            raise ValueError("Pending survey database identity changed during completion")
        registered = paths(conn)
        if (
            registered is None
            or (registered[0].root, registered[1]) != (store.root, root)
            or not sync_survey_files.active(
                lambda kind, item: client._optimistic_graph(conn)[0].get((kind, item)), operation
            )
            or not activate(conn, operation, directory)
        ):
            raise ValueError("Pending survey changed before verified local activation")
    return operation
