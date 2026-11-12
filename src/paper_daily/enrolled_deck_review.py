"""Explicit shared Apply for full enrolled proposals, preserving the retained science.

The parent Review authenticates displayed data and serializes user actions. This
helper supplies worker I/O and the final original-owner/base transaction guards.
No sender observation or current receiver inputs become producer provenance.
"""

from __future__ import annotations

import copy
import json
from contextlib import closing
from uuid import NAMESPACE_URL, uuid5

from paper_daily import enrolled_deck_proposals as catalog
from paper_daily import presentations, sync_capture
from paper_daily import research_file_review as files
from paper_daily.research_lifecycle import parent_lifecycle
from paper_daily.sync_artifacts import activate, desired_file, materialize, stage_bytes
from paper_daily.sync_deck_files import encode_deck
from paper_daily.sync_deck_publication import _observation, _same_observation, runtime
from paper_daily.sync_files import canonical_json, closed, digest, identifier
from paper_daily.sync_journal import canonical_operation
from paper_daily.sync_source_files import input_versions


def _context(service):
    with closing(service._connect()) as conn:
        service._check(conn)
        client = runtime(database=service.path)
        if client is None:
            raise ValueError("Enrolled proposal review needs its original research workspace")
        store, root, storage = files._storage(conn)
        catalog._runtime(client, store, service.identity)
        service._check(conn)
    return client, store, root, storage


def _read(service, identity):
    client, store, root, storage = _context(service)
    proposal = catalog.read(
        client,
        store,
        identity,
        expected_native=service.identity,
        current=lambda: not service.closed,
    )
    return proposal, client, store, root, storage


def _witnesses(proposal):
    return {str(path): json.loads(canonical_json(version)) for path, version in proposal.witnesses}


def prepare(service, record):
    """Return a bounded metadata-only fragment for the parent's authenticated preview."""
    from paper_daily.research_review import digest as record_digest
    from paper_daily.research_review import encode

    proposal, client, store, _root, storage = _read(service, record["proposal_id"])
    if proposal.record != record:
        raise ValueError("Retained enrolled proposal changed during explicit review")
    if not proposal.current_parent:
        raise ValueError("Original enrolled paper lifecycle changed; preserve/export its proposal")
    science = proposal.content
    with closing(service._connect()) as conn:
        conn.execute("BEGIN")
        service._check(conn)
        catalog.assert_current_in(conn, proposal)
        paper = record["local_id"]
        mode = science["deck"]["mode"]
        observation = _observation(conn, client, paper, mode)
        parent = conn.execute("SELECT * FROM papers WHERE id=?", (paper,)).fetchone()
        if parent is None:
            raise ValueError("Original enrolled proposal parent is unavailable")
        token = parent_lifecycle(conn, "paper", paper)
        current = desired_file(conn, observation["entity_id"])
        original = json.loads(record["owner_json"])["observation"].get("artifact")
        witnesses = _witnesses(proposal)
        current_body = files._body(store, current["payload"], witnesses) if current else None
        original_body = files._body(store, original["payload"], witnesses) if original else None
        _store, _root, after = files._storage(conn)
        if after != storage:
            raise ValueError("Enrolled proposal storage changed during explicit review")
        slot = observation["observed"][1]["metadata"]
        restoring = bool(slot and not slot["active"])
        catalog.assert_current_in(conn, proposal)
        files._check_files(witnesses)
        service._check(conn)
    manifest = json.loads(record["manifest_json"])
    result = dict(
        apply=True,
        editable=False,
        retained=science["deck"],
        retained_evidence=science["evidence"],
        original=original_body,
        current=current_body,
        image_manifest=manifest["images"],
        original_manifest=manifest["originals"],
        source_hash=science["source_document_hash"],
        reason="Review the full retained scientific proposal before confirming the current target",
        scope={"kind": "paper", "id": paper},
        parent_token=token,
        parent_row=dict(parent),
        target={"id": paper, "title": parent["title"], "slot": mode, "restoring": restoring},
        requires_confirmation=True,
        expected=dict(
            proposal_id=record["proposal_id"],
            record_hash=record_digest(record),
            observation=observation,
            storage=storage,
            files=witnesses,
        ),
    )
    encode(result)  # The parent's HMAC preview must stay within its existing bound.
    return result


