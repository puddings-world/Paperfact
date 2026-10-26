"""Actual deck save/load boundary for explicitly configured research workspaces."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from paper_daily.sync_artifacts import (
    activate,
    applied_file,
    desired_file,
    materialize,
    paper_current,
    paths,
    stage_bytes,
    version_directory,
)
from paper_daily.sync_files import canonical_json, file_id


class StaleDeckError(ValueError):
    def __init__(self, candidate_id, message=None):
        self.candidate_id = candidate_id
        super().__init__(
            message or "The saved deck or its inputs changed; your candidate is retained for review"
        )


def _retain_original_draft(observation, deck):
    """Keep a late producer result in its ORIGINAL database, never the replacement."""
    path = Path(observation["database"])
    stat = path.stat()
    if [stat.st_dev, stat.st_ino] != observation["database_identity"]:
        raise ValueError("Original workspace was replaced; preserve the open draft")
    encoded = canonical_json(deck.to_dict())
    if len(encoded) > 8 * 1024**2:
        raise ValueError("Draft is oversized; preserve the open editor before changing workspace")
    identity = str(uuid4())
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
        ).fetchone()
        if row is None or tuple(row) != (observation["workspace_id"], observation["device_id"]):
            raise ValueError("Original workspace binding changed; preserve the open draft")
        conn.execute(
            "INSERT INTO research_file_drafts VALUES(?,?,?,?)",
            (
                identity,
                observation["entity_id"],
                encoded.decode(),
                canonical_json(observation).decode(),
            ),
        )
    return identity


def runtime():
    """No implicit enrollment or database creation; credentials never enter this seam."""
    from paper_daily import store
    from paper_daily.sync_client import SyncClient
    from paper_daily.sync_journal import Journal
    from paper_daily.sync_research import research_order_writer, research_writer

    path = Path(store.DB_PATH)
    if not path.is_file():
        return None
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='research_sync_binding'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT workspace,origin FROM research_sync_binding WHERE id=1"
        ).fetchone()
        if row is None:
            raise ValueError("Incomplete research binding")
    journal = Journal.attach_existing(path, workspace_id=row[0], device_id=row[1])
    return SyncClient.attach_existing(journal, research_writer, order_writer=research_order_writer)


def _observation(conn, client, local_id, mode):
    row = conn.execute(
        "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (local_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Paper needs a portable identity before publishing a deck")
    portable = row[0]
    identity = file_id(portable, "deck", mode)
    graph, _, own = client._optimistic_graph(conn)
    observed, refs = [], []
    for kind, entity in (("paper", portable), ("research_file", identity)):
        value = graph.get((kind, entity))
        head = conn.execute(
            "SELECT revision,operation FROM paperfact_sync_heads "
            "WHERE entity_type=? AND entity_id=?",
            (kind, entity),
        ).fetchone()
        head_operation_id = json.loads(head[1])["operation_id"] if head and head[1] else None
        predecessor = own.get((kind, entity), {}).get("operation_id")
        observed.append(
            {
                "kind": kind,
                "id": entity,
                "metadata": value,
                "revision": head[0] if head else 0,
                "depends_on": predecessor,
                "head_operation_id": head_operation_id,
            }
        )
        if value:
            refs.append(
                {
                    "kind": kind,
                    "id": entity,
                    "incarnation": value["incarnation"],
                    "revision": head[0] if head else 0,
                    "depends_on": predecessor,
                }
            )
    if observed[0]["metadata"] is None or not observed[0]["metadata"]["active"]:
        raise ValueError("Deck requires an active portable paper")
    inputs = {}
    for table in (
        "dives",
        "close_readings",
        "cites",
        "followups",
        "paper_context",
        "notes",
        "chat",
        "pdf_highlights",
        "pdf_ai_highlights",
    ):
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "paper_id" not in columns:
            continue
        lengths = "+".join(f'COALESCE(length(CAST("{column}" AS BLOB)),0)' for column in columns)
        count, size = conn.execute(
            f"SELECT count(*),COALESCE(sum({lengths}),0) FROM {table} WHERE paper_id=?", (local_id,)
        ).fetchone()
        if count > 1000 or size > 4 * 1024**2:
            raise ValueError(
                "Deck input snapshot exceeds its row/byte bound; no research was truncated"
            )
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE paper_id=? LIMIT 1001", (local_id,)
        ).fetchall()
        inputs[table] = sorted(
            [dict(zip(columns, tuple(row), strict=True)) for row in rows], key=canonical_json
        )
    encoded_inputs = canonical_json(inputs)
    if len(encoded_inputs) > 8 * 1024**2:
        raise ValueError("Deck input snapshot exceeds 8 MiB; no research was truncated")
    input_hash = hashlib.sha256(encoded_inputs).hexdigest()
    from paper_daily.sync_documents import applied_document, desired_document

    desired, applied = desired_document(conn, portable), applied_document(conn, portable)
    document = applied if applied == desired else None
    documents = []
    if document:
        documents = [
            {
                key: document[key]
                for key in (
                    "paper_id",
                    "operation_id",
                    "incarnation",
                    "parent_incarnation",
                    "sha256",
                )
            }
        ]
    db = client.journal.path.resolve()
    stat = db.stat()
    return {
        "database": str(db),
        "database_identity": [stat.st_dev, stat.st_ino],
        "device_id": client.journal.device_id,
        "workspace_id": client.journal.workspace_id,
        "local_id": local_id,
        "paper_id": portable,
        "entity_id": identity,
        "mode": mode,
        "observed": observed,
        "artifact": desired_file(conn, identity),
        "desired_document": desired,
        "applied_document": applied,
        "inputs_sha256": input_hash,
        "input_versions": {
            "schema_version": 1,
            "complete": False,
            "entities": refs,
            "documents": documents,
            "inputs_sha256": input_hash,
        },
    }


def _same_observation(current, loaded):
    """Acknowledging an already observed local op does not change its visible content."""
    ignored = {"observed", "input_versions"}
    if {k: v for k, v in current.items() if k not in ignored} != {
        k: v for k, v in loaded.items() if k not in ignored
    }:
        return False
    for before, after in zip(loaded["observed"], current["observed"], strict=True):
        if before["revision"] < 0:
            return False
        if (before["kind"], before["id"]) != (after["kind"], after["id"]):
            return False
        if (before["depends_on"] or before["head_operation_id"]) != (
            after["depends_on"] or after["head_operation_id"]
        ):
            return False

        def lifecycle(value):
            return {k: v for k, v in value.items() if k != "structure_revision"} if value else None

        if lifecycle(before["metadata"]) != lifecycle(after["metadata"]):
            return False
    return True


def observe_deck(paper_id, mode):
    client = runtime()
    if client is None:
        return None
    with client.journal.transaction() as conn:
        return _observation(conn, client, paper_id, mode)


def publish_deck(deck, *, observation, request_id=None, evidence=None):
    from paper_daily.sync_deck_files import encode_deck

    client = runtime()
    if client is None:
        if observation is not None:
            retained = _retain_original_draft(observation, deck)
            raise StaleDeckError(retained, "Workspace changed; original draft retained")
        return None
    if (
        not isinstance(observation, dict)
        or observation.get("local_id") != deck.paper_id
        or observation.get("mode") != deck.mode
    ):
        raise ValueError("Managed deck saves require the observation captured when opened")
    db = client.journal.path.resolve()
    stat = db.stat()
    if (
        observation.get("database"),
        observation.get("database_identity"),
        observation.get("workspace_id"),
        observation.get("device_id"),
    ) != (
        str(db),
        [stat.st_dev, stat.st_ino],
        client.journal.workspace_id,
        client.journal.device_id,
    ):
        retained = _retain_original_draft(observation, deck)
        raise StaleDeckError(
            retained, "Deck belongs to another workspace/device; original draft retained"
        )
    with client.journal.transaction() as conn:
        configured = paths(conn)
    if configured is None:
        raise ValueError("Configure local artifact storage before saving this managed deck")
    blob_store, root = configured
    # Pin through retained ownership rather than the mutable legacy assets folder.
    with client.journal.transaction() as conn:
        prior_binding = applied_file(conn, observation["entity_id"])
    candidate = deepcopy(deck)
    supplied_evidence = evidence is not None
    loaded = getattr(deck, "_file_operation", None)
    evidence_binding = loaded or observation.get("artifact") or prior_binding
    if evidence_binding is not None:
        candidate._file_operation = evidence_binding
        if evidence is None and deck.source_hash:
            from paper_daily.sync_blobs import BlobManifest
            from paper_daily.sync_files import read_json

            old_payload = evidence_binding["payload"]
            body_row = old_payload["body"]
            body = read_json(
                blob_store.verified_path(
                    BlobManifest(body_row["sha256"], body_row["size"])
                ).read_bytes()
            )
            evidence_id = body["evidence_asset"]
            if evidence_id and body["deck"]["source_hash"] == deck.source_hash:
                row = next(a for a in old_payload["assets"] if a["id"] == evidence_id)
                evidence = read_json(
                    blob_store.verified_path(BlobManifest(row["sha256"], row["size"])).read_bytes()
                )
    documents = observation["input_versions"]["documents"]
    provenance = (
        loaded["payload"]
        if loaded is not None
        else (
            observation["artifact"]["payload"]
            if observation.get("artifact") is not None and not supplied_evidence
            else None
        )
    )
    input_versions = deepcopy(
        provenance["input_versions"] if provenance else observation["input_versions"]
    )
    if provenance:
        source_document_hash = provenance["source_document_hash"]
    else:
        hashes = {
            row.get("document_hash")
            for row in (evidence or {}).get("sources", [])
            if row.get("kind") in {"original", "figure"} and row.get("document_hash")
        }
        source_document_hash = next(iter(hashes)) if len(hashes) == 1 else None
        input_versions["documents"] = [
            row for row in documents if row["sha256"] == source_document_hash
        ]
    payload, blobs = encode_deck(
        candidate,
        observation["paper_id"],
        input_versions=input_versions,
        source_document_hash=source_document_hash,
        evidence=evidence,
    )
    stage_bytes(blob_store, blobs)
    request_id = request_id or str(uuid4())
    stale = False
    with client.journal.transaction() as conn:
        prior = conn.execute(
            "SELECT operation FROM research_file_versions WHERE operation_id=?", (request_id,)
        ).fetchone()
        if prior:
            operation = json.loads(prior[0])
            if (
                operation["payload"] != payload
                or operation["device_id"] != client.journal.device_id
            ):
                raise ValueError("Deck save request identity was reused")
        elif not _same_observation(
            _observation(conn, client, deck.paper_id, deck.mode), observation
        ):
            candidate = canonical_json(payload).decode()
            conn.execute(
                "INSERT OR IGNORE INTO research_file_candidates VALUES(?,?,?,?)",
                (
                    request_id,
                    observation["entity_id"],
                    candidate,
                    canonical_json(observation).decode(),
                ),
            )
            stale = True
        else:
            operation = client.new_graph_operation_in(
                conn, "research_file", observation["entity_id"], payload, operation_id=request_id
            )
            client.journal.apply_in(conn, operation, client.writer)
    if stale:
        raise StaleDeckError(request_id)
    directory = materialize(blob_store, root, operation)
    with client.journal.transaction() as conn:
        if not activate(conn, operation, directory):
            raise StaleDeckError(request_id)
        deck._file_observation = _observation(conn, client, deck.paper_id, deck.mode)
        deck._file_operation = operation
        deck._file_directory = directory
    # Only after durable save/activation expose pinned immutable source locations.
    assets = {row["id"]: row for row in operation["payload"]["assets"] if row["role"] == "figure"}
    deck.figures = [
        dict(row, asset=assets[row["id"]]["sha256"] + ".png") if row["id"] in assets else dict(row)
        for row in deck.figures
    ]
    return directory / "deck.json"


def load_managed_deck(paper_id, mode):
    """Return (managed slot exists, deck). Missing new bytes retain older applied version."""
    from paper_daily.presentations import deck_from_dict

    client = runtime()
    if client is None:
        return False, None
    with client.journal.transaction() as conn:
        observation = _observation(conn, client, paper_id, mode)
        identity = observation["entity_id"]
        known = conn.execute(
            "SELECT active FROM research_file_desired WHERE entity_id=?", (identity,)
        ).fetchone()
        if known is None:
            return False, None
        operation = applied_file(conn, identity)
        if not known[0] or operation is None or not paper_current(conn, operation):
            return True, None
        configured = paths(conn)
    if configured is None:
        return True, None
    blob_store, root = configured
    directory = materialize(blob_store, root, operation)
    if Path(directory) != version_directory(root, operation):
        raise ValueError("Invalid artifact version")
    deck = deck_from_dict(json.loads((directory / "deck.json").read_text(encoding="utf-8")))
    deck.paper_id = paper_id
    with client.journal.transaction() as conn:
        if applied_file(conn, identity) != operation or desired_file(conn, identity) is None:
            return True, None
        # The displayed old revision is not a fresh base for a newer pending deck.
        current = desired_file(conn, identity)
        if current != operation:
            observation["observed"][1]["revision"] = -1
    deck._file_observation = observation
    deck._file_operation = operation
    deck._file_directory = directory
    deck._file_pending = current != operation
    return True, deck


def managed_figure_bytes(deck, figure_id):
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_deck_files import validate_png

    client = runtime()
    if client is None:
        raise ValueError("Managed deck workspace is unavailable")
    figure = next(row for row in deck.figures if row["id"] == figure_id)
    asset = figure.get("asset", "")
    if not isinstance(asset, str) or not asset.endswith(".png"):
        raise ValueError("Managed figure needs its immutable PNG identity")
    sha256 = asset[:-4]
    with client.journal.transaction() as conn:
        configured = paths(conn)
        mapping = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (deck.paper_id,)
        ).fetchone()
        if configured is None or mapping is None:
            raise ValueError("Managed figure storage unavailable")
        identity = file_id(mapping[0], "deck", deck.mode)
        rows = conn.execute(
            "SELECT operation FROM research_file_versions WHERE entity_id=?", (identity,)
        ).fetchall()
        description = None
        for row in rows:
            operation = json.loads(row[0])
            for item in operation["payload"]["assets"]:
                if (
                    item["id"] == figure_id
                    and item["sha256"] == sha256
                    and item["role"] == "figure"
                ):
                    description = item
                    break
        if description is None:
            raise ValueError("Figure has no retained artifact ownership")
    store = configured[0]
    data = store.verified_path(BlobManifest(sha256, description["size"])).read_bytes()
    validate_png(data)
    return data


def managed_versions(paper_id, mode):
    client = runtime()
    if client is None:
        return None
    with client.journal.transaction() as conn:
        observation = _observation(conn, client, paper_id, mode)
        rows = conn.execute(
            "SELECT operation FROM research_file_versions WHERE entity_id=? ORDER BY rowid DESC",
            (observation["entity_id"],),
        ).fetchall()
        if not rows:
            return None
    return [json.loads(row[0]) for row in rows]


def restore_managed(paper_id, mode, filename):
    from paper_daily.presentations import deck_from_dict, now

    versions = managed_versions(paper_id, mode)
    if versions is None:
        return None
    selected = next(
        (op for op in versions if filename == mode + "-" + op["operation_id"] + ".json"), None
    )
    if selected is None:
        raise ValueError("Unknown managed deck revision")
    observation = observe_deck(paper_id, mode)
    client = runtime()
    with client.journal.transaction() as conn:
        configured = paths(conn)
    if configured is None:
        raise ValueError("Artifact storage unavailable")
    directory = materialize(*configured, selected)
    raw = json.loads((directory / "deck.json").read_text(encoding="utf-8"))
    deck = deck_from_dict(raw)
    deck.paper_id, deck.deck_id, deck.created_at = paper_id, uuid4().hex, now()
    deck._file_operation = selected
    publish_deck(deck, observation=observation)
    return deck


def version_summaries(paper_id, mode):
    from paper_daily.sync_blobs import BlobManifest
    from paper_daily.sync_deck_files import validate_body
    from paper_daily.sync_files import read_json

    versions = managed_versions(paper_id, mode)
    if versions is None:
        return None
    client = runtime()
    with client.journal.transaction() as conn:
        configured = paths(conn)
    result = []
    for operation in versions:
        payload = operation["payload"]
        description = payload["body"]
        title, created_at, count = "Revision bytes unavailable", "", 0
        if configured is not None:
            try:
                raw = read_json(
                    configured[0]
                    .verified_path(BlobManifest(description["sha256"], description["size"]))
                    .read_bytes()
                )
                parsed = validate_body(raw, payload)
                title, created_at, count = parsed.title, parsed.created_at, len(parsed.slides)
            except (OSError, ValueError):
                pass
        result.append(
            {
                "file": mode + "-" + operation["operation_id"] + ".json",
                "title": title,
                "created_at": created_at,
                "slides": count,
            }
        )
    return result
