"""Confirmed native Lineage recovery with fresh exact-original dependencies.

Old operation data is evidence, never replay authority. Every available original
and the scientific row share one caller-owned native transaction and receipt.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid5

from paper_daily import lineage_dependencies, lineage_projection, lineage_sets, lineage_wire
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_note_copy as native
from paper_daily import sync_recovery_original as original_choice
from paper_daily import sync_recovery_reading_group as references
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, suppress_capture
from paper_daily.sync_content import _local_scope
from paper_daily.sync_journal import _identifier
from paper_daily.sync_source_files import (
    FEATURE,
    _inspection_paths,
    prepare_source,
    publish_source_in,
)

FORMAT = "paperfact.recovery-lineage-group.v1"
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, request, metadata, comparison, replace):
    return hmac.new(
        _KEY,
        candidates._json(
            [
                observed._seal,
                request,
                metadata,
                comparison,
                replace,
            ]
        ).encode(),
        "sha256",
    ).hexdigest()


def _request(request, source_id):
    return str(uuid5(NAMESPACE_URL, "paperfact:lineage-recovery:" + request + ":" + source_id))


def review_request(observed, operation):
    """Stable UI retry per target input lifetime, not a perpetual source decision."""
    check = backup._guard(60, lambda: False)
    native._auth(observed, check)
    lineage_dependencies.canonical_operation(operation)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        graph = conn._capture_client._optimistic_graph(conn)[0]
        keys = [("paper", p["id"]) for p in operation["parents"]]
        keys.extend(("research_file", p["file_id"]) for p in operation["source_dependencies"])
        inputs = [
            [
                kind,
                key,
                {k: state[k] for k in ("incarnation", "active", "parents")} if state else None,
            ]
            for kind, key in keys
            for state in [graph.get((kind, key))]
        ]
    observed._check(check)
    return str(
        uuid5(
            NAMESPACE_URL,
            "paperfact:lineage-group-ui:"
            + candidates._json(
                [
                    observed.binding,
                    operation["operation_id"],
                    candidates._fingerprint(operation),
                    inputs,
                ]
            ),
        )
    )


def _root(observed, change, cancelled):
    operation = observed.source.details(change, cancelled=cancelled)["operation"]
    lineage_dependencies.canonical_operation(operation)
    if operation["action"] != "put":
        raise ValueError("Select a complete native Lineage put")
    return operation


def _original(operation, root, pin, parent):
    lineage_dependencies.validate(root)
    if (
        operation["version"] != 2
        or operation["action"] != "put"
        or operation["entity_type"] != "research_file"
        or operation["workspace_id"] != root["workspace_id"]
        or operation["entity_id"] != pin["file_id"]
        or operation["incarnation"] != pin["incarnation"]
        or operation["parents"] != [parent]
        or operation["payload"]["feature"] != FEATURE
        or operation["payload"]["paper_id"] != pin["paper_id"]
    ):
        raise ValueError("Lineage original differs from its exact recorded dependency")


def _sources(observed, root, check):
    report = root["payload"]["data"]["body_json"]["report"]
    by_id = {source["id"]: source for source in report["sources"]}
    parents = {parent["id"]: parent for parent in root["parents"]}
    metadata, proofs = [], []
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        for pin in root["source_dependencies"]:
            check()
            source, parent = by_id[pin["source_id"]], parents[pin["paper_id"]]
            original = original_choice.retained_original(
                conn,
                dict(
                    workspace_id=root["workspace_id"],
                    entity_id=pin["file_id"],
                    incarnation=pin["incarnation"],
                    parents=[parent],
                ),
                check,
            )
            _original(original, root, pin, parent)
            proof = original_choice._proof(observed, dict(original=original), check)
            if proof[0].stat().st_size > evidence.MAX_PDF_BYTES:
                raise ValueError("Lineage original exceeds its evidence byte budget")
            with proof[0].open("rb") as stream:
                data = stream.read(evidence.MAX_PDF_BYTES + 1)
            if len(data) > evidence.MAX_PDF_BYTES:
                raise ValueError("Lineage original exceeds its evidence byte budget")
            pages, indexes, whole = evidence._extract(data, lambda: (check(), False)[1])
            if len(pages) != source["page_count"]:
                raise ValueError("Lineage original page count changed")
            for statement in report["statements"]:
                for passage in statement["passages"]:
                    check()
                    if (
                        passage["source_id"] == pin["source_id"]
                        and passage["location"]["state"] == "located"
                    ):
                        location = passage["location"]
                        if (
                            evidence._locate(
                                dict(
                                    quote=passage["quote"],
                                    page=location["page"],
                                    anchor=location["anchor"],
                                ),
                                pages,
                                indexes,
                                whole,
                            )
                            != location
                        ):
                            raise ValueError(
                                "A Lineage passage no longer matches its exact original"
                            )
            title = conn.execute(
                "SELECT p.title FROM papers p JOIN research_paper_identity i ON p.id=i.local_id "
                "WHERE i.sync_id=?",
                (pin["paper_id"],),
            ).fetchone()
            metadata.append(
                dict(
                    source_id=pin["source_id"],
                    paper_id=pin["paper_id"],
                    sha256=source["document_hash"],
                    parent=parent,
                    title=title[0] if title else pin["paper_id"],
                    original=references._reference(original),
                )
            )
            native._original_current(proof)
            proofs.append(proof)
    observed.source._check(check)
    return metadata, proofs


def _visible(conn, root):
    local = _local_scope(conn, root["payload"]["scope"], required=True)
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (lineage_sets.TABLE,)
    ).fetchone():
        return None
    return lineage_projection._current(conn, local, root["payload"]["key"])


def _checked_visible(conn, client, root, current):
    """Accept native hiding, never an uncaptured row deletion or forged marker."""
    visible = _visible(conn, root)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (lineage_projection.TABLE,),
    ).fetchone()
    marker, marked = lineage_projection._marker(conn, root["entity_id"]) if exists else (None, None)
    if current is None:
        if visible is not None or marker is not None:
            raise ValueError("Visible Lineage differs from native history; preserve it first")
        return None
    if marker is None or marked != current or bool(marker["active"]) != (visible is not None):
        raise ValueError("Visible Lineage differs from native history; preserve it first")
    local = _local_scope(conn, root["payload"]["scope"], required=True)
    if marker["paper_id"] != local or marker["corpus_key"] != root["payload"]["key"]:
        raise ValueError("Lineage projection owners differ from native history")
    if visible is not None:
        from paper_daily.claim_content import hashed

        if (
            current["action"] != "put"
            or visible != lineage_wire.decode_row(conn, current["payload"])
            or hashed(visible) != marker["fingerprint"]
        ):
            raise ValueError("Visible Lineage differs from native history; preserve it first")
    elif current["action"] == "put":
        reason = lineage_dependencies.projection_reason_in(conn, client, current)
        if reason not in {
            "parent_missing",
            "parent_deleted",
            "parent_incarnation",
            "source_missing",
            "source_deleted",
            "source_incarnation",
        }:
            raise ValueError(
                "Hidden Lineage has no native retired-input evidence; preserve it first"
            )
    return visible


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
        or set(receipt) != set(context) | {"native", "originals"}
        or any(receipt.get(k) != v for k, v in context.items())
        or _hash(receipt) != row[0]
        or not isinstance(receipt["originals"], list)
        or len(receipt["originals"]) != len(root["source_dependencies"])
    ):
        raise ValueError("The Lineage-group request or saved receipt changed")
    scientific = references._retained(conn, receipt["native"], check)
    lineage_dependencies.canonical_operation(scientific)
    if (
        scientific["action"] != "put"
        or scientific["payload"] != root["payload"]
        or scientific["entity_id"] != root["entity_id"]
        or scientific["workspace_id"] != context["workspace_id"]
    ):
        raise ValueError("Saved Lineage differs from its exact native report")
    with closing(_readonly_connection(observed.source.database)) as old:
        old.execute("BEGIN")
        for old_pin, pin, item in zip(
            root["source_dependencies"],
            scientific["source_dependencies"],
            receipt["originals"],
            strict=True,
        ):
            if not isinstance(item, dict) or set(item) != {"source", "native"}:
                raise ValueError("Invalid Lineage original receipt")
            source = references._retained(old, item["source"], check)
            original = references._retained(conn, item["native"], check)
            _original(
                source,
                root,
                old_pin,
                next(p for p in root["parents"] if p["id"] == old_pin["paper_id"]),
            )
            _original(
                original,
                scientific,
                pin,
                next(p for p in scientific["parents"] if p["id"] == pin["paper_id"]),
            )
            if (
                source["payload"]["assets"] != original["payload"]["assets"]
                or source["payload"]["source_document_hash"]
                != original["payload"]["source_document_hash"]
            ):
                raise ValueError("Saved Lineage original bytes differ from the selected source")
    return receipt


def _unused(conn, request, root):
    ids = [
        _request(request, "report"),
        *[_request(request, pin["source_id"]) for pin in root["source_dependencies"]],
    ]
    if conn.execute(
        "SELECT 1 FROM paperfact_sync_operations WHERE operation_id IN ("
        + ",".join("?" for _ in ids)
        + ") LIMIT 1",
        ids,
    ).fetchone():
        raise ValueError("Native Lineage-group writes exist without their decision receipt")


def _result(receipt, applied):
    return dict(
        receipt,
        choice="lineage_group",
        state="saved_locally",
        applied=applied,
        recovery_complete=False,
        remote_acceptance_checked=False,
        replayed=False,
        semantic_validation="not_performed",
    )


@dataclass(frozen=True)
class LineageGroup:
    observed: object = field(repr=False)
    change_id: str
    request_id: str
    metadata_json: str = field(repr=False)
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
                self.metadata_json,
                self.comparison_json,
                self.replace,
            ),
        ):
            raise ValueError("Use the original prepared Lineage group")
        metadata = backup._decode(self.metadata_json)
        root = metadata["root"]
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, root, self.request_id, self.replace, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("The saved Lineage decision disappeared; compare again")
        self.observed._check(check)
        originals, proofs = _sources(self.observed, root, check)
        if originals != metadata["originals"]:
            raise ValueError("Lineage source ownership changed after comparison")
        with closing(_readonly_connection(self.observed.database)) as conn:
            conn.execute("BEGIN")
            native._binding_in(conn, self.observed)
            paths, client = _inspection_paths(conn), conn._capture_client
        if paths is None:
            raise ValueError("Lineage recovery needs registered native original storage")
        parents = {p["id"]: p for p in metadata["parents"]}
        staged = []
        for item, proof in zip(originals, proofs, strict=True):
            check()
            staged.append(
                prepare_source(
                    client,
                    item["paper_id"],
                    proof[0],
                    document_hash=item["sha256"],
                    parent_incarnation=parents[item["paper_id"]]["incarnation"],
                    store=BlobStore(paths[0].root),
                    version_root=paths[1],
                    request_id=_request(self.request_id, item["source_id"]),
                )
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
                _unused(conn, self.request_id, root)
                client, files = conn._capture_client, []
                for item in staged:
                    check()
                    files.append(publish_source_in(conn, client, item))
                template = deepcopy(root)
                template.update(
                    workspace_id=self.observed.binding["workspace_id"],
                    device_id=self.observed.binding["device_id"],
                    parents=metadata["parents"],
                    source_dependencies=[
                        dict(
                            source_id=source["source_id"],
                            paper_id=source["paper_id"],
                            file_id=op["entity_id"],
                            incarnation=op["incarnation"],
                        )
                        for source, op in zip(originals, files, strict=True)
                    ],
                )
                state = client._optimistic_graph(conn)[0].get(
                    ("research_content", root["entity_id"])
                )
                current = history._head(conn, root["entity_id"])
                same = (
                    current
                    and current["action"] == "put"
                    and state
                    and state["active"]
                    and all(
                        current[k] == template[k]
                        for k in ("payload", "parents", "source_dependencies")
                    )
                )
                operation = (
                    current
                    if same
                    else client._new_graph_operation(
                        conn,
                        "research_content",
                        root["entity_id"],
                        root["payload"],
                        operation_id=_request(self.request_id, "report"),
                        restore=bool(
                            state
                            and (not state["active"] or state["parents"] != metadata["parents"])
                        ),
                        lineage_template=template,
                    )
                )
                if operation["parents"] != metadata["parents"]:
                    raise ValueError("Lineage paper owners changed after comparison")
                if not same:
                    with suppress_capture(conn):
                        lineage_projection.initialize_receive_in(conn, client, operation)
                    client.journal.apply_in(conn, operation, client.writer)
                receipt = dict(
                    _context(self.observed, root, self.request_id, self.replace),
                    native=references._reference(operation),
                    originals=[
                        dict(source=item["original"], native=references._reference(op))
                        for item, op in zip(originals, files, strict=True)
                    ],
                )
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                for proof in proofs:
                    native._original_current(proof)
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(self.observed.database)) != self.observed.identity:
                    raise ValueError("Lineage destination was replaced")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, True)


def prepare(observed, change_id, request_id, *, replace=False, seconds=60, cancelled=lambda: False):
    """Prepare the complete native report and all available exact source originals."""
    _identifier(request_id)
    if type(replace) is not bool:
        raise ValueError("Choose explicitly whether to replace the Lineage report")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    root = _root(observed, change_id, cancelled)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        prior = _prior(conn, observed, root, request_id, replace, check)
        metadata = dict(root=root)
        comparison = []
        if prior is None:
            _unused(conn, request_id, root)
            originals, _proofs = _sources(observed, root, check)
            mapper = choices._parent_mapper(conn, observed, root, check)
            parents = [mapper(parent) for parent in root["parents"]]
            current = history._head(conn, root["entity_id"])
            state = conn._capture_client._optimistic_graph(conn)[0].get(
                ("research_content", root["entity_id"])
            )
            visible = _checked_visible(conn, conn._capture_client, root, current)
            graph = conn._capture_client._optimistic_graph(conn)[0]
            same = (
                current
                and current["action"] == "put"
                and state
                and state["active"]
                and visible is not None
                and lineage_dependencies.active(lambda kind, key: graph.get((kind, key)), current)
                and current["payload"] == root["payload"]
                and current["parents"] == parents
            )
            if state is not None and not same and not replace:
                raise ValueError("Review different or retired Lineage before replacement")
            metadata.update(originals=originals, parents=parents)
            comparison = [
                dict(
                    feature="lineage",
                    source=root["payload"]["data"],
                    current=current["payload"]["data"]
                    if current and current["action"] == "put"
                    else None,
                    originals=[
                        dict(source_id=i["source_id"], title=i["title"], sha256=i["sha256"])
                        for i in originals
                    ],
                )
            ]
    observed._check(check)
    encoded, compared = candidates._json(metadata), candidates._json(comparison)
    return LineageGroup(
        observed,
        change_id,
        request_id,
        encoded,
        compared,
        replace,
        prior is not None,
        _sign(observed, request_id, encoded, compared, replace),
    )
