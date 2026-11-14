"""Typed recovery of claims, their exact two analysis inputs and owned original.

Old envelopes remain immutable. New native operations and one bounded receipt
share the destination transaction; copied bytes alone confer no ownership.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from paper_daily import claim_content, research_evidence
from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_note_copy as native
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_capture import CaptureConnection
from paper_daily.sync_content import FEATURES as CONTENT_FEATURES
from paper_daily.sync_content import content_id, content_payload
from paper_daily.sync_journal import MAX_BYTES, _identifier, canonical_operation
from paper_daily.sync_source_files import (
    FEATURE,
    _inspection_paths,
    prepare_source,
    publish_source_in,
)

FORMAT = "paperfact.recovery-claim-group.v1"
FEATURES = ("dive", "close_reading", "claims")
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, request, source_json, operation_json, comparison_json, replace):
    return hmac.new(_KEY, candidates._json([
        observed._seal, request, source_json, operation_json, comparison_json, replace,
    ]).encode(), "sha256").hexdigest()


def _head(conn, identity):
    cursor = conn.execute("SELECT sequence FROM paperfact_sync_cursor").fetchone()[0]
    row = conn.execute(
        "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,fingerprint "
        "FROM paperfact_sync_operations WHERE entity_type='research_content' AND entity_id=? "
        "AND (server_revision IS NULL OR server_revision>?) ORDER BY sequence DESC LIMIT 1",
        (MAX_BYTES, identity, cursor),
    ).fetchone()
    if row is not None:
        if row[0] is None:
            raise ValueError("Research input exceeds its byte budget")
        operation = backup._decode(row[0])
        if candidates._fingerprint(operation) != row[1]:
            raise ValueError("Research input journal fingerprint changed")
    else:
        row = conn.execute(
            "SELECT CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
            "FROM paperfact_sync_heads WHERE entity_type='research_content' AND entity_id=?",
            (MAX_BYTES, identity),
        ).fetchone()
        operation = backup._decode(row[0]) if row and row[0] is not None else None
    if operation is not None:
        canonical_operation(operation)
        binding = conn.execute("SELECT workspace FROM research_sync_binding WHERE id=1").fetchone()
        if (operation["entity_type"] != "research_content" or operation["entity_id"] != identity
                or binding is None or operation["workspace_id"] != binding[0]):
            raise ValueError("Research head belongs to another entity")
    return operation


def _visible(conn, payload):
    table = CONTENT_FEATURES[payload["feature"]][0]
    paper = conn.execute("SELECT local_id FROM research_paper_identity WHERE sync_id=?",
                         (payload["scope"]["id"],)).fetchone()
    if paper is None:
        raise ValueError("The research group's native paper mapping is unavailable")
    cursor = conn.execute("SELECT * FROM " + table + " WHERE paper_id=?", (paper[0],))
    row = cursor.fetchone()
    return content_payload(conn, table, dict(zip(
        (column[0] for column in cursor.description), row, strict=True,
    ))) if row is not None else None


def _old(conn, identity):
    row = conn.execute(
        "SELECT CASE WHEN length(CAST(envelope AS BLOB))<=? THEN envelope END,fingerprint "
        "FROM paperfact_sync_operations WHERE operation_id=?", (MAX_BYTES, identity),
    ).fetchone()
    if row:
        operation = backup._decode(row[0]) if row[0] else None
        if operation is None or candidates._fingerprint(operation) != row[1]:
            raise ValueError("Recorded source journal changed")
    else:
        row = conn.execute(
            "SELECT CASE WHEN length(CAST(event AS BLOB))<=? THEN event END "
            "FROM paperfact_sync_graph_receipts WHERE operation_id=?",
            (candidates.review.MAX_EVENT, identity),
        ).fetchone()
        operation = backup._decode(row[0])["operation"] if row and row[0] else None
    if operation is None:
        raise ValueError("The group's recorded source operation is unavailable")
    canonical_operation(operation)
    if operation["operation_id"] != identity:
        raise ValueError("Recorded source identity changed")
    return operation


def _inputs(observed, root, check, recorded=None):
    payload = root["payload"]
    if (root["version"] != 2 or root["entity_type"] != "research_content"
            or root["action"] != "put" or payload.get("feature") != "claims"):
        raise ValueError("Select a complete native claim set")
    body, paper, sha = payload["data"]["body_json"], payload["scope"]["id"], payload[
        "source_document_hash"]
    claim_content.validate(body)
    if (not sha or body["report"]["source"] != dict(paper_id=paper, document_hash=sha)
            or payload["data"]["source_hash"] != claim_content.source_digest(body["inputs"], sha)):
        raise ValueError("Claims require their portable exact original and input identities")
    result = []
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        for index, feature in enumerate(FEATURES):
            check()
            operation = _old(conn, recorded[index]["id"]) if recorded else (
                root if feature == "claims" else _head(
                    conn, content_id(dict(kind="paper", id=paper), feature, "main")))
            if (operation is None or operation["version"] != 2 or operation["action"] != "put"
                    or operation["entity_type"] != "research_content"
                    or operation["workspace_id"] != root["workspace_id"]
                    or operation["parents"] != root["parents"]
                    or operation["payload"]["feature"] != feature
                    or operation["payload"]["scope"] != payload["scope"]
                    or operation["payload"]["source_document_hash"] not in (None, sha)):
                raise ValueError("The claim group needs its exact native analysis inputs")
            if feature != "claims" and claim_content.input_digest(operation["payload"]["data"]) != (
                body["inputs"][feature]
            ):
                raise ValueError("Analysis inputs changed; do not mix claim generations")
            if feature == "claims" and operation != root:
                raise ValueError("The claim-group receipt names another source version")
            if recorded and candidates._fingerprint(operation) != recorded[index]["fingerprint"]:
                raise ValueError("The claim group's recorded source fingerprint changed")
            result.append(operation)
    observed.source._check(check)
    return result


def _proof(observed, root, check):
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        value = native.inspect_original(
            conn, root["payload"]["scope"]["id"], root["parents"][0],
            root["payload"]["source_document_hash"], check,
        )
    if value[0].stat().st_size > research_evidence.MAX_PDF_BYTES:
        raise ValueError("Claim original exceeds the evidence byte budget")
    with value[0].open("rb") as stream:
        data = stream.read(research_evidence.MAX_PDF_BYTES + 1)
    if len(data) > research_evidence.MAX_PDF_BYTES:
        raise ValueError("Claim original exceeded the evidence byte budget")
    native._original_current(value)
    pages, indexes, whole = research_evidence._extract(data, lambda: (check(), False)[1])
    report = root["payload"]["data"]["body_json"]["report"]
    if len(pages) != report["page_count"]:
        raise ValueError("Claim source page count changed")
    for claim in report["claims"]:
        for passage in claim["passages"]:
            check()
            location = passage["location"]
            if location["state"] == "located" and research_evidence._locate(
                dict(quote=passage["quote"], page=location["page"], anchor=location["anchor"]),
                pages, indexes, whole,
            ) != location:
                raise ValueError("A recorded claim passage no longer matches its original")
    native._original_current(value)
    observed.source._check(check)
    return value


def _context(observed, root, request, replace):
    return dict(format=FORMAT, request_id=request, replace=replace,
                source_fingerprint=candidates._fingerprint(root),
                workspace_id=observed.binding["workspace_id"],
                device_id=observed.binding["device_id"], database_identity=list(observed.identity))


def _prior(conn, observed, root, request, replace, check):
    choices._schema(conn)
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END "
        "FROM integration_operations WHERE id=?", (choices.MAX_RECEIPT, request),
    ).fetchone()
    if row is None:
        return None
    receipt = backup._decode(row[1]) if row[1] else None
    context = _context(observed, root, request, replace)
    if (not isinstance(receipt, dict)
            or set(receipt) != set(context) | {"sources", "native", "original"}
            or any(receipt.get(k) != v for k, v in context.items()) or _hash(receipt) != row[0]
            or not isinstance(receipt["sources"], list) or len(receipt["sources"]) != 3
            or not isinstance(receipt["native"], list) or len(receipt["native"]) != 3):
        raise ValueError("The claim-group request or saved receipt changed")
    for reference in receipt["sources"] + receipt["native"]:
        claim_content.closed(reference, {"id", "fingerprint"})
        _identifier(reference["id"])
        claim_content.digest(reference["fingerprint"])
    _identifier(receipt["original"])
    sources = _inputs(observed, root, check, receipt["sources"])
    parents = None
    for source, reference in zip(sources, receipt["native"], strict=True):
        operation = _old(conn, reference["id"])
        if (operation["entity_type"] != "research_content"
                or operation["workspace_id"] != context["workspace_id"]
                or operation["payload"] != source["payload"]
                or operation["entity_id"] != source["entity_id"]
                or candidates._fingerprint(operation) != reference["fingerprint"]
                or operation["action"] != "put"):
            raise ValueError("Saved claim group disagrees with its native research")
        if parents is not None and parents != operation["parents"]:
            raise ValueError("Saved claim group has inconsistent paper ownership")
        parents = operation["parents"]
    file = conn.execute(
        "SELECT CASE WHEN length(CAST(operation AS BLOB))<=? THEN operation END "
        "FROM research_file_versions WHERE operation_id=?", (MAX_BYTES, receipt["original"]),
    ).fetchone()
    original = backup._decode(file[0]) if file and file[0] else None
    if (original is None or original["workspace_id"] != context["workspace_id"]
            or original["parents"] != parents or original["payload"]["feature"] != FEATURE
            or original["payload"]["paper_id"] != root["payload"]["scope"]["id"]
            or original["payload"]["source_document_hash"] != root["payload"][
                "source_document_hash"]):
        raise ValueError("Saved claim group lost its native original receipt")
    canonical_operation(original)
    return receipt


def _unused_request(conn, request, sources):
    identities = [str(uuid5(NAMESPACE_URL, request + ":" + source["entity_id"]))
                  for source in sources]
    identities.append(str(uuid5(NAMESPACE_URL, "paperfact:claim-group-original:" + request)))
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id IN (?,?,?,?) LIMIT 1",
        identities,
    ).fetchone():
        raise ValueError("Native claim-group writes exist without their decision receipt")


def _result(receipt, applied):
    return dict(receipt, choice="claim_group", state="saved_locally", applied=applied,
                recovery_complete=False, remote_accepted=None, remote_acceptance_checked=False,
                semantic_validation="not_performed", replayed=False)


@dataclass(frozen=True)
class ClaimGroup:
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
        if not hmac.compare_digest(self._seal, _sign(
            self.observed, self.request_id, self.source_json, self.operation_json,
            self.comparison_json, self.replace,
        )):
            raise ValueError("Use the original prepared claim group")
        sources, operations = backup._decode(self.source_json), backup._decode(self.operation_json)
        root = sources[-1]
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, root, self.request_id, self.replace, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("The recorded claim-group decision disappeared; inspect it again")
        self.observed._check(check)
        proof = _proof(self.observed, root, check)
        with closing(_readonly_connection(self.observed.database)) as conn:
            conn.execute("BEGIN")
            native._binding_in(conn, self.observed)
            paths = _inspection_paths(conn)
            client = conn._capture_client
        if paths is None:
            raise ValueError("The claim group needs registered native original storage")
        self.observed._check(check)
        from paper_daily.sync_blobs import BlobStore

        staged = prepare_source(
            client, root["payload"]["scope"]["id"], proof[0],
            document_hash=root["payload"]["source_document_hash"],
            parent_incarnation=operations[0]["operation"]["parents"][0]["incarnation"],
            store=BlobStore(paths[0].root), version_root=paths[1],
            request_id=str(uuid5(
                NAMESPACE_URL, "paperfact:claim-group-original:" + self.request_id
            )),
        )
        native._original_current(proof)
        with closing(sqlite3.connect(self.observed.database.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.1, factory=CaptureConnection)) as conn:
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
                    conn, root["payload"]["scope"]["id"], operations[0]["operation"]["parents"][0],
                    root["payload"]["source_document_hash"], check,
                )
                receipt = dict(_context(self.observed, root, self.request_id, self.replace),
                    sources=[dict(id=o["operation_id"], fingerprint=candidates._fingerprint(o))
                             for o in sources],
                    native=[dict(id=i["operation"]["operation_id"],
                                 fingerprint=candidates._fingerprint(i["operation"]))
                            for i in operations], original=original["operation_id"])
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(
                    self.observed.database
                )) != self.observed.identity:
                    raise ValueError("Claim-group destination was replaced")
                native._original_current(current)
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, True)


def prepare(observed, change_id, request_id, *, replace=False, seconds=60, cancelled=lambda: False):
    """Prepare a complete claim group; differing/deleted members need explicit replace."""
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
            sources = _inputs(observed, root, check, prior["sources"])
            operations, comparisons = [], []
        else:
            sources = _inputs(observed, root, check)
            _unused_request(conn, request_id, sources)
            _proof(observed, root, check)
            mapped = choices._parent_mapper(conn, observed, root, check)
            parents = [mapped(parent) for parent in root["parents"]]
            client, operations, comparisons = conn._capture_client, [], []
            for source in sources:
                check()
                current = _head(conn, source["entity_id"])
                state = client._optimistic_graph(conn)[0].get(
                    ("research_content", source["entity_id"])
                )
                visible = _visible(conn, source["payload"])
                expected = current["payload"] if current and current["action"] == "put" and (
                    state and state["active"]
                ) else None
                if visible != expected:
                    raise ValueError(
                        "Visible research differs from native history; preserve it first"
                    )
                same = (current is not None and state and state["active"]
                        and current["action"] == "put"
                        and current["payload"] == source["payload"]
                        and current["parents"] == parents)
                if state is not None and not same and not replace:
                    raise ValueError("Review different or deleted group members before replacement")
                operation = current if same else client.new_graph_operation_in(
                    conn, "research_content", source["entity_id"], source["payload"],
                    operation_id=str(uuid5(NAMESPACE_URL, request_id + ":" + source["entity_id"])),
                    restore=bool(state and (not state["active"] or state["parents"] != parents)),
                )
                if operation["parents"] != parents:
                    raise ValueError("Claim-group paper differs from its proven parent mapping")
                operations.append(dict(operation=operation, write=not same))
                comparisons.append(dict(feature=source["payload"]["feature"],
                    source=source["payload"]["data"], current=visible["data"] if visible else None,
                    state="absent" if state is None else "active" if state["active"] else "retired",
                ))
    observed._check(check)
    values = [candidates._json(value) for value in (sources, operations, comparisons)]
    return ClaimGroup(observed, change_id, request_id, *values, replace, prior is not None,
                      _sign(observed, request_id, *values, replace))
