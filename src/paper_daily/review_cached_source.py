"""Process-only evidence for bytes recovered from a receiver-owned private store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from paper_daily.sync_legacy_sources import path as safe_path

_SEAL = object()


@dataclass(frozen=True, init=False)
class CachedOwner:
    index: Path = field(repr=False)
    native: tuple
    binding: tuple = field(repr=False)
    document_hash: str
    size: int
    _seal: object = field(repr=False)


def capture(review, client, store, document_hash):
    """Worker-only metadata; no research authority, old paths or byte substitution."""
    from paper_daily.sync_source_files import MAX_PDF_BYTES

    index = safe_path(store.root / "index.sqlite")
    try:
        before = index.stat()
        with closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True, timeout=0.025)) as conn:
            conn.execute("BEGIN")
            binding = conn.execute(
                "SELECT workspace,device,research_path FROM transfer_binding WHERE id=1"
            ).fetchone()
            wanted = (
                client.journal.workspace_id,
                client.journal.device_id,
                str(review.path.resolve()),
            )
            if binding is None or tuple(binding) != wanted:
                raise ValueError(
                    "Recovered original store workspace/device/database binding changed"
                )
            item = conn.execute(
                "SELECT size,complete FROM blobs WHERE digest=?", (document_hash,)
            ).fetchone()
        after = index.stat()
        native = before.st_dev, before.st_ino
        if native != (after.st_dev, after.st_ino):
            raise ValueError("Recovered original store was replaced during verification")
        if item is None:
            return None
        if type(item[0]) is not int or not 0 < item[0] <= MAX_PDF_BYTES or item[1] != 1:
            raise ValueError("Recovered original store has no complete bounded source")
    except (OSError, sqlite3.DatabaseError) as error:
        raise ValueError(
            "Recovered original store metadata is unavailable; your draft is retained"
        ) from error
    owner = object.__new__(CachedOwner)
    for name, value in dict(
        index=index,
        native=native,
        binding=wanted,
        document_hash=document_hash,
        size=item[0],
        _seal=_SEAL,
    ).items():
        object.__setattr__(owner, name, value)
    return owner


def check(owner, review, prepared, client):
    """Recheck captured store ownership without hashing bytes on the save boundary."""
    if not isinstance(owner, CachedOwner) or getattr(owner, "_seal", None) is not _SEAL:
        raise ValueError("A native recovered original store observation is required")
    if owner.index != prepared.store.root / "index.sqlite" or owner.binding != (
        prepared.workspace,
        prepared.device,
        str(prepared.database),
    ):
        raise ValueError("Recovered original store differs from its prepared owner")
    from paper_daily.sync_files import read_json

    payload = read_json(prepared.payload.encode())
    assets = {item["sha256"]: item["size"] for item in payload["assets"]}
    if payload["slot"] != owner.document_hash or assets.get(owner.document_hash) != owner.size:
        raise ValueError("Recovered original store observation differs from its source")
    if capture(review, client, prepared.store, owner.document_hash) != owner:
        raise ValueError("Recovered original store owner or source completeness changed")
