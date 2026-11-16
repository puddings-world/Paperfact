"""Offline exact-byte supply for an existing document target, without a new version."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from paper_daily import native_primary_publication as native
from paper_daily.legacy_primary_migration import _encoded, _scope
from paper_daily.sync_blobs import BlobManifest
from paper_daily.sync_documents import applied_document, bind_verified_document, verify_document
from paper_daily.sync_journal import _identifier

_SEAL = object()


class NoKnownOriginal(ValueError):
    """There is no active original to supply; retirement is not a missing file."""


def _ownership(scope):
    # Metadata edits/acknowledgments do not change which exact original is wanted.
    # Desired operation and local paper lifetime remain exact, including parents.
    return dict(
        binding=scope["binding"], registration=scope["registration"],
        lifecycle=scope["lifecycle"], desired=scope["desired"],
        parent={k: v for k, v in scope["parent"].items() if k != "structure_revision"},
    )


@dataclass(frozen=True)
class PreparedSupply:
    source: object = field(repr=False)
    target_json: bytes = field(repr=False)
    ownership_json: bytes = field(repr=False)
    verified: object = field(repr=False)
    request_id: str
    running: object = field(repr=False)
    seal: object = field(repr=False)

    @property
    def target(self):
        return json.loads(self.target_json)

    @property
    def fingerprint(self):
        return hashlib.sha256(_encoded(dict(
            mode="known_document_supply", ownership=json.loads(self.ownership_json),
            database=str(self.source.database), identity=self.source.identity,
            store_identity=self.source.store_identity,
        ))).hexdigest()

    def check_in(self, conn):
        source = self.source
        source.live()
        now = _encoded(_ownership(_scope(conn, source.actions, source.document)))
        if now != self.ownership_json:
            raise ValueError("Known original or workspace changed during supply")
        if not self.verified.matches(self.target):
            raise ValueError("Verified original changed before binding")


def prepare(source, path, *, request_id=None, expected_target=None):
    """Stage/verify an explicit local file for the already observed desired target."""
    if not isinstance(source, native.PrimaryObservation) or source.seal is not native._SEAL:
        raise ValueError("Expected an owned original observation")
    target = json.loads(source.scope)["desired"]
    if target is None:
        raise NoKnownOriginal("There is no active known original to supply")
    if expected_target is not None and target != expected_target:
        raise ValueError("Selected original changed before supply")
    request_id = request_id or str(uuid4())
    _identifier(request_id)
    before = _encoded(_ownership(json.loads(source.scope)))
    journal = source.actions.client.journal

    def check_in(conn):
        source.live()
        if _encoded(_ownership(_scope(conn, source.actions, source.document))) != before:
            raise ValueError("Known original or workspace changed during supply")

    with journal.transaction() as conn:
        check_in(conn)
    source.store.import_file(
        BlobManifest(target["sha256"], target["size"]), path, check=source.live,
    )
    verified = verify_document(source.store, target)
    with journal.transaction() as conn:
        check_in(conn)
    return PreparedSupply(source, _encoded(target), before, verified, request_id, Lock(), _SEAL)


def run(prepared):
    """Bind exact verified cache bytes and one private receipt in the same SQL commit."""
    if not isinstance(prepared, PreparedSupply) or prepared.seal is not _SEAL:
        raise ValueError("Expected a prepared known-original supply")
    if not prepared.running.acquire(blocking=False):
        raise ValueError("This original supply is already running")
    try:
        source = prepared.source
        journal = source.actions.client.journal
        results = []

        def publish():
            with journal.transaction() as conn:
                prepared.check_in(conn)
                previous = conn.execute(
                    "SELECT fingerprint,result FROM research_action_receipts WHERE request_id=?",
                    (prepared.request_id,),
                ).fetchone()
                if previous is not None and previous[0] != prepared.fingerprint:
                    raise ValueError("Known-original retry changed its request")
                target = prepared.target
                if not bind_verified_document(conn, target, prepared.verified):
                    raise ValueError("Known original could not be bound")
                prepared.check_in(conn)
                if applied_document(conn, target["paper_id"]) != target:
                    raise ValueError("Known original binding changed")
                result = dict(
                    paper_id=target["paper_id"], operation_id=target["operation_id"],
                    sha256=target["sha256"], size=target["size"], state="bound",
                )
                if previous is not None:
                    if json.loads(previous[1]) != result:
                        raise ValueError("Known-original retry receipt is inconsistent")
                else:
                    conn.execute(
                        "DELETE FROM kv WHERE key=?",
                        ("analyze.failed.pdf." + source.document.local_id,),
                    )
                    conn.execute(
                        "INSERT INTO research_action_receipts VALUES(?,?,?)",
                        (prepared.request_id, prepared.fingerprint, _encoded(result).decode()),
                    )
                source.live()
                results.append(result)

        source.ticket.publish(publish)
        return results[0]
    finally:
        prepared.running.release()
