"""Private original-source ownership receipts; never remote or publication authority.

Verified bytes are published before ownership. A crash can leave unowned bytes;
retry repairs that boundary without deleting another pending job's original.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import closing
from itertools import islice
from pathlib import Path

from paper_daily import claim_content
from paper_daily import research_evidence as evidence
from paper_daily import research_generation as generation
from paper_daily.sync_legacy_sources import path as owned_path

TABLE = "research_source_snapshot_recovery"
COLUMNS = "request_id owner_json sha256 size media_type"
FIELDS = set(COLUMNS.split())
MAX_RECEIPT = 16 * 1024
MAX_RECEIPTS = 10000
_PUBLICATION_LOCK = threading.RLock()
_DEFAULT_POLICY = object()
POSITION_FORMATS = {"paperfact.position-source-owner.v1", "paperfact.position-source-owner.v2"}
NOTE_FORMAT = "paperfact.note-source-owner.v1"
LINEAGE_FORMAT = "paperfact.lineage-source-observation.v1"
ATOMIC_FORMATS = {"paperfact.position-source-owner.v2", NOTE_FORMAT, LINEAGE_FORMAT}


def _owner(context, snapshot):
    data = context.data
    source, _bytes = evidence._checked_snapshot(snapshot)
    origin = snapshot._origin
    expected_owner = ((data["observation"] or {}).get("parents") or [{}])[0].get("id")
    if (
        origin.local_id != context.owner_id
        or origin._owner.db_path.resolve() != context.db_path
        or source["paper_id"] != (expected_owner or context.owner_id)
        or not data["document"]
        or source["document_hash"] != data["document"]["sha256"]
    ):
        raise ValueError("Source snapshot does not belong to the captured owner")
    return {
        "format": "paperfact.source-owner.v1",
        "database_identity": data["database_identity"],
        "binding": data["binding"],
        "paper_id": context.owner_id,
        "parent_lifecycle": data["parent_lifecycle"],
        "source_owner_id": source["paper_id"],
    }


def _decode(encoded):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate source snapshot field")
            result[key] = value
        return result

    return json.loads(encoded, object_pairs_hook=pairs)


def validate(row, *, max_pdf_bytes=_DEFAULT_POLICY):
    from paper_daily.sync_documents import MAX_PDF_BYTES as primary_limit

    claim_content.closed(row, FIELDS)
    claim_content.text(row["request_id"], 128)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", row["request_id"]):
        raise ValueError("Invalid source snapshot request identity")
    if not isinstance(row["owner_json"], str) or len(row["owner_json"].encode()) > MAX_RECEIPT:
        raise ValueError("Source snapshot owner exceeds its bound")
    try:
        owner = _decode(row["owner_json"])
    except (ValueError, TypeError):
        raise ValueError("Invalid source snapshot owner") from None
    position = (
        isinstance(owner, dict) and owner.get("format") in POSITION_FORMATS
    )
    note = isinstance(owner, dict) and owner.get("format") == NOTE_FORMAT
    lineage = isinstance(owner, dict) and owner.get("format") == LINEAGE_FORMAT
    lineage_fields = (
        {"corpus_id", "generation_request_id", "source_id", "source_identity",
         "focal_paper_id", "focal_lifecycle"}
        if lineage else set()
    )
    claim_content.closed(
        owner,
        {
            "format",
            "database_identity",
            "binding",
            "paper_id",
            "parent_lifecycle",
            "source_owner_id",
        } | ({"position_key"} if position else set())
        | ({"draft_key"} if note else set()) | lineage_fields,
    )
    if owner["format"] not in {
        "paperfact.source-owner.v1", NOTE_FORMAT, LINEAGE_FORMAT, *POSITION_FORMATS
    }:
        raise ValueError("Unsupported source snapshot owner")
    identity = owner["database_identity"]
    if (
        not isinstance(identity, list)
        or len(identity) != 2
        or any(type(item) is not int or item < 0 for item in identity)
    ):
        raise ValueError("Invalid source snapshot database provenance")
    binding = owner["binding"]
    if binding is not None:
        claim_content.closed(binding, {"workspace_id", "device_id"})
        for item in binding.values():
            claim_content.text(item, 128)
    claim_content.text(owner["paper_id"], 4096)
    claim_content.text(owner["source_owner_id"], 512)
    if not isinstance(owner["parent_lifecycle"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", owner["parent_lifecycle"]
    ):
        raise ValueError("Invalid source snapshot parent epoch")
    if note:
        claim_content.digest(owner["draft_key"])
        if (owner["source_owner_id"] != owner["paper_id"] or row["request_id"] !=
                "note-choice:" + claim_content.hashed(owner)):
            raise ValueError("Note choice receipt requires its exact typed owner")
    claim_content.digest(row["sha256"])
    if lineage:
        from paper_daily.lineage_source_snapshots import validate_owner

        validate_owner(owner, row)
    if position and (
        owner["position_key"] != row["sha256"] or owner["source_owner_id"] != owner["paper_id"]
    ):
        raise ValueError("Position original belongs to another exact position owner")
    if max_pdf_bytes is _DEFAULT_POLICY:
        max_pdf_bytes = primary_limit if position or note else evidence.MAX_PDF_BYTES
    if type(max_pdf_bytes) is not int or not 0 < max_pdf_bytes <= primary_limit:
        raise ValueError("Invalid trusted source receipt size policy")
    claim_content.number(row["size"], max_pdf_bytes, 1)
    if row["media_type"] != "application/pdf":
        raise ValueError("Unsupported source snapshot media")
    return row


def _namespace(owner):
    return claim_content.hashed({key: owner[key] for key in ("database_identity", "binding")})


def receipt_path(database, row):
    owner = json.loads(validate(row)["owner_json"])
    root = Path(database).parent / ".paperfact-source-snapshots" / _namespace(owner)
    key = claim_content.hashed(row["request_id"])
    if owner["format"] in ATOMIC_FORMATS:
        return owned_path(root / key / "receipt.json")
    return owned_path(root / (key + ".json"))


def source_path(database, row, *, max_pdf_bytes=_DEFAULT_POLICY):
    owner = json.loads(validate(row, max_pdf_bytes=max_pdf_bytes)["owner_json"])
    if owner["format"] in ATOMIC_FORMATS:
        return owned_path(receipt_path(database, row).parent / "original.pdf")
    if owner["format"] == "paperfact.position-source-owner.v1":
        alias = claim_content.hashed(["reading-position-owner", owner["paper_id"]])[:24]
        return owned_path(
            Path(database).parent / "pdf" / ".reading-positions" / alias / (row["sha256"] + ".pdf")
        )
    alias = claim_content.hashed(["claim-source-owner", owner["paper_id"]])[:24]
    return owned_path(
        Path(database).parent / "pdf" / ".claim-evidence" / alias / (row["sha256"] + ".pdf")
    )


def _atomic(destination, data, request_id):
    with _PUBLICATION_LOCK:
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage_id = claim_content.hashed([request_id, "source-stage"])[:32]
        temporary = owned_path(destination.with_name(destination.name + "." + stage_id + ".part"))
        # Another captured job has its own staging bytes. Identical retry repairs
        # only this owned staging path, never truncating a different pending job.
        with temporary.open("wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        owned_path(destination)
        os.replace(temporary, destination)


def _publish_receipt(destination, row):
    encoded = claim_content.hashed(row)
    if destination.exists():
        if destination.stat().st_size > MAX_RECEIPT:
            raise ValueError("Source snapshot receipt exceeds its bound")
        existing = validate(_decode(destination.read_text(encoding="utf-8")))
        if claim_content.hashed(existing) != encoded:
            raise ValueError("Source snapshot retry changed its ownership")
        return
    if destination.parent.exists() and sum(1 for _ in destination.parent.iterdir()) >= MAX_RECEIPTS:
        raise ValueError("Source snapshot history exceeds its receipt bound")
    _atomic(destination, (generation._json(row) + "\n").encode(), row["request_id"])


def retain(context, snapshot):
    """Grant local provenance only after sealed original bytes are durable."""
    source, data = evidence._checked_snapshot(snapshot)
    owner = _owner(context, snapshot)
    row = validate(
        {
            "request_id": context.request_id,
            "owner_json": generation._json(owner),
            "sha256": source["document_hash"],
            "size": len(data),
            "media_type": "application/pdf",
        }
    )
    destination = source_path(context.db_path, row)
    if destination.exists():
        if destination.stat().st_size != len(data) or destination.read_bytes() != data:
            raise ValueError("Original source snapshot bytes are damaged")
    else:
        _atomic(destination, data, row["request_id"])
    _publish_receipt(receipt_path(context.db_path, row), row)
    return row


def list_owned(database):
    """Read private provenance matching this DB/binding; never activate old owners."""
    database = Path(database).resolve(strict=True)
    with closing(generation._connect(database)) as conn:
        owner = {
            "database_identity": generation._identity(database),
            "binding": generation._binding(conn),
        }
    root = owned_path(database.parent / ".paperfact-source-snapshots" / _namespace(owner))
    if not root.exists():
        return []
    from paper_daily import position_source_snapshots as position_sources

    rows = []
    entries = list(islice(root.iterdir(), MAX_RECEIPTS * 2 + 1))
    if len(entries) > MAX_RECEIPTS * 2:
        raise ValueError("Source snapshot history exceeds its entry bound")
    for item in sorted(entries):
        owned_path(item)
        if item.is_dir():
            if position_sources.is_stage(item):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", item.name):
                raise ValueError("Unsupported private source snapshot directory")
            receipt = owned_path(item / "receipt.json")
            if not receipt.is_file() or receipt.stat().st_size > MAX_RECEIPT:
                raise ValueError("Private position source receipt is missing or oversized")
            row = validate(_decode(receipt.read_bytes()))
            if receipt_path(database, row) != receipt:
                raise ValueError("Position receipt differs from its canonical location")
            position_sources.verify(database, row)
            rows.append(row)
            if len(rows) > MAX_RECEIPTS:
                raise ValueError("Source snapshot history exceeds its receipt bound")
            continue
        if item.suffix != ".json" or not item.is_file() or item.stat().st_size > MAX_RECEIPT:
            raise ValueError("Unsupported private source snapshot receipt")
        if len(rows) >= MAX_RECEIPTS:
            raise ValueError("Source snapshot history exceeds its receipt bound")
        row = validate(_decode(item.read_text(encoding="utf-8")))
        if receipt_path(database, row) != item:
            raise ValueError("Source snapshot receipt ownership differs from its location")
        path = source_path(database, row)
        if not path.is_file() or path.stat().st_size != row["size"]:
            raise ValueError("Owned original source snapshot bytes are missing")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                raise ValueError("Owned original source snapshot bytes changed")
        rows.append(row)
    return rows
