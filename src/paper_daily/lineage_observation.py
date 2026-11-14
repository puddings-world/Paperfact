"""Sealed composite-target observations, without schema installation or writes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily import file_change, lineage_sets, research_lineage, sync_capture
from paper_daily import research_generation as generation
from paper_daily.lineage_jobs import _worker
from paper_daily.research_evidence import _checked_snapshot
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import desired_file
from paper_daily.sync_client import SyncClient
from paper_daily.sync_content import content_id
from paper_daily.sync_files import canonical_json, file_id
from paper_daily.workspace_service import _binding, _tables

_KEY = secrets.token_bytes(32)


def _fail(code):
    raise research_lineage.LineageError(code) from None


def _seal(encoded, corpus, versions):
    origins = [
        (id(d), id(d._owner), d._generation, d._owner._generation, d._owner._closed)
        for d in corpus._documents
    ]
    data = [
        encoded,
        corpus._json,
        corpus._seal,
        origins,
        [(str(p), v) for p, v in versions],
        os.getpid(),
    ]
    return hmac.new(_KEY, research_lineage._json(data).encode(), "sha256").hexdigest()


@dataclass(frozen=True, slots=True)
class LineageObservation:
    _json: str = field(repr=False)
    _corpus: research_lineage.CorpusSnapshot = field(repr=False)
    _versions: tuple = field(repr=False)
    _seal: str = field(repr=False)

    @property
    def data(self):
        return json.loads(self._json)


def checked(observation):
    if not isinstance(observation, LineageObservation) or not hmac.compare_digest(
        observation._seal, _seal(observation._json, observation._corpus, observation._versions)
    ):
        _fail("invalid_lineage_observation")
    return observation.data


def source_request_id(observation, source_id):
    data = checked(observation)
    if source_id not in {row["source_id"] for row in data["sources"]}:
        _fail("unselected_source")
    return (
        "lineage-source:"
        + hashlib.sha256((data["request_id"] + "\0" + source_id).encode()).hexdigest()
    )


def _target(conn, focal, corpus_id):
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=?", (lineage_sets.TABLE,)
    ).fetchone()
    if not exists:
        _fail("lineage_schema_required")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(paper_lineage_sets)")]
    if columns != lineage_sets.COLUMNS.split():
        _fail("lineage_schema_changed")
    row = conn.execute(
        "SELECT " + ",".join(lineage_sets.COLUMNS.split()) + " FROM paper_lineage_sets "
        "WHERE paper_id=? AND corpus_key=?",
        (focal, corpus_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(zip(lineage_sets.COLUMNS.split(), row, strict=True))
    lineage_sets.validate_row(result)
    return result


def _token(conn, client, graphs, kind, identity):
    graph, _touches, own = graphs
    key = kind, identity
    current = graph.get(key)
    row = conn.execute(
        "SELECT revision FROM paperfact_sync_heads WHERE entity_type=? AND entity_id=?", key
    ).fetchone()
    return dict(
        workspace_id=client.journal.workspace_id,
        kind=kind,
        entity_id=identity,
        revision=row[0] if row else 0,
        predecessor=own[key]["operation_id"] if key in own else None,
        incarnation=current["incarnation"] if current else None,
        active=bool(current and current["active"]),
        parents=[
            dict(
                kind=p["kind"],
                id=p["id"],
                incarnation=graph.get((p["kind"], p["id"]), {}).get("incarnation"),
                active=bool(graph.get((p["kind"], p["id"]), {}).get("active")),
            )
            for p in current["parents"]
        ]
        if current
        else [],
    )


def _read_in(conn, corpus, corpus_id, request_id, *, captured=None, sizes=None, client=None):
    captured = research_lineage._checked(corpus) if captured is None else captured
    database = Path(captured["database"])
    if (
        not conn.in_transaction
        or generation._path(conn) != str(database)
        or list(generation._identity(database)) != captured["database_identity"]
    ):
        _fail("lineage_database_or_binding_changed")
    attached = conn._capture_client if sync_capture.enabled(conn) else None
    client = attached if client is None else client
    if captured["binding"] is not None:
        if (
            not isinstance(client, SyncClient)
            or client.journal.path.resolve() != database
            or captured["binding"]
            != dict(workspace_id=client.journal.workspace_id, device_id=client.journal.device_id)
        ):
            _fail("lineage_database_or_binding_changed")
        client.journal._binding(conn)
    elif client is not None or "paperfact_sync_identity" in _tables(conn):
        _fail("lineage_database_or_binding_changed")
    lineage_sets.uuid(corpus_id)
    lineage_sets.uuid(request_id)
    sources, versions = [], []
    graphs = client._optimistic_graph(conn) if client else None
    graph = graphs[0] if graphs else None
    parents = []
    for prior, source, document, snapshot in zip(
        captured["observed"], corpus.sources, corpus._documents, corpus._snapshots, strict=True
    ):
        local = prior["local_id"]
        if (
            parent_lifecycle(conn, "paper", local) != prior["lifecycle"]
            or research_lineage._paper(conn, local) != prior["identity"]
        ):
            _fail("lineage_parent_changed")
        parent = operation = source_graph = None
        if client:
            row = conn.execute(
                "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local,)
            ).fetchone()
            state = graph.get(("paper", row[0])) if row else None
            if not state or not state["active"]:
                _fail("lineage_parent_not_active")
            parent = dict(kind="paper", id=row[0], incarnation=state["incarnation"])
            parents.append(parent)
            if source["document_hash"] is not None:
                identity = file_id(row[0], "original_source", source["document_hash"])
                source_graph = graph.get(("research_file", identity))
                if source_graph and (
                    not source_graph["active"] or source_graph["parents"] != [parent]
                ):
                    _fail("lineage_original_retired")
                operation = desired_file(conn, identity)
        size = None
        if snapshot is not None:
            if sizes is None:
                _metadata, raw = _checked_snapshot(snapshot)
                size = len(raw)
            else:
                size = sizes[source["id"]]
            versions.append((document.path, file_change.version(document.path)))
        sources.append(
            dict(
                local_id=local,
                source_id=source["id"],
                document_hash=source["document_hash"],
                availability=source["availability"],
                size=size,
                identity=prior["identity"],
                lifecycle=prior["lifecycle"],
                parent=parent,
                source_graph=source_graph,
                source_operation=operation,
            )
        )
    target = _target(conn, sources[0]["local_id"], corpus_id)
    from paper_daily.lineage_capacity import local_room_in

    if target is None and not local_room_in(conn, sources[0]["local_id"], corpus_id):
        _fail("lineage_set_limit")
    observation = None
    if client:
        identity = content_id(dict(kind="paper", id=parents[0]["id"]), "lineage", corpus_id)
        observation = _token(conn, client, graphs, "research_content", identity)
        if observation["incarnation"] is not None and not observation["active"]:
            _fail("lineage_restore_required")
        if observation["parents"]:
            actual = [
                {key: p[key] for key in ("kind", "id", "incarnation")}
                for p in observation["parents"]
            ]
            if actual != parents:
                _fail("lineage_corpus_changed")
        else:
            observation["parents"] = [{**parent, "active": True} for parent in parents]
        if target is not None and observation["incarnation"] is None:
            _fail("lineage_target_not_enrolled")
    return dict(
        format="paperfact.lineage-observation.v1",
        database=str(database),
        database_identity=captured["database_identity"],
        binding=captured["binding"],
        binding_scope=_binding(conn, _tables(conn)),
        focal=sources[0]["local_id"],
        corpus_id=corpus_id,
        request_id=request_id,
        target=target,
        sources=sources,
        observation=observation,
    ), tuple(versions)


def observe_in(conn, corpus, corpus_id, request_id):
    """Read caller snapshot only. Metadata observation is not byte/publication authority."""
    _worker()
    data, versions = _read_in(conn, corpus, corpus_id, request_id)
    encoded = research_lineage._json(data)
    return LineageObservation(encoded, corpus, versions, _seal(encoded, corpus, versions))


def observe(corpus, corpus_id, request_id):
    """Convenient worker-only source validation followed by a read-only observation."""
    _worker()
    research_lineage.current(corpus)
    database = Path(research_lineage._checked(corpus)["database"])
    with closing(generation._connect(database)) as conn:
        conn.execute("BEGIN")
        return observe_in(conn, corpus, corpus_id, request_id)


def check_in(conn, observation, *, client=None):
    """Re-read exact SQL/native metadata; do not hash PDFs inside the write lock."""
    _worker()
    expected = checked(observation)
    actual, versions = _read_in(
        conn,
        observation._corpus,
        expected["corpus_id"],
        expected["request_id"],
        captured=json.loads(observation._corpus._json),
        sizes={s["source_id"]: s["size"] for s in expected["sources"]},
        client=client,
    )
    if canonical_json(actual) != canonical_json(expected) or versions != observation._versions:
        _fail("lineage_observation_changed")
    return True


def check_after_sources_in(conn, observation, operations, *, client=None, publication=None):
    """Allow only exact same-transaction original creations with this request's IDs."""
    _worker()
    expected = checked(observation)
    if not isinstance(operations, dict):
        _fail("invalid_lineage_source_operations")
    selected = {s["source_id"] for s in expected["sources"] if s["document_hash"] is not None}
    if set(operations) != selected:
        _fail("invalid_lineage_source_operations")
    actual, versions = _read_in(
        conn,
        observation._corpus,
        expected["corpus_id"],
        expected["request_id"],
        captured=json.loads(observation._corpus._json),
        sizes={s["source_id"]: s["size"] for s in expected["sources"]},
        client=client,
    )
    for before, after in zip(expected["sources"], actual["sources"], strict=True):
        if before["document_hash"] is None:
            continue
        operation = operations[before["source_id"]]
        if canonical_json(operation) != canonical_json(after["source_operation"]):
            _fail("lineage_source_operation_changed")
        if canonical_json(after) == canonical_json(before):
            continue
        parent = before["parent"]
        graph = after["source_graph"]
        if (
            before["source_graph"] is not None
            or parent is None
            or graph is None
            or operation["operation_id"] != source_request_id(observation, before["source_id"])
            or operation["entity_type"] != "research_file"
            or operation["action"] != "put"
            or operation["parents"] != [parent]
            or operation["payload"]["feature"] != "original_source"
            or operation["payload"]["paper_id"] != parent["id"]
            or operation["payload"]["slot"] != before["document_hash"]
            or operation["payload"]["assets"][0]["size"] != before["size"]
            or not graph["active"]
            or graph["incarnation"] != operation["incarnation"]
            or graph["parents"] != [parent]
        ):
            _fail("lineage_source_operation_changed")
        after["source_graph"] = before["source_graph"]
        after["source_operation"] = before["source_operation"]
    if publication is not None:
        from paper_daily import lineage_dependencies, lineage_projection, lineage_wire

        encoded = lineage_dependencies.canonical_operation(publication)
        owned = conn.execute(
            "SELECT envelope FROM paperfact_sync_operations WHERE operation_id=?",
            (expected["request_id"],),
        ).fetchone()
        marker, marked = lineage_projection._marker(conn, publication["entity_id"])
        if (
            owned is None or owned[0] != encoded
            or publication["operation_id"] != expected["request_id"]
            or publication["action"] != "put"
            or publication["workspace_id"] != expected["binding"]["workspace_id"]
            or publication["device_id"] != expected["binding"]["device_id"]
            or publication["content_address"]["key"] != expected["corpus_id"]
            or marker is None or marker["active"] != 1 or marked != publication
            or actual["target"] != lineage_wire.decode_row(conn, publication["payload"])
            or actual["observation"]["incarnation"] != publication["incarnation"]
            or not actual["observation"]["active"]
        ):
            _fail("lineage_publication_changed")
        # Only the exact own journal/marker/row mutation may differ. A queued
        # action is not claimed remotely accepted; later edits fail above.
        actual["target"] = expected["target"]
        actual["observation"] = expected["observation"]
    if canonical_json(actual) != canonical_json(expected) or versions != observation._versions:
        _fail("lineage_observation_changed")
    return True


