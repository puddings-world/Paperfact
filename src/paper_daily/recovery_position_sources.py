"""Fresh private position originals, only inside sealed editable-recovery staging."""

from __future__ import annotations

import json
from pathlib import Path

from paper_daily import local_source_owners, position_source_snapshots, source_snapshots
from paper_daily import reading_position_ops as operations
from paper_daily import reading_positions as positions
from paper_daily.manual_highlight_ops import capture_owner_in
from paper_daily.research_generation import _path
from paper_daily.sync_files import canonical_json, file_id, validate_closure


def _authority(value, records, row):
    tables, manifest = value["tables"], value["manifest"]
    paper, digest = row["paper_id"], row["document_hash"]
    parent = records.parent_lifecycles.get(("paper", paper))
    if parent is None or not parent["active"] or paper not in records.paper_ids:
        raise ValueError("Recovered reading position lacks its active original paper lifecycle")
    if manifest["workspace_id"] is not None:
        identities = [key for key, local in records.paper_map.items() if local == paper]
        if len(identities) != 1:
            raise ValueError("Recovered reading position lacks its exact portable paper")
        portable = identities[0]
        entity = file_id(portable, "original_source", digest)
        desired = [
            item for item in tables.get("research_file_desired", []) if item["entity_id"] == entity
        ]
        projection = [
            item
            for item in tables.get("research_paper_projection", [])
            if item["sync_id"] == portable
        ]
        if (
            len(desired) != 1
            or type(desired[0]["active"]) is not int
            or desired[0]["active"] != 1
            or len(projection) != 1
        ):
            raise ValueError("Recovered position original is missing, retired or unowned")
        operation = json.loads(desired[0]["operation"])
        expected = [{"kind": "paper", "id": portable, "incarnation": projection[0]["incarnation"]}]
        if (
            operation["action"] != "put"
            or operation["parents"] != expected
            or operation["payload"]["paper_id"] != portable
            or operation["payload"]["feature"] != "original_source"
            or operation["payload"]["source_document_hash"] != digest
        ):
            raise ValueError("Recovered position original belongs to another paper incarnation")
        return operation["payload"]

    sidecars = {
        item["request_id"]: item for item in tables.get("research_source_snapshot_recovery", [])
    }
    for receipt in tables.get("research_local_source_owners", []):
        local_source_owners.validate(receipt)
        owner = json.loads(receipt["owner_json"])
        if (
            owner["format"] in source_snapshots.POSITION_FORMATS
            and owner["binding"] is None
            and owner["paper_id"] == paper
            and owner["parent_lifecycle"] == parent["token"]
            and receipt["sha256"] == digest
            and receipt["size"] == records.refs[digest]
            and receipt == sidecars.get(receipt["request_id"])
        ):
            return None
    raise ValueError("Recovered reading position lacks its exact original ownership proof")


def stage(service, inspection, conn, value, ticket):
    """Caller owns an unpublished baseline transaction, never original/live authority."""
    from paper_daily.recovery_adoption import RecoveryAdoptionService, RecoveryInspection, _records

    if (
        not isinstance(service, RecoveryAdoptionService)
        or type(inspection) is not RecoveryInspection
    ):
        raise ValueError("Position recovery requires its native sealed inspection")
    service._metadata_current(inspection, ticket)
    if canonical_json(value) != inspection._snapshot or not conn.in_transaction:
        raise ValueError("Position recovery requires its exact caller-owned staging transaction")
    database = Path(_path(conn)).resolve(strict=True)
    if database == service.database or database.is_relative_to(service.root):
        raise ValueError("Position recovery cannot write into its detached source")
    selected = value["tables"].get(positions.TABLE, [])
    if not selected:
        return
    if len(selected) > source_snapshots.MAX_RECEIPTS:
        raise ValueError("Recovered position originals exceed their receiver ownership budget")
    records = _records(value)
    for row in selected:
        ticket.check()
        positions.validate_row(row)
        if positions.read(conn, row["paper_id"], row["document_hash"]) != row:
            raise ValueError("Recovered staged position differs from its canonical source")
        payload = _authority(value, records, row)
        blobs = {}

        def read(descriptor, *, cache=blobs):
            digest = descriptor["sha256"]
            if digest not in cache:
                if records.refs.get(digest) != descriptor["size"]:
                    raise ValueError("Recovered position source is not in its declared closure")
                checked = local_source_owners._read_pdf(
                    service.root / "objects" / digest,
                    digest,
                    descriptor["size"],
                    lambda: ticket.cancelled,
                )
                ticket.check()
                cache[digest] = checked[0]
            return cache[digest]

        if payload is not None:
            validate_closure(payload, read)
        digest = row["document_hash"]
        data = read({"sha256": digest, "size": records.refs[digest]})
        positions.verify_page(row, data)
        service._metadata_current(inspection, ticket)
        owner = capture_owner_in(conn, row["paper_id"])
        receipt = operations._source_receipt(owner, digest, len(data))
        position_source_snapshots.publish(database, receipt, data=data)
        ticket.check()
        owner.check(conn)
        if positions.read(conn, row["paper_id"], digest) != row:
            raise ValueError("Recovered position changed before original ownership publication")
        conn.execute(local_source_owners.SCHEMA)
        if not local_source_owners._schema(conn):
            raise ValueError("Receiver original ownership schema is unavailable")
        if conn.execute("SELECT COUNT(*) FROM research_local_source_owners").fetchone()[0] >= (
            source_snapshots.MAX_RECEIPTS
        ):
            raise ValueError("Recovered position ownership exceeds its metadata budget")
        conn.execute(
            "INSERT INTO research_local_source_owners VALUES(?,?,?,?,?)",
            tuple(receipt[key] for key in local_source_owners.COLUMNS.split()),
        )
        service._metadata_current(inspection, ticket)
