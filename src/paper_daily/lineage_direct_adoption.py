"""Explicit original-selection adoption of one unchanged private saved Lineage row."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL, uuid4, uuid5

from paper_daily import (
    lineage_matching_adoption,
    lineage_package_native,
    lineage_package_targets,
    lineage_packages,
    lineage_projection,
    lineage_sets,
    lineage_wire,
)
from paper_daily.lineage_jobs import _worker
from paper_daily.package_import import PackageImporter, _receipt
from paper_daily.sync_artifacts import activate, desired_file, materialize
from paper_daily.sync_content import content_id
from paper_daily.sync_files import file_id
from paper_daily.sync_source_files import prepare_source, publish_source_in
from paper_daily.workspace_service import Ticket, _safe_path

_KEY = secrets.token_bytes(32)


def _json(value):
    return lineage_packages._json(value)


@dataclass(frozen=True)
class PreparedAdoption:
    context: str = field(repr=False)
    validated: object = field(repr=False)
    sources: tuple = field(repr=False)
    seal: str = field(repr=False)

    def preview(self):
        value = json.loads(self.context)
        return dict(
            state="prepared",
            applied=False,
            row=value["row"],
            originals=len(self.sources),
            parents=value["parents"],
        )


class DirectAdoption:
    def __init__(self, database, data_root, *, current_path=None):
        self.receiver = PackageImporter(database, data_root, current_path=current_path)
        self._scope = secrets.token_hex(32)

    def _signature(self, context, validated, sources):
        return hmac.new(
            _KEY,
            _json(
                [context, self._scope, id(validated), [id(source) for source in sources]]
            ).encode(),
            "sha256",
        ).hexdigest()

    def _observe(self, conn, paper_id, corpus_key):
        receiver = self.receiver
        receiver._check(conn)
        row = lineage_package_native.saved_in(conn, paper_id, corpus_key)
        if row is None:
            raise ValueError("Select an existing saved Lineage report")
        payload = lineage_wire.encode_row(conn, row)
        identity = content_id(payload["scope"], "lineage", payload["key"])
        if not lineage_matching_adoption.eligible_in(conn, receiver.client, identity, payload, row):
            raise ValueError("Only unchanged private Lineage without native history can be adopted")
        parents = lineage_matching_adoption.parents_in(conn, receiver.client, payload)
        graph = receiver.client._optimistic_graph(conn)[0]
        files = []
        for selected in lineage_wire.required_originals(payload):
            key = file_id(selected["paper_id"], "original_source", selected["document_hash"])
            files.append(
                dict(
                    identity=key,
                    graph=graph.get(("research_file", key)),
                    desired=desired_file(conn, key),
                )
            )
        return dict(row=row, payload=payload, parents=parents, files=files)

    def inspect(self, paper_id, corpus_key, *, ticket=None):
        _worker()
        ticket = ticket or Ticket()
        receiver = self.receiver
        receiver._current_ticket(ticket)
        with receiver.client.journal.transaction() as conn:
            observed = self._observe(conn, paper_id, corpus_key)
            body = lineage_sets.decode(observed["row"]["body_json"])
            sources = []
            for binding, source in zip(body["bindings"], body["report"]["sources"], strict=True):
                title = conn.execute(
                    "SELECT title FROM papers WHERE id=?", (binding["paper_id"],)
                ).fetchone()
                if title is None:
                    raise ValueError("A selected source paper is missing")
                sources.append(
                    dict(
                        id=source["id"],
                        title=title[0],
                        paper_id=binding["paper_id"],
                        document_hash=source["document_hash"],
                        availability=source["availability"],
                    )
                )
        return dict(state="inspected", row=observed["row"], sources=sources)

    def prepare(self, paper_id, corpus_key, originals, *, ticket=None, request_id=None):
        _worker()
        ticket = ticket or Ticket()
        receiver = self.receiver
        receiver._current_ticket(ticket)
        if request_id is not None:
            lineage_sets.uuid(request_id)
        request = str(
            uuid5(NAMESPACE_URL, "paperfact-direct-lineage:" + str(request_id or uuid4()))
        )
        with receiver.client.journal.transaction() as conn:
            observed = self._observe(conn, paper_id, corpus_key)
            identities = {
                binding["paper_id"]: conn.execute(
                    "SELECT sync_id FROM research_paper_identity WHERE local_id=?",
                    (binding["paper_id"],),
                ).fetchone()[0]
                for binding in lineage_sets.decode(observed["row"]["body_json"])["bindings"]
            }
        body = lineage_sets.decode(observed["row"]["body_json"])
        needed = [s for s in body["report"]["sources"] if s["availability"] == "available"]
        if not isinstance(originals, dict) or set(originals) != {s["id"] for s in needed}:
            raise ValueError("Choose an exact PDF for every available saved source")
        captured, selected_paths, total = {}, {}, 0
        for source in needed:
            receiver._current_ticket(ticket)
            path = _safe_path(originals[source["id"]])
            size = path.stat().st_size
            if not path.is_file() or not 0 < size <= lineage_packages.MAX_PDF_BYTES:
                raise ValueError("Selected original exceeds its PDF byte budget")
            with path.open("rb") as stream:
                data = stream.read(size + 1)
            total += len(data)
            if len(data) != size or total > lineage_packages.MAX_TOTAL:
                raise ValueError("Selected originals changed or exceed their byte budget")
            captured[source["id"]] = data
            selected_paths[source["id"]] = path
        try:
            validated = lineage_package_targets.validate_selected(
                observed["row"], captured, cancelled=lambda: ticket.cancelled
            )
        except ValueError:
            ticket.check()
            raise
        payload = lineage_package_native.payloads(validated, identities)[0]
        if payload != observed["payload"]:
            raise ValueError("Selected source identities changed")
        staged = []
        for selected in lineage_wire.required_originals(payload):
            receiver._current_ticket(ticket)
            parent = next(p for p in observed["parents"] if p["id"] == selected["paper_id"])
            source_request = str(uuid5(NAMESPACE_URL, request + ":" + selected["source_id"]))
            staged.append(
                prepare_source(
                    receiver.client,
                    selected["paper_id"],
                    selected_paths[selected["source_id"]],
                    document_hash=selected["document_hash"],
                    parent_incarnation=parent["incarnation"],
                    store=receiver.store,
                    version_root=receiver.version_root,
                    request_id=source_request,
                )
            )
        receiver._current_ticket(ticket)
        with receiver.client.journal.transaction() as conn:
            if self._observe(conn, paper_id, corpus_key) != observed:
                raise ValueError("Saved Lineage or source lifetimes changed during preparation")
        context = _json(
            dict(
                observed,
                request=request,
                identities=identities,
                database=str(receiver.database),
                native=receiver.identity,
                binding=receiver.binding,
            )
        )
        staged = tuple(staged)
        return PreparedAdoption(
            context, validated, staged, self._signature(context, validated, staged)
        )

    def apply(self, prepared, *, ticket=None):
        _worker()
        if not isinstance(prepared, PreparedAdoption) or not hmac.compare_digest(
            prepared.seal, self._signature(prepared.context, prepared.validated, prepared.sources)
        ):
            raise ValueError("Direct adoption requires this service's unchanged reviewed plan")
        ticket = ticket or Ticket()
        receiver = self.receiver
        receiver._current_ticket(ticket)
        data = json.loads(prepared.context)
        if (
            data["database"] != str(receiver.database)
            or data["native"] != list(receiver.identity)
            or _json(data["binding"]) != _json(receiver.binding)
        ):
            raise ValueError("Adoption belongs to another workspace")
        fingerprint = hashlib.sha256(prepared.context.encode()).hexdigest()
        transaction = receiver.client.journal.transaction()
        conn, ended = transaction.__enter__(), False
        try:
            receiver._check(conn)
            prior = _receipt(conn, data["request"])
            if prior:
                if prior[0] != fingerprint:
                    raise ValueError("Adoption request identity was reused")
                report = dict(
                    prior[1],
                    state="previously_applied",
                    replayed=True,
                    availability_rechecked=False,
                )
            else:
                row = data["row"]
                current = self._observe(conn, row["paper_id"], row["corpus_key"])
                if current != {key: data[key] for key in ("row", "payload", "parents", "files")}:
                    raise ValueError("Saved Lineage changed; review its originals again")
                lineage_projection.initialize_in(conn)
                originals, artifacts = {}, []
                for source in prepared.sources:
                    receiver._current_ticket(ticket)
                    operation = publish_source_in(conn, receiver.client, source)
                    originals[operation["entity_id"]] = operation
                    artifacts.append(
                        (operation, materialize(receiver.store, receiver.version_root, operation))
                    )
                operation = lineage_package_native.build_in(
                    conn,
                    receiver.client,
                    prepared.validated,
                    data["identities"],
                    data["payload"],
                    data["request"],
                    originals,
                )
                lineage_matching_adoption.consume_in(conn, receiver.client, operation, row)
                receiver.client.journal.apply_in(conn, operation, receiver.client.writer)
                for original, directory in artifacts:
                    if not activate(conn, original, directory):
                        raise ValueError("Selected original changed before activation")
                report = dict(
                    state="adopted_locally",
                    lineage_adopted=1,
                    originals=len(originals),
                    replayed=False,
                    request_id=data["request"],
                    paper_id=row["paper_id"],
                    corpus_key=row["corpus_key"],
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS package_import_receipts("
                    "request_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,"
                    "result_json TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO package_import_receipts VALUES(?,?,?)",
                    (data["request"], fingerprint, _json(report)),
                )
            receiver._current_ticket(ticket)
            receiver._check(conn)

            def commit():
                nonlocal ended
                ended = True
                transaction.__exit__(None, None, None)

            ticket.publish(commit)
            return report
        except BaseException as error:
            if not ended:
                transaction.__exit__(type(error), error, error.__traceback__)
            raise


def can_offer_in(conn, row):
    """Cheap read-only UI hint, never a source/adoption grant or eligibility proof."""
    import sqlite3

    try:

        def exists(table):
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()

        if not exists("research_capture_binding") or not exists("research_paper_identity"):
            return False
        mapped = conn.execute(
            "SELECT sync_id FROM research_paper_identity WHERE local_id=?", (row["paper_id"],)
        ).fetchone()
        if mapped is None:
            return False
        identity = content_id(dict(kind="paper", id=mapped[0]), "lineage", row["corpus_key"])
        for table in ("paperfact_sync_operations", "paperfact_sync_heads", "paperfact_sync_graph"):
            if (
                exists(table)
                and conn.execute(
                    f"SELECT 1 FROM {table} WHERE entity_type='research_content' "
                    "AND entity_id=? LIMIT 1",
                    (identity,),
                ).fetchone()
            ):
                return False
        for table in (lineage_projection.TABLE, lineage_projection.HISTORY):
            if (
                exists(table)
                and conn.execute(
                    f"SELECT 1 FROM {table} WHERE entity_id=? LIMIT 1", (identity,)
                ).fetchone()
            ):
                return False
        return True
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        return False
