"""Recover a selected highlight analysis, exact PDF and verified located marks.

Manual and unrelated highlights remain untouched. This never invokes a model.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from paper_daily import annotation_content, pdf_highlights
from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_note_copy as native
from paper_daily.highlight_draft_verification import _source_text_hash
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import content_id, content_payload
from paper_daily.sync_journal import _identifier
from paper_daily.sync_source_files import _inspection_paths, prepare_source, publish_source_in

FORMAT = "paperfact.recovery-highlight-group.v1"
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, change, request, operations, comparison, replace):
    return hmac.new(
        _KEY,
        candidates._json(
            [
                observed._seal,
                change,
                request,
                operations,
                comparison,
                replace,
            ]
        ).encode(),
        "sha256",
    ).hexdigest()


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


def _root(observed, change):
    root = observed.source.details(change)["operation"]
    payload = root["payload"]
    if (
        root["version"] != 2
        or root["entity_type"] != "research_content"
        or root["action"] != "put"
        or payload.get("feature") != "highlight_analysis"
        or payload["key"] != "main"
        or not payload["source_document_hash"]
        or payload["data"]["document_hash"] != payload["source_document_hash"]
    ):
        raise ValueError("Select a complete source-bound highlight analysis")
    annotation_content.validate("highlight_analysis", payload["data"]["body_json"])
    return root


def _located(observed, root, check):
    return _locate_source(observed.source, root, check)


def _locate_source(source, root, check):
    payload = root["payload"]
    with closing(_readonly_connection(source.database)) as conn:
        conn.execute("BEGIN")
        proof = native.inspect_original(
            conn, payload["scope"]["id"], root["parents"][0],
            payload["source_document_hash"], check,
            allow_retained=True,
        )
    from paper_daily.sync_documents import MAX_PDF_BYTES

    with proof[0].open("rb") as stream:
        data = stream.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("Highlight original exceeds its byte budget")
    if _source_text_hash(data, lambda: (check(), False)[1]) != payload["data"]["source_hash"]:
        raise ValueError("Highlight analysis does not match its exact original text")
    fingerprint, located, unmatched = pdf_highlights.locate(
        proof[0],
        payload["data"]["body_json"],
    )
    native._original_current(proof)
    if fingerprint != payload["source_document_hash"] or unmatched:
        raise ValueError("Locate every recorded highlight in its exact original before recovery")
    result = [payload]
    for key, anchor, item in located:
        result.append(
            dict(
                scope=payload["scope"],
                feature="ai_highlight",
                key=fingerprint + ":" + key,
                source_document_hash=fingerprint,
                data=dict(
                    analysis_hash=payload["data"]["source_hash"],
                    anchor=anchor,
                    quote=item["text"],
                    reason=item["reason"],
                    hidden=0,
                ),
            )
        )
    source._check(check)
    return proof, result


def _visible(conn, payload):
    if payload["feature"] == "highlight_analysis":
        return history._visible(conn, payload)
    paper = conn.execute(
        "SELECT local_id FROM research_paper_identity WHERE sync_id=?", (payload["scope"]["id"],)
    ).fetchone()
    if paper is None:
        raise ValueError("The highlight paper has no native mapping")
    cursor = conn.execute(
        "SELECT * FROM pdf_ai_highlights WHERE paper_id=? AND document_hash=? AND source_key=?",
        (paper[0], payload["source_document_hash"], payload["key"].split(":", 1)[1]),
    )
    row = cursor.fetchone()
    return (
        content_payload(
            conn,
            "pdf_ai_highlights",
            dict(
                zip(
                    (column[0] for column in cursor.description),
                    row,
                    strict=True,
                )
            ),
        )
        if row is not None
        else None
    )


def _expected(conn, payload):
    identity = content_id(payload["scope"], payload["feature"], payload["key"])
    current = history._head(conn, identity)
    state = conn._capture_client._optimistic_graph(conn)[0].get(("research_content", identity))
    visible = _visible(conn, payload)
    expected = (
        current["payload"]
        if current and current["action"] == "put" and (state and state["active"])
        else None
    )
    if visible != expected:
        raise ValueError("Visible highlights differ from native history; preserve them first")
    return identity, current, state, visible


def _source_value(conn, payload):
    identity = content_id(payload["scope"], payload["feature"], payload["key"])
    current = history._head(conn, identity)
    if current and current["action"] == "delete":
        raise ValueError("A deleted source highlight needs a separate decision")
    expected = current["payload"] if current else None
    if _visible(conn, payload) != expected:
        raise ValueError("Source highlights differ from native history; preserve them first")
    if expected and (
        expected["source_document_hash"] != payload["source_document_hash"]
        or expected["data"]["quote"] != payload["data"]["quote"]
    ):
        raise ValueError("The source highlight quote differs from its selected identity")
    return expected


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
    items = root["payload"]["data"]["body_json"]["items"]
    if (
        not isinstance(receipt, dict)
        or set(receipt) != set(context) | {"native", "original"}
        or any(receipt.get(k) != v for k, v in context.items())
        or _hash(receipt) != row[0]
        or not isinstance(receipt["native"], list)
        or len(receipt["native"]) != len(items) + 1
    ):
        raise ValueError("Highlight recovery receipt or request changed")
    analysis = None
    for index, reference in enumerate(receipt["native"]):
        if not isinstance(reference, dict) or set(reference) != {"id", "fingerprint"}:
            raise ValueError("Invalid highlight member receipt")
        operation = history._old(conn, reference["id"], check)
        payload = operation["payload"]
        if (
            operation["entity_type"] != "research_content"
            or operation["action"] != "put"
            or operation["workspace_id"] != context["workspace_id"]
            or candidates._fingerprint(operation) != reference["fingerprint"]
            or payload["scope"] != root["payload"]["scope"]
            or payload["source_document_hash"] != root["payload"]["source_document_hash"]
        ):
            raise ValueError("Highlight receipt differs from native research")
        if index == 0:
            if payload != root["payload"]:
                raise ValueError("Highlight analysis receipt names another source value")
            analysis = operation
        else:
            item = items[index - 1]
            key = hashlib.sha256(f"{item['page']}:{item['text']}".encode()).hexdigest()
            values = payload["data"]
            if (
                payload["feature"] != "ai_highlight"
                or payload["key"] != payload["source_document_hash"] + ":" + key
                or operation["parents"] != analysis["parents"]
                or values["quote"] != item["text"]
                or values["reason"] != item["reason"]
                or values["analysis_hash"] != root["payload"]["data"]["source_hash"]
                or values["anchor"]["p0"] != item["page"] - 1
                or values["anchor"]["p1"] != values["anchor"]["p0"]
            ):
                raise ValueError("Highlight member differs from its recovered analysis")
    original = history._old(conn, receipt["original"], check)
    if (
        original["entity_type"] != "research_file"
        or original["action"] != "put"
        or original["workspace_id"] != context["workspace_id"]
        or original["payload"]["feature"] != "original_source"
        or original["parents"] != analysis["parents"]
        or original["payload"]["paper_id"] != root["payload"]["scope"]["id"]
        or original["payload"]["slot"] != root["payload"]["source_document_hash"]
    ):
        raise ValueError("Highlight group lost its native original receipt")
    return receipt


def _unused(conn, request, payloads):
    ids = [
        str(
            uuid5(
                NAMESPACE_URL,
                request
                + ":"
                + content_id(
                    p["scope"],
                    p["feature"],
                    p["key"],
                ),
            )
        )
        for p in payloads
    ]
    ids.append(str(uuid5(NAMESPACE_URL, "paperfact:highlight-original:" + request)))
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id IN ("
        + ",".join("?" for _ in ids)
        + ") LIMIT 1",
        ids,
    ).fetchone():
        raise ValueError("Native highlight writes exist without their decision receipt")


def _result(receipt, applied):
    return dict(
        receipt,
        choice="highlight_group",
        state="saved_locally",
        applied=applied,
        recovery_complete=False,
        remote_acceptance_checked=False,
        replayed=False,
        semantic_validation="not_performed",
    )


@dataclass(frozen=True)
class HighlightGroup:
    observed: object = field(repr=False)
    change_id: str
    request_id: str
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
                self.change_id,
                self.request_id,
                self.operation_json,
                self.comparison_json,
                self.replace,
            ),
        ):
            raise ValueError("Use the original prepared highlight group")
        root = _root(self.observed, self.change_id)
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, root, self.request_id, self.replace, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("Highlight recovery receipt disappeared; compare again")
        self.observed._check(check)
        proof, payloads = _located(self.observed, root, check)
        operations = backup._decode(self.operation_json)
        for expected, operation in zip(payloads, operations, strict=True):
            value = operation["payload"]
            if value["feature"] == "ai_highlight":
                expected["data"]["hidden"] = value["data"]["hidden"]
            if expected != value:
                raise ValueError("Verified highlight placement changed before recovery")
        with closing(_readonly_connection(self.observed.database)) as conn:
            conn.execute("BEGIN")
            native._binding_in(conn, self.observed)
            paths, client = _inspection_paths(conn), conn._capture_client
        if paths is None:
            raise ValueError("Highlight recovery needs registered original storage")
        staged = prepare_source(
            client,
            root["payload"]["scope"]["id"],
            proof[0],
            document_hash=root["payload"]["source_document_hash"],
            parent_incarnation=operations[0]["parents"][0]["incarnation"],
            store=BlobStore(paths[0].root),
            version_root=paths[1],
            request_id=str(uuid5(NAMESPACE_URL, "paperfact:highlight-original:" + self.request_id)),
        )
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
                _unused(conn, self.request_id, payloads)
                client = conn._capture_client
                original = publish_source_in(conn, client, staged)
                for operation in operations:
                    check()
                    client.journal.apply_in(conn, operation, client.writer)
                receipt = dict(
                    _context(self.observed, root, self.request_id, self.replace),
                    native=[
                        dict(id=o["operation_id"], fingerprint=candidates._fingerprint(o))
                        for o in operations
                    ],
                    original=original["operation_id"],
                )
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                native._original_current(proof)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(self.observed.database)) != self.observed.identity:
                    raise ValueError("Highlight destination was replaced")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, True)


def prepare(observed, change_id, request_id, *, replace=False, seconds=60, cancelled=lambda: False):
    """Prepare one complete analysis and exact marks; never touch manual/unrelated marks."""
    _identifier(request_id)
    if type(replace) is not bool:
        raise ValueError("Choose explicitly whether to replace existing highlights")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    root = _root(observed, change_id)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        prior = _prior(conn, observed, root, request_id, replace, check)
        if prior is not None:
            operations, comparison = [], []
        else:
            _proof, payloads = _located(observed, root, check)
            _unused(conn, request_id, payloads)
            mapper = choices._parent_mapper(conn, observed, root, check)
            parents = [mapper(parent) for parent in root["parents"]]
            client, operations, comparison = conn._capture_client, [], []
            with closing(_readonly_connection(observed.source.database)) as old:
                old.execute("BEGIN")
                for payload in payloads:
                    check()
                    identity, current, state, visible = _expected(conn, payload)
                    if state is not None and not replace:
                        raise ValueError("Review existing/deleted highlights before replacement")
                    if payload["feature"] == "ai_highlight":
                        old_value = _source_value(old, payload)
                        chosen = visible or old_value
                        if chosen:
                            payload["data"]["hidden"] = chosen["data"]["hidden"]
                    operation = client.new_graph_operation_in(
                        conn,
                        "research_content",
                        identity,
                        payload,
                        operation_id=str(uuid5(NAMESPACE_URL, request_id + ":" + identity)),
                        restore=bool(
                            state and (not state["active"] or state["parents"] != parents)
                        ),
                    )
                    if operation["parents"] != parents:
                        raise ValueError("Highlight paper differs from its proven parent mapping")
                    operations.append(operation)
                    comparison.append(
                        dict(
                            feature=payload["feature"],
                            source=payload["data"],
                            current=visible["data"] if visible else None,
                            state="absent"
                            if state is None
                            else "active"
                            if state["active"]
                            else "retired",
                        )
                    )
    observed._check(check)
    operation_json, comparison_json = candidates._json(operations), candidates._json(comparison)
    return HighlightGroup(
        observed,
        change_id,
        request_id,
        operation_json,
        comparison_json,
        replace,
        prior is not None,
        _sign(observed, change_id, request_id, operation_json, comparison_json, replace),
    )
