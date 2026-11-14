"""Explicit original-source restoration and retirement during device recovery.

A retained native file version proves the selected old immutable original. Fresh
observations authorize the target decision; history/cache alone never does.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from paper_daily import research_generation as generation
from paper_daily import sync_artifacts as artifacts
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_reading_group as references
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobManifest, BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_documents import _identity, _paper_current
from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation
from paper_daily.sync_source_files import (
    FEATURE,
    _inspection_paths,
    prepare_source,
    publish_source_in,
)

FORMAT = "paperfact.recovery-original-decision.v1"
ACTIONS = {"use_original": "put", "retire_original": "delete"}
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, request, selected, compared, planned, action):
    return hmac.new(
        _KEY,
        candidates._json(
            [
                observed._seal,
                request,
                selected,
                compared,
                planned,
                action,
            ]
        ).encode(),
        "sha256",
    ).hexdigest()


def _operation_id(request):
    return str(uuid5(NAMESPACE_URL, "paperfact:original-decision:" + request))


def _matches(put, root):
    canonical_operation(put)
    return (
        put["version"] == 2
        and put["entity_type"] == "research_file"
        and put["action"] == "put"
        and put["workspace_id"] == root["workspace_id"]
        and put["entity_id"] == root["entity_id"]
        and put["parents"] == root["parents"]
        and put["incarnation"] == root["incarnation"]
        and put["payload"]["feature"] == FEATURE
    )


def _retained_versions(conn, identity, check):
    total = 0
    for number, (raw,) in enumerate(
        conn.execute(
            "SELECT CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
            "FROM research_file_versions WHERE entity_id=? ORDER BY rowid DESC",
            (MAX_BYTES, identity),
        ),
        1,
    ):
        check()
        if raw is None or number > candidates.review.MAX_RECORDS:
            raise ValueError("Retained original exceeds its record/byte budget")
        total += len(raw.encode("utf-8"))
        if total > candidates.MAX_INDEX_BYTES:
            raise ValueError("Retained original exceeds its history byte budget")
        put = backup._decode(raw)
        canonical_operation(put)
        if put["entity_id"] != identity:
            raise ValueError("Retained original history belongs to another file slot")
        yield put


def retained_original(conn, root, check):
    """Locate actual retained file ownership, never a same-hash cache or guessed parent."""
    for put in _retained_versions(conn, root["entity_id"], check):
        if _matches(put, root):
            if history._old(conn, put["operation_id"], check) != put:
                raise ValueError("Retained original differs from native history")
            return put
    raise ValueError("No retained native original matches this selected source lifetime")


def inspect_retained(conn, paper, parent, document_hash, check):
    """Inspect document-pinned historical research; grants no current file lifetime."""
    from paper_daily.sync_files import file_id

    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_file_versions'"
    ).fetchone():
        return None
    binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
    if binding is None:
        raise ValueError("Retained original has no native workspace binding")
    identity = file_id(paper, FEATURE, document_hash)
    for put in _retained_versions(conn, identity, check):
        if (
            put["workspace_id"] == binding[0]
            and put["entity_type"] == "research_file"
            and put["action"] == "put"
            and put["parents"] == [parent]
            and put["payload"]["feature"] == FEATURE
            and put["payload"]["paper_id"] == paper
            and put["payload"]["source_document_hash"] == document_hash
        ):
            return _proof_in(conn, put, check)
    return None


def _selection(observed, change, action, cancelled, check):
    root = observed.source.details(change, cancelled=cancelled)["operation"]
    if (
        root["version"] != 2
        or root["entity_type"] != "research_file"
        or root["action"] != ACTIONS[action]
    ):
        raise ValueError("Select the matching native original-source action")
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        put = retained_original(conn, root, check)
    if root["action"] == "put" and root != put:
        # A selected put is itself the exact record, not another same-lifetime update.
        with closing(_readonly_connection(observed.source.database)) as conn:
            recorded = conn.execute(
                "SELECT operation FROM research_file_versions WHERE operation_id=?",
                (root["operation_id"],),
            ).fetchone()
            if not recorded or backup._decode(recorded[0]) != root:
                raise ValueError("Selected original lacks its retained ownership record")
        put = root
    observed.source._check(check)
    return dict(root=root, original=put)


def _proof_in(conn, put, check):
    owned = conn.execute(
        "SELECT CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
        "FROM research_file_versions WHERE operation_id=?",
        (MAX_BYTES, put["operation_id"]),
    ).fetchone()
    if not owned or owned[0] is None or backup._decode(owned[0]) != put:
        raise ValueError("The original has no exact retained ownership record")
    if history._old(conn, put["operation_id"], check) != put or not _paper_current(
        conn,
        dict(
            paper_id=put["payload"]["paper_id"], parent_incarnation=put["parents"][0]["incarnation"]
        ),
    ):
        raise ValueError("Retained original paper lifetime changed; review its parent first")
    paths = _inspection_paths(conn)
    if paths is None:
        raise ValueError("Retained original has no registered native storage")
    closure, _body, _blobs = artifacts.verify_closure(paths[0], put)
    asset = put["payload"]["assets"][0]
    path = paths[0].verified_path(BlobManifest(asset["sha256"], asset["size"]))
    proof = path, _identity(path)
    import pymupdf

    with pymupdf.open(path) as pdf:
        if pdf.needs_pass or pdf.page_count < 1:
            raise ValueError("The retained original is not a readable PDF")
    if not closure.matches(put):
        raise ValueError("The retained original changed during verification")
    native._original_current(proof)
    return proof


def _proof(observed, selected, check):
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        proof = _proof_in(conn, selected["original"], check)
    observed.source._check(check)
    native._original_current(proof)
    return proof


def _context(observed, selected, request, action):
    return dict(
        format=FORMAT,
        request_id=request,
        choice=action,
        source_fingerprint=candidates._fingerprint(selected["root"]),
        source_original=references._reference(selected["original"]),
        workspace_id=observed.binding["workspace_id"],
        device_id=observed.binding["device_id"],
        database_identity=list(observed.identity),
    )


def _prior(conn, observed, selected, request, action, check):
    choices._schema(conn)
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? THEN result "
        "END FROM integration_operations WHERE id=?",
        (choices.MAX_RECEIPT, request),
    ).fetchone()
    if row is None:
        return None
    receipt = backup._decode(row[1]) if row[1] else None
    context = _context(observed, selected, request, action)
    if (
        not isinstance(receipt, dict)
        or set(receipt) != set(context) | {"native"}
        or any(receipt.get(k) != v for k, v in context.items())
        or _hash(receipt) != row[0]
    ):
        raise ValueError("The original-source request or saved receipt changed")
    operation = (
        references._retained(conn, receipt["native"], check)
        if receipt["native"] is not None
        else None
    )
    put = selected["original"]
    if operation is None:
        if action != "retire_original":
            raise ValueError("Saved original restoration lost its native operation")
    elif (
        operation["version"] != 2
        or operation["entity_type"] != "research_file"
        or operation["workspace_id"] != context["workspace_id"]
        or operation["entity_id"] != put["entity_id"]
        or operation["action"] != ACTIONS[action]
        or [(p["kind"], p["id"]) for p in operation["parents"]]
        != [(p["kind"], p["id"]) for p in put["parents"]]
        or action == "use_original"
        and operation["payload"] != put["payload"]
    ):
        raise ValueError("Saved original decision disagrees with its native file history")
    return receipt


def _result(receipt, applied):
    return dict(
        receipt,
        state="saved_locally",
        applied=applied,
        replayed=False,
        recovery_complete=False,
        remote_acceptance_checked=False,
        semantic_validation="not_performed",
    )


@dataclass(frozen=True)
class OriginalDecision:
    observed: object = field(repr=False)
    change_id: str
    request_id: str
    selected_json: str = field(repr=False)
    comparison_json: str = field(repr=False)
    planned_json: str = field(repr=False)
    action: str
    already: bool
    _seal: str = field(repr=False)

    @property
    def comparison(self):
        return backup._decode(self.comparison_json)

    def apply(self, *, seconds=60, cancelled=lambda: False):
        check = backup._guard(seconds, cancelled)
        native._auth(self.observed, check)
        if not hmac.compare_digest(
            self._seal,
            _sign(
                self.observed,
                self.request_id,
                self.selected_json,
                self.comparison_json,
                self.planned_json,
                self.action,
            ),
        ):
            raise ValueError("Use the original prepared original-source decision")
        selected, planned = backup._decode(self.selected_json), backup._decode(self.planned_json)
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, selected, self.request_id, self.action, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("The saved source decision disappeared; compare again")
        self.observed._check(check)
        staged = proof = None
        if self.action == "use_original":
            proof = _proof(self.observed, selected, check)
            with closing(_readonly_connection(self.observed.database)) as conn:
                paths, client = _inspection_paths(conn), conn._capture_client
            if paths is None:
                raise ValueError("Original recovery needs registered native file storage")
            staged = prepare_source(
                client,
                selected["original"]["payload"]["paper_id"],
                proof[0],
                document_hash=selected["original"]["payload"]["source_document_hash"],
                parent_incarnation=self.comparison[0]["parents"][0]["incarnation"],
                store=BlobStore(paths[0].root),
                version_root=paths[1],
                request_id=_operation_id(self.request_id),
            )
            native._original_current(proof)
        with closing(
            sqlite3.connect(
                self.observed.database.as_uri() + "?mode=rw",
                uri=True,
                timeout=0.1,
                factory=CaptureConnection,
            )
        ) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                native._binding_in(conn, self.observed)
                prior = _prior(conn, self.observed, selected, self.request_id, self.action, check)
                if prior is not None:
                    return _result(prior, False)
                self.observed._check(check)
                _unused(conn, self.request_id)
                client, operation, applied = conn._capture_client, planned["operation"], False
                if staged is not None:
                    operation = publish_source_in(conn, client, staged, restore=True)
                    applied = operation["operation_id"] == _operation_id(self.request_id)
                elif planned["write"]:
                    check()
                    client.journal.apply_in(conn, operation, client.writer)
                    applied = True
                receipt = dict(
                    _context(self.observed, selected, self.request_id, self.action),
                    native=references._reference(operation),
                )
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                native._original_current(proof)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(self.observed.database)) != self.observed.identity:
                    raise ValueError("Original-source destination was replaced")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, applied)


def _unused(conn, request):
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?", (_operation_id(request),)
    ).fetchone():
        raise ValueError("Native original decision exists without its saved receipt")


def prepare(observed, change_id, request_id, *, action, seconds=60, cancelled=lambda: False):
    """Review one explicit source use/retirement; no paper/cache/history deletion."""
    _identifier(request_id)
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("Choose use_original or retire_original explicitly")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    selected = _selection(observed, change_id, action, cancelled, check)
    comparison, planned = [], dict(operation=None, write=False)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        prior = _prior(conn, observed, selected, request_id, action, check)
        if prior is None:
            _unused(conn, request_id)
            put, root = selected["original"], selected["root"]
            target = observed.compare(change_id, cancelled=cancelled)["target"]
            current = (
                target["pending_operations"][-1]
                if target["pending_operations"]
                else target["accepted_operation"]
            )
            state = target["entity_state"]
            if state is not None and current is None:
                raise ValueError("The original target has no matching native history")
            visible = artifacts.desired_file(conn, root["entity_id"])
            expected = (
                current
                if current and current["action"] == "put" and (state and state["active"])
                else None
            )
            if visible != expected:
                raise ValueError("Visible original ownership differs from native history")
            mapper = choices._parent_mapper(conn, observed, root, check)
            parents = [mapper(parent) for parent in root["parents"]]
            if action == "use_original":
                _proof(observed, selected, check)
            elif state and state["active"]:
                if current["parents"] != parents or current["payload"] != put["payload"]:
                    raise ValueError("Review the target's different original before retirement")
                planned = dict(
                    operation=conn._capture_client.new_graph_operation_in(
                        conn,
                        "research_file",
                        root["entity_id"],
                        {},
                        action="delete",
                        operation_id=_operation_id(request_id),
                    ),
                    write=True,
                )
            elif current and current["action"] == "delete":
                planned["operation"] = current
            title = conn.execute(
                "SELECT p.title FROM papers p JOIN research_paper_identity i ON "
                "p.id=i.local_id WHERE i.sync_id=?",
                (put["payload"]["paper_id"],),
            ).fetchone()
            comparison = [
                dict(
                    feature=FEATURE,
                    source=put["payload"],
                    current=visible["payload"] if visible else None,
                    parents=parents,
                    source_action=root["action"],
                    title=title[0] if title else put["payload"]["paper_id"],
                    state="absent" if state is None else "active" if state["active"] else "retired",
                )
            ]
    observed._check(check)
    values = [candidates._json(value) for value in (selected, comparison, planned)]
    return OriginalDecision(
        observed,
        change_id,
        request_id,
        *values,
        action,
        prior is not None,
        _sign(observed, request_id, *values, action),
    )