def _check(service, conn, data, proposal, *, allow_storage_creation=False):
    from paper_daily.research_review import digest as record_digest

    service._check(conn)
    expected = data["expected"]
    closed(expected, {"proposal_id", "record_hash", "observation", "storage", "files"})
    row = proposal.record
    if (
        data["id"] != row["proposal_id"]
        or expected["proposal_id"] != row["proposal_id"]
        or data["record_hash"] != expected["record_hash"]
        or record_digest(row) != expected["record_hash"]
    ):
        raise ValueError("Displayed retained enrolled proposal changed")
    catalog.assert_current_in(conn, proposal)
    before = expected["observation"]
    current = _observation(conn, proposal._owner.client, row["local_id"], before["mode"])
    if not _same_observation(current, before):
        raise ValueError("Displayed slide version or inputs changed; review again")
    parent = conn.execute("SELECT * FROM papers WHERE id=?", (row["local_id"],)).fetchone()
    if (
        parent is None
        or dict(parent) != data["parent_row"]
        or parent_lifecycle(conn, "paper", row["local_id"]) != data["parent_token"]
        or data["target"]["id"] != row["local_id"]
        or data["target"]["slot"] != before["mode"]
    ):
        raise ValueError("Displayed enrolled proposal parent changed")
    slot = current["observed"][1]["metadata"]
    if data["target"].get("restoring") is not bool(slot and not slot["active"]):
        raise ValueError("Displayed slide restoration choice changed")
    store, root, storage = files._storage(conn)
    if storage != expected["storage"]:
        old = expected["storage"]
        created = (
            allow_storage_creation
            and old["version_root"] is None
            and storage["version_root"] is not None
            and all(storage[k] == old[k] for k in ("registration", "blob_root", "blob_index"))
            and files._native(old["version_anchor"][0]) == old["version_anchor"][1]
        )
        if not created:
            raise ValueError("Original enrolled artifact storage changed")
    content = proposal.content
    if content["deck"] != data["retained"] or content["evidence"] != data["retained_evidence"]:
        raise ValueError("Displayed scientific proposal changed")
    if any(expected["files"].get(path) != stamp for path, stamp in _witnesses(proposal).items()):
        raise ValueError("Displayed scientific source bytes changed")
    files._check_files(expected["files"])
    service._check(conn)
    return proposal._owner.client, store, root


def _previous(service, conn, data, fingerprint, request_id):
    service._check(conn)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_review_receipts'"
    ).fetchone():
        return None
    row = conn.execute(
        "SELECT fingerprint,origin,origin_id,result FROM research_review_receipts "
        "WHERE request_id=?",
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    if tuple(row[:3]) != (fingerprint, "enrolled_deck", data["id"]):
        raise ValueError("Review retry changed its decision or proposal")
    result = json.loads(row[3])
    if result != {"decision": "applied", "operation_id": request_id}:
        raise ValueError("Enrolled review receipt has an incompatible result")
    return result


def apply(service, data, fingerprint, request_id, body, confirm_target):
    """Materialize off-lock; publish shared operation and receipt in one transaction."""
    from paper_daily.research_review import _setup

    identifier(request_id)
    digest(fingerprint)
    if data.get("origin") != "enrolled_deck":
        raise ValueError("Select an actual enrolled scientific proposal")
    if body is not None:
        raise ValueError("Retained slides require typed Apply, not edited JSON")
    if confirm_target is not True:
        raise ValueError("Confirm the reviewed enrolled target before applying")
    if not data.get("apply") or data.get("resume_state", "ready") != "ready":
        raise ValueError("Prepare and review the retained proposal before applying")
    with closing(service._connect()) as conn:
        previous = _previous(service, conn, data, fingerprint, request_id)
        if previous is not None:
            return previous
    proposal, _client, _store, _root, _storage = _read(service, data["id"])
    with closing(service._connect()) as conn:
        conn.execute("BEGIN")
        client, store, root = _check(service, conn, data, proposal)
    science = proposal.content
    deck = presentations.deck_from_dict(copy.deepcopy(science["deck"]))
    deck.paper_id = proposal.record["local_id"]
    deck.deck_id = str(uuid5(NAMESPACE_URL, "paperfact.enrolled.review:" + request_id))
    deck.edited = True
    deck._revision_figures = science["image_bytes"]
    payload, blobs = encode_deck(
        deck,
        proposal.record["portable_id"],
        input_versions=input_versions(),
        source_document_hash=science["source_document_hash"],
        evidence=science["evidence"],
    )
    owned = catalog._OwnedStore(proposal._owner, proposal._store, lambda: not service.closed)
    stage_bytes(owned, blobs)
    with closing(service._connect()) as conn:
        conn.execute("BEGIN")
        client, store, root = _check(service, conn, data, proposal)
        operation = client.new_graph_operation_in(
            conn,
            "research_file",
            data["expected"]["observation"]["entity_id"],
            payload,
            operation_id=request_id,
            restore=data["target"]["restoring"],
        )
    directory = materialize(store, root, operation)
    with closing(service._connect()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = _previous(service, conn, data, fingerprint, request_id)
        if previous is not None:
            return previous
        client, _store, _root = _check(service, conn, data, proposal, allow_storage_creation=True)
        current = client.new_graph_operation_in(
            conn,
            "research_file",
            operation["entity_id"],
            payload,
            operation_id=request_id,
            restore=data["target"]["restoring"],
        )
        if canonical_operation(current) != canonical_operation(operation):
            raise ValueError("Displayed synchronization base changed; review again")
        with sync_capture.suppress_capture(conn):
            client.journal.apply_in(conn, operation, client.writer)
            if not activate(conn, operation, directory):
                raise ValueError("Reviewed enrolled target changed before activation")
            _setup(conn)
            result = {"decision": "applied", "operation_id": operation["operation_id"]}
            service._receipt(conn, request_id, fingerprint, data, result)
            catalog.assert_current_in(conn, proposal)
            service._check(conn)
        conn.commit()
        return result
