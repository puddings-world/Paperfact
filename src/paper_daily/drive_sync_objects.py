"""Chunked immutable Drive bytes with private retry receipts, separate from research."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from paper_daily.drive_sync_files import MAX_INLINE, DriveMissing, decode, encode, identifier
from paper_daily.drive_sync_log import reference
from paper_daily.drive_transfer_progress import byte_progress
from paper_daily.presentations import _atomic_json
from paper_daily.sync_blobs import BlobManifest, _no_link

MAX_OBJECT = 150 * 1024**2
FORMAT = "paperfact.drive-bytes.v1"


def checked_manifest(manifest):
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"format", "sha256", "size", "chunks"}
        or manifest["format"] != FORMAT
    ):
        raise ValueError("Unsupported Drive byte manifest")
    blob = BlobManifest(manifest["sha256"], manifest["size"])
    chunks = manifest["chunks"]
    if (
        not 0 < blob.size <= MAX_OBJECT
        or not isinstance(chunks, list)
        or len(chunks) != (blob.size + MAX_INLINE - 1) // MAX_INLINE
    ):
        raise ValueError("Invalid Drive chunk count")
    boundaries = []
    for index, ref in enumerate(chunks):
        length = min(MAX_INLINE, blob.size - index * MAX_INLINE)
        if (
            not isinstance(ref, dict)
            or set(ref) != {"id", "sha256", "size"}
            or ref["size"] != length
        ):
            raise ValueError("Invalid Drive chunk boundary")
        identifier(ref["id"])
        BlobManifest(ref["sha256"], ref["size"])
        boundaries.append((ref, length))
    return blob, boundaries


class DriveObjects:
    def __init__(self, files, folder, workspace, cache, *, folder_role="workspace", check=None):
        if folder_role not in {"workspace", "directory"}:
            raise ValueError("Unknown Drive attachment folder role")
        self.folder_role = folder_role
        self._scope = check
        self.files, self.folder, self.workspace = files, identifier(folder), workspace
        self.cache = Path(cache)
        for entry in (self.cache, *self.cache.parents):
            _no_link(entry)
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _check(self):
        self.files.check()
        if self._scope is not None:
            self._scope()

    def _remember(self, receipt, chunks):
        """The first complete receipt wins even if two readers transfer the same original."""
        record = dict(workspace=self.workspace, folder=self.folder, chunks=chunks)
        if self.folder_role == "workspace":
            _atomic_json(receipt, record)
            return
        value = encode(record)
        with tempfile.TemporaryDirectory(dir=self.cache) as staging:
            temp = Path(staging) / "receipt"
            with temp.open("xb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            with suppress(FileExistsError):
                os.link(temp, receipt)

    def put(self, path, *, expected: BlobManifest | None = None):
        self._check()
        path = Path(path)
        _no_link(path)
        size = path.stat().st_size
        if not 0 < size <= MAX_OBJECT:
            raise ValueError("Drive object is empty or exceeds the transfer limit")
        if expected is not None and expected.size != size:
            raise ValueError("Source size differs from the selected attachment")
        full = hashlib.sha256()
        seen = 0
        parts = []
        with path.open("rb") as source:
            while raw := source.read(MAX_INLINE):
                self._check()
                seen += len(raw)
                if seen > size:
                    raise ValueError("Source grew during Drive upload preparation")
                full.update(raw)
                parts.append((hashlib.sha256(raw).hexdigest(), len(raw)))
        digest = full.hexdigest()
        if seen != size or (expected is not None and digest != expected.sha256):
            raise ValueError("Source bytes differ from the selected attachment")
        if self.folder_role == "directory":
            self.files.owned(self.folder, self.workspace, self.folder_role)
        receipt = self.cache / (digest + ".upload.json")
        _no_link(receipt)
        if not receipt.exists():
            chunks = [
                reference(identity, b"placeholder") for identity in self.files.new_ids(len(parts))
            ]
            for ref, (part_hash, length) in zip(chunks, parts, strict=True):
                ref.update(sha256=part_hash, size=length)
            self._remember(receipt, chunks)
        _no_link(receipt)
        saved = decode(receipt.read_bytes())
        if (
            not isinstance(saved, dict)
            or set(saved) != {"workspace", "folder", "chunks"}
            or saved["workspace"] != self.workspace
            or saved["folder"] != self.folder
            or not isinstance(saved["chunks"], list)
            or len(saved["chunks"]) != len(parts)
        ):
            raise ValueError("Drive upload receipt belongs to another transfer")
        chunks = saved["chunks"]
        with path.open("rb") as source:
            confirmed = 0
            for ref, (part_hash, length) in zip(chunks, parts, strict=True):
                self._check()
                if (
                    not isinstance(ref, dict)
                    or set(ref) != {"id", "sha256", "size"}
                    or ref["sha256"] != part_hash
                    or ref["size"] != length
                ):
                    raise ValueError("Drive retry bytes changed")
                identifier(ref["id"])
                raw = source.read(length)
                if len(raw) != length or hashlib.sha256(raw).hexdigest() != part_hash:
                    raise ValueError("Source bytes changed during Drive upload")
                # Preallocated IDs and immutable checksum verification handle a lost reply.
                try:
                    existing = self.files.owned(
                        ref["id"], self.workspace, "blob", parent=self.folder
                    )
                except DriveMissing:
                    self._check()
                    self.files.put_small(ref["id"], self.folder, self.workspace, "blob", raw,
                                         folder_role=self.folder_role)
                else:
                    if (
                        existing.get("size") != str(length)
                        or existing.get("sha256Checksum") != part_hash
                    ):
                        raise ValueError("Drive retry object differs from the captured chunk")
                confirmed += length
                byte_progress(confirmed, size)
            if source.read(1):
                raise ValueError("Source bytes grew during Drive upload")
        self._check()
        return dict(format=FORMAT, sha256=digest, size=size, chunks=chunks)

    def get(self, manifest, store, *, expected: BlobManifest | None = None):
        self._check()
        blob, boundaries = checked_manifest(manifest)
        if expected is not None and expected != blob:
            raise ValueError("Drive manifest differs from the selected attachment")
        if self.folder_role == "directory":
            self.files.owned(self.folder, self.workspace, self.folder_role)
        chunks = manifest["chunks"]
        if store.available(blob):
            return store.verified_path(blob)
        status = store.begin(blob)
        offset = status["offset"]
        start = 0
        fetched_all = offset == 0
        for ref, length in boundaries:
            self._check()
            if offset < start + length:
                raw = self.files.read_small(ref, self.folder, self.workspace, "blob")
                pending = raw[max(0, offset - start) :]
                while pending:
                    piece, pending = pending[: store.chunk_bytes], pending[store.chunk_bytes :]
                    offset = store.append(blob, offset, piece)
            start += length
            byte_progress(start, blob.size)
        self._check()
        path = store.finalize(blob)
        if fetched_all and self.folder_role == "directory":
            receipt = self.cache / (blob.sha256 + ".upload.json")
            _no_link(receipt)
            if not receipt.exists():
                self._remember(receipt, chunks)
        return path
