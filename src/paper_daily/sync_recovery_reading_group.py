"""Atomic recovery of exact explanation-link inputs and their owned original.

Optional absent explanations are explicit deletion choices. Manual/PDF marks stay
independent; source lookup alone never authorizes a target write.
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
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_highlight_group as highlights
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_reading_context as reading_context
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import content_id
from paper_daily.sync_journal import _identifier
from paper_daily.sync_source_files import (
    FEATURE,
    _inspection_paths,
    prepare_source,
    publish_source_in,
)

FORMAT = "paperfact.recovery-reading-group.v1"
FEATURES = (*reading_context.FEATURES, "reading_links")
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, request, source_json, operation_json, comparison_json, replace):
    return hmac.new(
        _KEY,
        candidates._json(
            [
                observed._seal,
                request,
                source_json,
                operation_json,
                comparison_json,
                replace,
            ]
        ).encode(),
        "sha256",
    ).hexdigest()


def _validate_sources(sources, root):
    if (
        root["version"] != 2
        or root["action"] != "put"
        or root["entity_type"] != "research_content"
        or root["payload"].get("feature") != "reading_links"
        or root["payload"]["key"] != "main"
        or not root["payload"]["source_document_hash"]
        or sources[-1] != root
        or not all(
            reading_context._valid(op, root, feature) and (op is None or op["action"] == "put")
            for feature, op in zip(FEATURES[:3], sources[:3], strict=True)
        )
        or not reading_context._matches(root, tuple(sources[:3]))
    ):
        raise ValueError("The reading group does not match its exact recorded inputs")


def _proof(observed, sources, check):
    _validate_sources(sources, sources[-1])
    proof, _payloads = highlights._locate_source(observed.source, sources[2], check)
    return proof


def _context(observed, root, request, replace):
    return dict(
        format=FORMAT,
        request_id=request,
        replace=replace,
        source_fingerprint=candidates._fingerprint(root),
        workspace_id=observed.binding["workspace_id"],
        device_id=observed.binding["device_id"],
        database_identity=list(observed.identity),
    )


def _reference(operation):
    return (
        dict(id=operation["operation_id"], fingerprint=candidates._fingerprint(operation))
        if operation is not None
        else None
    )


def _retained(conn, reference, check):
    if not isinstance(reference, dict) or set(reference) != {"id", "fingerprint"}:
        raise ValueError("Invalid reading-group operation reference")
    _identifier(reference["id"])
    operation = history._old(conn, reference["id"], check)
    if candidates._fingerprint(operation) != reference["fingerprint"]:
        raise ValueError("Reading-group operation fingerprint changed")
    return operation


def _prior(conn, observed, root, request, replace, check):
    choices._schema(conn)
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END "
        "FROM integration_operations WHERE id=?",
        (choices.MAX_RECEIPT, request),
    ).fetchone()
    if row is None:
        return None
    receipt = backup._decode(row[1]) if row[1] else None
    context = _context(observed, root, request, replace)
    if (
        not isinstance(receipt, dict)
        or set(receipt) != set(context) | {"sources", "native", "original"}
        or any(receipt.get(k) != v for k, v in context.items())
        or _hash(receipt) != row[0]
        or not isinstance(receipt["sources"], list)
        or len(receipt["sources"]) != 4
        or not isinstance(receipt["native"], list)
        or len(receipt["native"]) != 4
    ):
        raise ValueError("The reading-group request or saved receipt changed")
    with closing(_readonly_connection(observed.source.database)) as old:
        old.execute("BEGIN")
        sources = [
            _retained(old, ref, check) if ref is not None else None for ref in receipt["sources"]
        ]
    _validate_sources(sources, root)
    native_ops = [
        _retained(conn, ref, check) if ref is not None else None for ref in receipt["native"]
    ]
    if native_ops[-1] is None:
        raise ValueError("Reading-group receipt lost its root operation")
    parents = native_ops[-1]["parents"]
    for feature, source, operation in zip(FEATURES, sources, native_ops, strict=True):
        if operation is None:
            if source is not None:
                raise ValueError("Reading-group receipt lost a required member")
            continue
        if (
            operation["version"] != 2
            or operation["entity_type"] != "research_content"
            or operation["workspace_id"] != context["workspace_id"]
            or operation["parents"] != parents
            or operation["entity_id"] != content_id(root["payload"]["scope"], feature, "main")
            or operation["action"] != ("put" if source else "delete")
            or source is not None
            and operation["payload"] != source["payload"]
        ):
            raise ValueError("Saved reading group disagrees with native research")
    if not reading_context._matches(
        native_ops[-1], tuple(map(reading_context._put, native_ops[:3]))
    ):
        raise ValueError("Saved reading-group inputs no longer match their links")
    original = _retained(conn, receipt["original"], check)
    if (
        original["version"] != 2
        or original["action"] != "put"
        or original["entity_type"] != "research_file"
        or original["workspace_id"] != context["workspace_id"]
        or original["parents"] != parents
        or original["payload"]["feature"] != FEATURE
        or original["payload"]["paper_id"] != root["payload"]["scope"]["id"]
        or original["payload"]["source_document_hash"] != root["payload"]["source_document_hash"]
    ):
        raise ValueError("Saved reading group lost its native original receipt")
    return receipt


def _unused_request(conn, request, sources):
    root = sources[-1]
    identities = [
        str(
            uuid5(
                NAMESPACE_URL, request + ":" + content_id(root["payload"]["scope"], feature, "main")
            )
        )
        for feature in FEATURES
    ]
    identities.append(str(uuid5(NAMESPACE_URL, "paperfact:reading-group-original:" + request)))
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id IN (?,?,?,?,?) LIMIT 1",
        identities,
    ).fetchone():
        raise ValueError("Native reading-group writes exist without their decision receipt")


def _result(receipt, applied):
    return dict(
        receipt,
        choice="reading_group",
        state="saved_locally",
        applied=applied,
        recovery_complete=False,
        remote_accepted=None,
        remote_acceptance_checked=False,
        semantic_validation="not_performed",
        replayed=False,
    )


@dataclass(frozen=True)
class ReadingGroup:
    observed: object = field(repr=False)
    change_id: str
    request_id: str
    source_json: str = field(repr=False)
    operation_json: str = field(repr=False)
    comparison_json: str = field(repr=False)
    replace: bool
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
                self.source_json,
                self.operation_json,
                self.comparison_json,
                self.replace,
            ),
        ):
            raise ValueError("Use the original prepared reading group")
        sources, operations = backup._decode(self.source_json), backup._decode(self.operation_json)
        root = sources[-1]
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, root, self.request_id, self.replace, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("The recorded reading-group decision disappeared; inspect it again")
        self.observed._check(check)
        proof = _proof(self.observed, sources, check)
        with closing(_readonly_connection(self.observed.database)) as conn:
            conn.execute("BEGIN")
            native._binding_in(conn, self.observed)
            paths = _inspection_paths(conn)
            client = conn._capture_client
        if paths is None:
            raise ValueError("The reading group needs registered native original storage")
        self.observed._check(check)
        from paper_daily.sync_blobs import BlobStore

        staged = prepare_source(
            client,
            root["payload"]["scope"]["id"],
            proof[0],
            document_hash=root["payload"]["source_document_hash"],
            parent_incarnation=operations[-1]["operation"]["parents"][0]["incarnation"],
            store=BlobStore(paths[0].root),
            version_root=paths[1],
            request_id=str(
                uuid5(NAMESPACE_URL, "paperfact:reading-group-original:" + self.request_id)
            ),
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
                prior = _prior(conn, self.observed, root, self.request_id, self.replace, check)
                if prior is not None:
                    return _result(prior, False)
                self.observed._check(check)
                _unused_request(conn, self.request_id, sources)
                client = conn._capture_client
                original = publish_source_in(conn, client, staged)
                for item in operations:
                    check()
                    if item["write"]:
                        client.journal.apply_in(conn, item["operation"], client.writer)
                current = native.inspect_original(
                    conn,
                    root["payload"]["scope"]["id"],
                    operations[-1]["operation"]["parents"][0],
                    root["payload"]["source_document_hash"],
                    check,
                )
                receipt = dict(
                    _context(self.observed, root, self.request_id, self.replace),
                    sources=[_reference(o) for o in sources],
                    native=[_reference(i["operation"]) for i in operations],
                    original=_reference(original),
                )
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(self.observed.database)) != self.observed.identity:
                    raise ValueError("Reading-group destination was replaced")
                native._original_current(current)
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, True)


def prepare(observed, change_id, request_id, *, replace=False, seconds=60, cancelled=lambda: False):
    """Prepare a complete reading group; differing/deleted members need explicit replace."""
    _identifier(request_id)
    if type(replace) is not bool:
        raise ValueError("Choose explicitly whether to replace the group")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    root = observed.source.details(change_id, cancelled=cancelled)["operation"]
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        prior = _prior(conn, observed, root, request_id, replace, check)
        if prior is not None:
            sources = [None, None, None, root]
            operations, comparisons = [], []
        else:
            sources = [
                member["operation"]
                for member in reading_context.resolve(
                    observed.source,
                    change_id,
                    seconds=seconds,
                    cancelled=cancelled,
                )["members"]
            ]
            _validate_sources(sources, root)
            _unused_request(conn, request_id, sources)
            mapped = choices._parent_mapper(conn, observed, root, check)
            parents = [mapped(parent) for parent in root["parents"]]
            client, operations, comparisons = conn._capture_client, [], []
            for feature, source in zip(FEATURES, sources, strict=True):
                check()
                identity = content_id(root["payload"]["scope"], feature, "main")
                template = (
                    source["payload"]
                    if source
                    else dict(
                        scope=root["payload"]["scope"],
                        feature=feature,
                        key="main",
                    )
                )
                current = history._head(conn, identity)
                state = client._optimistic_graph(conn)[0].get(("research_content", identity))
                visible = history._visible(conn, template)
                expected = (
                    current["payload"]
                    if current and current["action"] == "put" and (state and state["active"])
                    else None
                )
                if visible != expected:
                    raise ValueError(
                        "Visible research differs from native history; preserve it first"
                    )
                same = (
                    source is not None
                    and current is not None
                    and state
                    and state["active"]
                    and current["action"] == "put"
                    and current["payload"] == source["payload"]
                    and current["parents"] == parents
                )
                absent = source is None and not (state and state["active"])
                if state is not None and not same and not absent and not replace:
                    raise ValueError("Review different or deleted group members before replacement")
                operation = (
                    None
                    if absent
                    else current
                    if same
                    else client.new_graph_operation_in(
                        conn,
                        "research_content",
                        identity,
                        source["payload"] if source else {},
                        action="put" if source else "delete",
                        operation_id=str(uuid5(NAMESPACE_URL, request_id + ":" + identity)),
                        restore=bool(
                            source
                            and state
                            and (not state["active"] or state["parents"] != parents)
                        ),
                    )
                )
                if operation is not None and operation["parents"] != parents:
                    raise ValueError("Reading-group paper differs from its proven parent mapping")
                operations.append(dict(operation=operation, write=not (same or absent)))
                comparisons.append(
                    dict(
                        feature=feature,
                        source=source["payload"]["data"] if source else None,
                        current=visible["data"] if visible else None,
                        state="absent"
                        if state is None
                        else "active"
                        if state["active"]
                        else "retired",
                    )
                )
    observed._check(check)
    values = [candidates._json(value) for value in (sources, operations, comparisons)]
    return ReadingGroup(
        observed,
        change_id,
        request_id,
        *values,
        replace,
        prior is not None,
        _sign(observed, request_id, *values, replace),
    )