@dataclass(frozen=True, slots=True)
class TargetLease:
    """Retained pre-call observation, distinct from current publication permission."""

    _observation: LineageObservation = field(repr=False)
    _seal: str = field(repr=False)


def _lease_seal(observation):
    data = [id(observation), observation._json, observation._seal, os.getpid()]
    return hmac.new(_KEY, research_lineage._json(data).encode(), "sha256").hexdigest()


def lease_data(lease):
    """Read original archive metadata even after its view/source becomes stale."""
    if (not isinstance(lease, TargetLease)
            or not isinstance(lease._observation, LineageObservation)
            or not hmac.compare_digest(lease._seal, _lease_seal(lease._observation))):
        _fail("invalid_lineage_target_lease")
    return lease._observation.data


def check_target(lease):
    """Worker-only fresh check, never a substitute for check_in at commit time."""
    _worker()
    data = lease_data(lease)
    research_lineage.current(lease._observation._corpus)
    with closing(generation._connect(Path(data["database"]))) as conn:
        conn.execute("BEGIN")
        return check_in(conn, lease._observation)


def target_lease(observation):
    """Capture only a still-current native observation, before submitting a job."""
    _worker()
    checked(observation)
    lease = TargetLease(observation, _lease_seal(observation))
    check_target(lease)
    return lease
