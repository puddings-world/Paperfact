"""Atomic private original/provenance pairs for admitted reading-position intents.

Published pairs are archive-only private source provenance. They grant no active
position, synchronization operation, device identity or resumable job. Reserved
bounded staging directories are disposable and never interpreted as research.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from itertools import islice
from pathlib import Path

from paper_daily import file_change, source_snapshots
from paper_daily.sync_documents import MAX_PDF_BYTES
from paper_daily.sync_files import canonical_json
from paper_daily.sync_legacy_sources import path as owned_path

FORMAT = "paperfact.position-source-owner.v2"
STAGE = re.compile(r"\.position-stage-[a-z0-9_]{8}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def stage_root(database, identity, binding):
    root = owned_path(
        Path(database).parent
        / ".paperfact-source-snapshots"
        / source_snapshots._namespace(dict(database_identity=list(identity), binding=binding))
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_stage(directory):
    directory = owned_path(directory)
    if (
        not directory.is_dir()
        or not STAGE.fullmatch(directory.name)
        or not HASH.fullmatch(directory.parent.name)
        or directory.parent.parent.name != ".paperfact-source-snapshots"
    ):
        return False
    entries = list(islice(directory.iterdir(), 3))
    if len(entries) > 2:
        return False
    for entry in entries:
        owned_path(entry)
        if not entry.is_file() or entry.name not in ("receipt.json", "original.pdf"):
            return False
        maximum = source_snapshots.MAX_RECEIPT if entry.name == "receipt.json" else MAX_PDF_BYTES
        if entry.stat().st_size > maximum:
            return False
    return True


def is_stage_file(database, entry):
    entry = owned_path(entry)
    return entry.parent.parent.parent == Path(
        database
    ).parent / ".paperfact-source-snapshots" and is_stage(entry.parent)


def create_stage(database, identity, binding):
    return tempfile.TemporaryDirectory(
        prefix=".position-stage-", dir=stage_root(database, identity, binding)
    )


def cleanup_stage(lease, database):
    selected = Path(lease.name).absolute()
    expected = Path(database).parent / ".paperfact-source-snapshots"
    if selected.parent.parent != expected or not STAGE.fullmatch(selected.name):
        raise ValueError("Position staging cleanup is outside its fixed owned workspace")
    if selected.exists() and not is_stage(selected):
        raise ValueError("Position staging cleanup contains an unexpected entry")
    lease.cleanup()


def verify(database, row, *, known_version=None):
    source_snapshots.validate(row)
    if json.loads(row["owner_json"])["format"] not in source_snapshots.ATOMIC_FORMATS:
        raise ValueError("Atomic position originals require their exact private format")
    receipt = source_snapshots.receipt_path(database, row)
    directory = owned_path(receipt.parent)
    if {entry.name for entry in islice(directory.iterdir(), 3)} != {"receipt.json", "original.pdf"}:
        raise ValueError("Private position source has an incomplete or unknown file closure")
    owned_path(receipt)
    if receipt.stat().st_size > source_snapshots.MAX_RECEIPT:
        raise ValueError("Private position source receipt exceeds its bound")
    saved = source_snapshots.validate(source_snapshots._decode(receipt.read_bytes()))
    if canonical_json(saved) != canonical_json(row):
        raise ValueError("Private position source changed its exact owner/hash")
    source = owned_path(directory / "original.pdf")
    version = file_change.version(source)
    if version[2] != row["size"]:
        raise ValueError("Private position source differs from its exact size")
    if known_version is None or version != known_version:
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                raise ValueError("Private position source differs from its original hash")
    if file_change.version(source) != version:
        raise ValueError("Private position original changed during verification")
    return source, version


def _write_receipt(directory, row):
    with (directory / "receipt.json").open("wb") as stream:
        stream.write(canonical_json(row))
        stream.flush()
        os.fsync(stream.fileno())


def publish(database, row, *, data=None, stage=None, version=None):
    """Publish a whole checked pair by rename; caller owns any later SQL commit."""
    from paper_daily.local_source_owners import validate

    validate(row)
    metadata = json.loads(row["owner_json"])
    if (metadata["format"] not in source_snapshots.ATOMIC_FORMATS
            or (data is None) == (stage is None)):
        raise ValueError("Position publication requires its checked bytes or owned stage")
    directory = source_snapshots.receipt_path(database, row).parent
    if directory.exists():
        return verify(database, row)
    namespace = stage_root(database, metadata["database_identity"], metadata["binding"])
    entries = list(islice(namespace.iterdir(), source_snapshots.MAX_RECEIPTS * 2 + 1))
    if (
        len(entries) > source_snapshots.MAX_RECEIPTS * 2
        or sum(not STAGE.fullmatch(item.name) for item in entries) >= source_snapshots.MAX_RECEIPTS
    ):
        raise ValueError("Private position source history exceeds its receipt budget")
    if stage is not None:
        stage = owned_path(stage)
        if stage.parent != namespace or not is_stage(stage):
            raise ValueError("Position import staging belongs to another namespace")
        if file_change.version(stage / "original.pdf") != version:
            raise ValueError("Position original changed after its staged byte proof")
        _write_receipt(stage, row)
        if file_change.version(stage / "original.pdf") != version:
            raise ValueError("Position original changed during receipt publication")
        try:
            os.rename(stage, directory)
        except FileExistsError:
            return verify(database, row)
        return verify(database, row, known_version=version)
    if (
        not isinstance(data, bytes)
        or len(data) != row["size"]
        or hashlib.sha256(data).hexdigest() != row["sha256"]
    ):
        raise ValueError("Position publication bytes differ from their exact original")
    lease = create_stage(database, metadata["database_identity"], metadata["binding"])
    selected = Path(lease.name)
    try:
        with (selected / "original.pdf").open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _write_receipt(selected, row)
        try:
            os.rename(selected, directory)
        except FileExistsError:
            return verify(database, row)
        return verify(database, row)
    finally:
        cleanup_stage(lease, database)
