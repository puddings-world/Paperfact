"""Exact-paper source closure for later outcomes, then fresh editable-copy ownership."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from paper_daily import later_outcomes as outcomes
from paper_daily import local_source_owners as owners
from paper_daily import research_generation as generation
from paper_daily import source_snapshots
from paper_daily.research_lifecycle import ensure_lifecycle, parent_lifecycle
from paper_daily.sync_files import canonical_json, file_id, validate_closure


class Records:
    def __init__(self):
        self.outcomes = {}
        self.receipts = []
        self.desired = {}
        self.applied = {}
        self.parents = {}

    def add(self, name, row):
        if name == outcomes.TABLE:
            outcomes.validate_row(row)
            if row["paper_id"] in self.outcomes:
                raise ValueError("Duplicate recovered later outcome")
            self.outcomes[row["paper_id"]] = row
        elif name in {"research_local_source_owners", "research_source_snapshot_recovery"}:
            source_snapshots.validate(row)
            self.receipts.append(row)
        elif name == "research_paper_projection":
            self.parents[row["sync_id"]] = row["incarnation"]
        elif name in {"research_file_desired", "research_file_applied"}:
            (self.desired if name == "research_file_desired" else self.applied)[
                row["entity_id"]
            ] = row

    def authority(self, records, row):
        paper, sha = row["paper_id"], row["document_hash"]
        if paper not in records.paper_ids:
            raise ValueError("Recovered later outcome lacks exact paper")
        if sha is None:
            return None
        parent = records.parent_lifecycles.get(("paper", paper))
        portable = [key for key, local in records.paper_map.items() if local == paper]
        for receipt in self.receipts:
            owner = json.loads(receipt["owner_json"])
            if (
                receipt["sha256"] == sha
                and owner["paper_id"] == paper
                and parent is not None
                and parent["active"]
                and owner["parent_lifecycle"] == parent["token"]
                and owner["source_owner_id"] in {paper, *portable}
            ):
                return receipt
        if len(portable) == 1:
            key = file_id(portable[0], "original_source", sha)
            desired = self.desired.get(key)
            applied = self.applied.get(key)
            if (
                desired
                and applied
                and desired["active"] == 1
                and desired["operation"] == applied["operation"]
            ):
                operation = json.loads(applied["operation"])
                payload = operation["payload"]
                if (
                    operation["action"] == "put"
                    and payload["paper_id"] == portable[0]
                    and payload["feature"] == "original_source"
                    and payload["source_document_hash"] == sha
                    and operation["parents"]
                    == [
                        {
                            "kind": "paper",
                            "id": portable[0],
                            "incarnation": self.parents.get(portable[0]),
                        }
                    ]
                ):
                    return payload
        raise ValueError("Recovered later outcome lacks its exact paper/source ownership")

    def finish(self, records):
        for row in self.outcomes.values():
            self.authority(records, row)


def stage(service, inspection, conn, value, ticket):
    from paper_daily.later_outcome_packages import read
    from paper_daily.recovery_adoption import RecoveryAdoptionService, RecoveryInspection, _records

    if (
        not isinstance(service, RecoveryAdoptionService)
        or not isinstance(inspection, RecoveryInspection)
        or inspection._owner is not service
    ):
        raise ValueError("Later recovery requires its sealed inspected detached source")
    service._metadata_current(inspection, ticket)
    if not conn.in_transaction or canonical_json(value) != inspection._snapshot:
        raise ValueError("Later recovery requires its exact caller-owned staging snapshot")
    database = Path(generation._path(conn))
    if database == service.database or database.is_relative_to(service.root):
        raise ValueError("Later recovery cannot edit its source")
    selected = value["tables"].get(outcomes.TABLE, [])
    if not selected:
        return
    if len(selected) > 500:
        raise ValueError("Too many recovered later outcomes")
    records = _records(value)
    typed = records.later_outcomes
    ensure_lifecycle(conn)
    for row in selected:
        ticket.check()
        outcomes.validate_row(row)
        if read(conn, row["paper_id"]) != row:
            raise ValueError("Staged later outcome changed")
        authority = typed.authority(records, row)
        if row["document_hash"] is None:
            continue
        sha = row["document_hash"]
        size = records.refs[sha]
        verified = owners._read_pdf(
            service.root / "objects" / sha, sha, size, lambda: ticket.cancelled
        )
        ticket.check()
        if verified is None:
            raise ValueError("Later source verification did not complete")
        data, _version = verified
        if authority.get("feature") == "original_source":

            def get(descriptor, *, source_hash=sha, source_data=data):
                if descriptor["sha256"] == source_hash:
                    return source_data
                location = service.root / "objects" / descriptor["sha256"]
                if (
                    records.refs.get(descriptor["sha256"]) != descriptor["size"]
                    or location.stat().st_size != descriptor["size"]
                ):
                    raise ValueError("Recovered later artifact closure differs")
                return location.read_bytes()

            validate_closure(authority, get)
        service._metadata_current(inspection, ticket)
        ticket.check()
        owner = dict(
            format="paperfact.source-owner.v1",
            database_identity=generation._identity(database),
            binding=generation._binding(conn),
            paper_id=row["paper_id"],
            parent_lifecycle=parent_lifecycle(conn, "paper", row["paper_id"]),
            source_owner_id=row["paper_id"],
        )
        receipt = owners.validate(
            dict(
                request_id="import:" + hashlib.sha256(canonical_json([owner, row])).hexdigest(),
                owner_json=canonical_json(owner).decode(),
                sha256=sha,
                size=size,
                media_type="application/pdf",
            )
        )
        target = source_snapshots.source_path(database, receipt, max_pdf_bytes=32 * 1024**2)
        if target.exists():
            owners._read_pdf(target, sha, size)
        else:
            source_snapshots._atomic(target, data, receipt["request_id"])
        if read(conn, row["paper_id"]) != row:
            raise ValueError("Later recovery target changed before receiver ownership")
        if not owners._schema(conn):
            conn.execute(owners.SCHEMA)
        if (
            conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0]
            >= source_snapshots.MAX_RECEIPTS
        ):
            raise ValueError("Recovered later source ownership exceeds budget")
        conn.execute(
            "INSERT INTO research_local_source_owners VALUES(?,?,?,?,?)",
            tuple(receipt[k] for k in owners.COLUMNS.split()),
        )
        service._metadata_current(inspection, ticket)
