"""Chunked immutable Drive bytes with private retry receipts, separate from research."""

from __future__ import annotations

import hashlib
from pathlib import Path

from paper_daily.drive_sync_files import MAX_INLINE, DriveMissing, decode, identifier
from paper_daily.drive_sync_log import reference
from paper_daily.presentations import _atomic_json
from paper_daily.sync_blobs import BlobManifest, _no_link

MAX_OBJECT = 150 * 1024**2
FORMAT = "paperfact.drive-bytes.v1"


class DriveObjects:
    def __init__(self, files, folder, workspace, cache):
        self.files, self.folder, self.workspace = files, identifier(folder), workspace
        self.cache = Path(cache)
        for entry in (self.cache, *self.cache.parents):
            _no_link(entry)
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, path):
        path = Path(path)
        _no_link(path)
        size = path.stat().st_size
        if not 0 < size <= MAX_OBJECT:
            raise ValueError("Drive object is empty or exceeds the transfer limit")
        full = hashlib.sha256()
        parts = []
        with path.open("rb") as source:
            while raw := source.read(MAX_INLINE):
                self.files.check()
                full.update(raw)
                parts.append((hashlib.sha256(raw).hexdigest(), len(raw)))
        digest = full.hexdigest()
        receipt = self.cache / (digest + ".upload.json")
        _no_link(receipt)
        if receipt.exists():
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
        else:
            chunks = [
                reference(identity, b"placeholder") for identity in self.files.new_ids(len(parts))
            ]
            for ref, (part_hash, length) in zip(chunks, parts, strict=True):
                ref.update(sha256=part_hash, size=length)
            _atomic_json(receipt, dict(workspace=self.workspace, folder=self.folder, chunks=chunks))
        with path.open("rb") as source:
            for ref, (part_hash, length) in zip(chunks, parts, strict=True):
                self.files.check()
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
                    self.files.put_small(ref["id"], self.folder, self.workspace, "blob", raw)
                else:
                    if (
                        existing.get("size") != str(length)
                        or existing.get("sha256Checksum") != part_hash
                    ):
                        raise ValueError("Drive retry object differs from the captured chunk")
            if source.read(1):
                raise ValueError("Source bytes grew during Drive upload")
        return dict(format=FORMAT, sha256=digest, size=size, chunks=chunks)

    def get(self, manifest, store):
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"format", "sha256", "size", "chunks"}
            or manifest["format"] != FORMAT
        ):
            raise ValueError("Unsupported Drive byte manifest")
        blob = BlobManifest(manifest["sha256"], manifest["size"])
        chunks = manifest["chunks"]
        if (
            blob.size > MAX_OBJECT
            or not isinstance(chunks, list)
            or len(chunks) != (blob.size + MAX_INLINE - 1) // MAX_INLINE
        ):
            raise ValueError("Invalid Drive chunk count")
        expected = []
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
            expected.append((ref, length))
        if store.available(blob):
            return store.verified_path(blob)
        status = store.begin(blob)
        offset = status["offset"]
        start = 0
        for ref, length in expected:
            self.files.check()
            if offset < start + length:
                raw = self.files.read_small(ref, self.folder, self.workspace, "blob")
                pending = raw[max(0, offset - start) :]
                while pending:
                    piece, pending = pending[: store.chunk_bytes], pending[store.chunk_bytes :]
                    offset = store.append(blob, offset, piece)
            start += length
        return store.finalize(blob)
