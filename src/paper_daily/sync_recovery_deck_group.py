"""Explicit whole-deck recovery with exact assets and owned originals.

A fresh native operation is published, never a replay of the old envelope.
Preparation is read-only; immutable staging precedes one research transaction.
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

from paper_daily import research_generation as generation
from paper_daily import sync_artifacts as artifacts
from paper_daily import sync_authority_backup as backup
from paper_daily import sync_recovery_candidates as candidates
from paper_daily import sync_recovery_choices as choices
from paper_daily import sync_recovery_claim_group as history
from paper_daily import sync_recovery_note_copy as native
from paper_daily.manual_highlight_ops import _readonly_connection
from paper_daily.sync_blobs import BlobStore
from paper_daily.sync_capture import CaptureConnection, suppress_capture
from paper_daily.sync_files import scope_input_versions
from paper_daily.sync_journal import _identifier, canonical_operation
from paper_daily.sync_source_files import _inspection_paths, prepare_source, publish_source_in

FORMAT = "paperfact.recovery-deck-group.v1"
_KEY = secrets.token_bytes(32)


def _hash(value):
    return hashlib.sha256(candidates._json(value).encode()).hexdigest()


def _sign(observed, change, request, operation, comparison, replace):
    return hmac.new(_KEY, candidates._json([
        observed._seal, change, request, operation, comparison, replace,
    ]).encode(), "sha256").hexdigest()


def _context(observed, source, request, replace):
    return dict(format=FORMAT, request_id=request, replace=replace,
                source_fingerprint=candidates._fingerprint(source),
                workspace_id=observed.binding["workspace_id"],
                device_id=observed.binding["device_id"], database_identity=list(observed.identity))


def _payload(source):
    canonical_operation(source)
    if (source["version"] != 2 or source["entity_type"] != "research_file"
            or source["action"] != "put" or source["payload"]["feature"] != "deck"):
        raise ValueError("Select a recorded editable deck put")
    payload = deepcopy(source["payload"])
    payload["input_versions"] = scope_input_versions(
        payload["input_versions"], source["workspace_id"],
    )
    return payload


def _recorded_owner(conn, source, reference, check):
    operation = history._old(conn, reference["operation_id"], check)
    parent = dict(kind="paper", id=reference["paper_id"],
                  incarnation=reference["parent_incarnation"])
    if (operation["version"] != 2 or operation["action"] != "put"
            or operation["workspace_id"] != source["workspace_id"]
            or operation["entity_type"] != "paper_document"
            or operation["entity_id"] != reference["paper_id"]
            or operation["incarnation"] != reference["incarnation"]
            or operation["parents"] != [parent]
            or operation["payload"]["sha256"] != reference["sha256"]):
        raise ValueError("Recorded deck document differs from its retained native operation")
    return parent


def _originals(conn, source, hashes, check):
    payload = source["payload"]
    refs = payload["input_versions"]["documents"]
    if refs and payload["input_versions"].get(
        "workspace_id", source["workspace_id"],
    ) != source["workspace_id"]:
        raise ValueError("Foreign-scope original owners need explicit workspace mapping")
    owners = {}
    for reference in refs:
        parent = _recorded_owner(conn, source, reference, check)
        owners.setdefault(reference["sha256"], []).append(parent)
    if any(len(value) > 1 for value in owners.values()) or (
        payload["source_document_hash"] in owners
        and owners[payload["source_document_hash"]] != [source["parents"][0]]
    ):
        raise ValueError("A deck original has ambiguous recorded paper owners")
    result = {}
    for sha in sorted(hashes):
        matches = owners.get(sha, [])
        parent = matches[0] if matches else source["parents"][0]
        title = conn.execute(
            "SELECT p.title FROM papers p JOIN research_paper_identity i ON i.local_id=p.id "
            "WHERE i.sync_id=?", (parent["id"],),
        ).fetchone()
        result[sha] = dict(parent=parent, title=title[0] if title else parent["id"],
                           proof=native.inspect_original(conn, parent["id"], parent, sha, check,
                                                         allow_retained=True))
    return result


def _mapped_originals(mapper, originals):
    result = []
    for sha, value in originals.items():
        try:
            translated = mapper(value["parent"])
        except ValueError as error:
            raise ValueError(
                "Review this paper's recorded change first: " + value["title"] + ". " + str(error)
            ) from error
        result.append(dict(sha256=sha, title=value["title"], source_parent=value["parent"],
                           target_parent=translated))
    return result


def _closure(observed, source, check):
    with closing(_readonly_connection(observed.source.database)) as conn:
        conn.execute("BEGIN")
        paths = _inspection_paths(conn)
        if paths is None:
            raise ValueError("The old deck has no registered artifact storage")
        closure, body, blobs = artifacts.verify_closure(paths[0], source)
        payload = source["payload"]
        hashes = {payload["source_document_hash"]} - {None}
        for row in body["deck"]["sources"] + body["deck"]["figures"]:
            if row.get("document_hash"):
                hashes.add(row["document_hash"])
        evidence_id = body["evidence_asset"]
        if evidence_id:
            from paper_daily.sync_files import read_json

            entry = next(a for a in payload["assets"] if a["id"] == evidence_id)
            evidence = read_json(blobs[entry["sha256"]])
            hashes.update(r["document_hash"] for r in evidence["sources"]
                          if r.get("document_hash"))
        refs = payload["input_versions"]["documents"]
        hashes.update(row["sha256"] for row in refs)
        if len(hashes) > 16:
            raise ValueError("Deck originals exceed the recovery budget")
        originals = _originals(conn, source, hashes, check)
    check()
    observed.source._check(check)
    if not closure.matches(source):
        raise ValueError("Old deck assets changed during review")
    return closure, body, blobs, originals


def _prior(conn, observed, source, request, replace, check):
    choices._schema(conn)
    row = conn.execute(
        "SELECT fingerprint,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END "
        "FROM integration_operations WHERE id=?", (choices.MAX_RECEIPT, request),
    ).fetchone()
    if row is None:
        return None
    receipt = backup._decode(row[1]) if row[1] else None
    context = _context(observed, source, request, replace)
    if (not isinstance(receipt, dict) or set(receipt) != set(context) | {"native", "originals"}
            or any(receipt.get(k) != v for k, v in context.items())
            or _hash(receipt) != row[0] or not isinstance(receipt["native"], dict)
            or set(receipt["native"]) != {"id", "fingerprint"}
            or not isinstance(receipt["originals"], list) or len(receipt["originals"]) > 16):
        raise ValueError("Saved deck recovery receipt or request changed")
    operation = history._old(conn, receipt["native"]["id"], check)
    if (candidates._fingerprint(operation) != receipt["native"]["fingerprint"]
            or operation["workspace_id"] != context["workspace_id"]
            or operation["entity_type"] != "research_file" or operation["action"] != "put"
            or operation["entity_id"] != source["entity_id"]
            or operation["payload"] != _payload(source)):
        raise ValueError("Deck recovery receipt differs from native history")
    seen = set()
    for reference in receipt["originals"]:
        if not isinstance(reference, dict) or set(reference) not in (
            {"id", "fingerprint"}, {"id", "fingerprint", "source_parent", "target_parent"},
        ):
            raise ValueError("Invalid original recovery receipt")
        source_parent = reference.get("source_parent", source["parents"][0])
        target_parent = reference.get("target_parent", operation["parents"][0])
        for parent in (source_parent, target_parent):
            if (not isinstance(parent, dict) or set(parent) != {"kind", "id", "incarnation"}
                    or parent["kind"] != "paper"):
                raise ValueError("Invalid original owner recovery receipt")
            for value in parent.values():
                _identifier(value)
        original = history._old(conn, reference["id"], check)
        if (original["entity_type"] != "research_file" or original["action"] != "put"
                or original["payload"].get("feature") != "original_source"):
            raise ValueError("Deck original receipt names another native content type")
        sha = original["payload"]["slot"]
        permitted = source_parent == source["parents"][0] or any(
            row["paper_id"] == source_parent["id"]
            and row["parent_incarnation"] == source_parent["incarnation"] and row["sha256"] == sha
            for row in source["payload"]["input_versions"]["documents"]
        )
        if (not permitted or candidates._fingerprint(original) != reference["fingerprint"]
                or original["workspace_id"] != operation["workspace_id"]
                or original["entity_type"] != "research_file" or original["action"] != "put"
                or original["payload"]["feature"] != "original_source"
                or original["payload"]["paper_id"] != source_parent["id"]
                or target_parent["id"] != source_parent["id"]
                or original["parents"] != [target_parent] or sha in seen):
            raise ValueError("Deck original receipt differs from native history")
        if source_parent == source["parents"][0] and target_parent != operation["parents"][0]:
            raise ValueError("Deck root original differs from its native parent mapping")
        seen.add(sha)
    return receipt


def _unused(conn, request):
    if conn.execute("SELECT 1 FROM paperfact_sync_operations WHERE operation_id=?",
                    (request,)).fetchone():
        raise ValueError("Native deck write exists without its recovery receipt")


def _legacy_guard(conn, observed, payload):
    paper = conn.execute("SELECT local_id FROM research_paper_identity WHERE sync_id=?",
                         (payload["paper_id"],)).fetchone()
    if paper is None:
        raise ValueError("The deck's native paper mapping is unavailable")
    folder = hashlib.sha256(paper[0].encode()).hexdigest()[:24]
    legacy = (observed.database.parent / "presentations" / folder
              / (payload["slot"] + ".json"))
    if legacy.exists() or legacy.is_symlink():
        raise ValueError("Preserve the legacy private deck before managed recovery")


def _result(receipt, applied):
    return dict(receipt, choice="deck_group", applied=applied, state="saved_locally",
                replayed=False, recovery_complete=False, remote_acceptance_checked=False,
                semantic_validation="not_performed")


@dataclass(frozen=True)
class DeckGroup:
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
        if not hmac.compare_digest(self._seal, _sign(
            self.observed, self.change_id, self.request_id, self.operation_json,
            self.comparison_json, self.replace,
        )):
            raise ValueError("Use the original prepared deck comparison")
        source = self.observed.source.details(self.change_id)["operation"]
        with closing(_readonly_connection(self.observed.database)) as conn:
            prior = _prior(conn, self.observed, source, self.request_id, self.replace, check)
        if prior is not None:
            return _result(prior, False)
        if self.already:
            raise ValueError("Saved deck decision disappeared; review again")
        self.observed._check(check)
        closure, _body, blobs, originals = _closure(self.observed, source, check)
        operation = backup._decode(self.operation_json)
        with closing(_readonly_connection(self.observed.database)) as conn:
            conn.execute("BEGIN")
            native._binding_in(conn, self.observed)
            paths, client = _inspection_paths(conn), conn._capture_client
            current = artifacts.applied_file(conn, source["entity_id"])
            mapper = choices._parent_mapper(conn, self.observed, source, check)
            owners = _mapped_originals(mapper, originals)
            if owners != self.comparison["original_owners"]:
                raise ValueError("Deck original owner mapping changed after comparison")
        if paths is None:
            raise ValueError("The restored workspace needs registered artifact storage")
        store, root = BlobStore(paths[0].root), paths[1]
        # Detect modified existing managed files rather than hiding private edits.
        current_version = artifacts.materialize(store, root, current) if current else None
        staged = [prepare_source(
            client, owner["source_parent"]["id"], originals[owner["sha256"]]["proof"][0],
            document_hash=owner["sha256"],
            parent_incarnation=owner["target_parent"]["incarnation"], store=store,
            version_root=root,
            request_id=str(uuid5(
                NAMESPACE_URL, "paperfact:deck-original:" + self.request_id + owner["sha256"],
            )),
        ) for owner in owners]
        artifacts.stage_bytes(store, blobs)
        directory = artifacts.materialize(store, root, operation)
        check()
        with closing(sqlite3.connect(self.observed.database.as_uri() + "?mode=rw", uri=True,
                                     timeout=0.1, factory=CaptureConnection)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                native._binding_in(conn, self.observed)
                prior = _prior(conn, self.observed, source, self.request_id, self.replace, check)
                if prior is not None:
                    return _result(prior, False)
                self.observed._check(check)
                _unused(conn, self.request_id)
                _legacy_guard(conn, self.observed, operation["payload"])
                if current_version and not current_version.matches(current):
                    raise ValueError("Current editable deck changed before recovery")
                client = conn._capture_client
                published = [publish_source_in(conn, client, item) for item in staged]
                client.journal.apply_in(conn, operation, client.writer)
                with suppress_capture(conn):
                    activated = artifacts.activate(conn, operation, directory)
                if not activated:
                    raise ValueError("Recovered deck no longer has its prepared destination")
                receipt = dict(_context(self.observed, source, self.request_id, self.replace),
                    native=dict(id=operation["operation_id"],
                                fingerprint=candidates._fingerprint(operation)),
                    originals=[dict(id=o["operation_id"], fingerprint=candidates._fingerprint(o),
                                    source_parent=owner["source_parent"],
                                    target_parent=owner["target_parent"])
                               for o, owner in zip(published, owners, strict=True)])
                choices._write_receipt(conn, self.request_id, _hash(receipt), receipt)
                if not closure.matches(source):
                    raise ValueError("Old deck assets changed before recovery committed")
                for value in originals.values():
                    native._original_current(value["proof"])
                self.observed.source._check(check)
                native._binding_in(conn, self.observed)
                if tuple(generation._identity(self.observed.database)) != self.observed.identity:
                    raise ValueError("Deck recovery destination was replaced")
                _legacy_guard(conn, self.observed, operation["payload"])
                if (not directory.matches(operation) or current_version
                        and not current_version.matches(current)):
                    raise ValueError("Editable deck files changed before recovery committed")
                check()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return _result(receipt, True)


def prepare(observed, change_id, request_id, *, replace=False, seconds=60,
            cancelled=lambda: False):
    """Compare complete editable content before explicit native restore/replacement."""
    _identifier(request_id)
    if type(replace) is not bool:
        raise ValueError("Choose explicitly whether to replace the deck")
    check = backup._guard(seconds, cancelled)
    native._auth(observed, check)
    source = observed.source.details(change_id, cancelled=cancelled)["operation"]
    payload = _payload(source)
    with closing(_readonly_connection(observed.database)) as conn:
        conn.execute("BEGIN")
        native._binding_in(conn, observed)
        prior = _prior(conn, observed, source, request_id, replace, check)
        if prior is not None:
            operation_json, comparison = "null", {}
        else:
            _unused(conn, request_id)
            _closure_proof, body, _blobs, originals = _closure(observed, source, check)
            mapper = choices._parent_mapper(conn, observed, source, check)
            parents = [mapper(parent) for parent in source["parents"]]
            client = conn._capture_client
            state = client._optimistic_graph(conn)[0].get(("research_file", source["entity_id"]))
            current = artifacts.desired_file(conn, source["entity_id"])
            if state is not None and not replace:
                raise ValueError("Compare the existing or deleted deck before replacement")
            _legacy_guard(conn, observed, payload)
            operation = client.new_graph_operation_in(
                conn, "research_file", source["entity_id"], payload, operation_id=request_id,
                restore=bool(state and (not state["active"] or state["parents"] != parents)),
            )
            if operation["parents"] != parents:
                raise ValueError("Deck paper differs from its verified recovery mapping")
            current_body = None
            if current:
                paths = _inspection_paths(conn)
                if paths is None:
                    raise ValueError("Current deck storage is unregistered")
                _proof, current_body, _bytes = artifacts.verify_closure(paths[0], current)
            comparison = dict(source=body, current=current_body, original_hashes=sorted(originals),
                              original_owners=_mapped_originals(mapper, originals),
                              state="absent" if state is None else
                              "active" if state["active"] else "retired")
            operation_json = canonical_operation(operation)
    observed._check(check)
    comparison_json = candidates._json(comparison)
    return DeckGroup(observed, change_id, request_id, operation_json, comparison_json, replace,
                     prior is not None, _sign(observed, change_id, request_id, operation_json,
                                             comparison_json, replace))
