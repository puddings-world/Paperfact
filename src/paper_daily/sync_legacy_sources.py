"""Archive-only adoption of exact legacy source PDFs from explicit trusted roots."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from paper_daily.sync_blobs import BlobManifest, _no_link

TABLE = "research_legacy_source_recovery"
COLUMNS = "sha256 size media_type"
MAX_FILE = 150 * 1024**2
MAX_SCAN_BYTES = 8 * 1024**3
MAX_ENTRIES = 20_000
MAX_FILES = 10_000


def path(value):
    result = Path(value).absolute()
    for part in (result, *result.parents):
        _no_link(part)
    return result


def validate_manifest(row):
    if not isinstance(row, dict) or set(row) != {"sha256", "size", "media_type"}:
        raise ValueError("Invalid archive-only source manifest")
    BlobManifest(row["sha256"], row["size"])
    if type(row["size"]) is not int or not 0 < row["size"] <= MAX_FILE:
        raise ValueError("Invalid archive-only source size")
    if row["media_type"] != "application/pdf":
        raise ValueError("Archive-only source must be PDF")
    return row


def validate_pdf(value):
    import pymupdf

    if not isinstance(value, bytes):
        source = path(value)
        if not 0 < source.stat().st_size <= MAX_FILE:
            raise ValueError("Source PDF exceeds its bound")
        with source.open("rb") as stream:
            value = stream.read(MAX_FILE + 1)
    if not 0 < len(value) <= MAX_FILE:
        raise ValueError("Source PDF exceeds its bound")
    # A failed native filename-open can retain a Windows file handle. Validate
    # bounded bytes so even malformed PDFs leave source/staging files releasable.
    try:
        with pymupdf.open(stream=value, filetype="pdf") as document:
            if document.is_encrypted or document.page_count < 1:
                raise ValueError("Original source PDF is not readable")
    except Exception as exc:
        raise ValueError("Original source PDF is not readable") from exc


class LegacySources:
    """Resolve required digests only; no receipt path or paper URL is ever read."""

    def __init__(self, roots, temporary):
        if len(roots) > 32:
            raise ValueError("Too many trusted PDF roots")
        self.roots = sorted({path(root) for root in roots})
        self.staging = Path(temporary) / "legacy-source-objects"
        self.staging.mkdir()
        self.objects, self.aliases, self.manifests = {}, {}, {}
        self._index = None

    def _scan(self):
        if self._index is not None:
            return
        index, scanned, entries, files = {}, 0, 0, 0
        for root in self.roots:
            if not root.exists():
                continue
            if not root.is_dir():
                raise ValueError("Select a trusted PDF directory")
            for entry in root.rglob("*"):
                path(entry)
                entries += 1
                if entries > MAX_ENTRIES:
                    raise ValueError("Trusted PDF inventory exceeds its entry bound")
                if entry.is_dir():
                    continue
                if not entry.is_file():
                    raise ValueError("Unsupported entry in trusted PDF directory")
                if entry.suffix.lower() != ".pdf":
                    continue
                files += 1
                if files > MAX_FILES or not 0 < entry.stat().st_size <= MAX_FILE:
                    raise ValueError("Trusted PDF inventory exceeds its file bound")
                digest, size = hashlib.sha256(), 0
                with entry.open("rb") as stream:
                    while block := stream.read(1024**2):
                        size += len(block)
                        scanned += len(block)
                        if size > MAX_FILE or scanned > MAX_SCAN_BYTES:
                            raise ValueError("Trusted PDF inventory exceeds its byte bound")
                        digest.update(block)
                index.setdefault(digest.hexdigest(), []).append((entry, size))
        self._index = index

    def find(self, digest, expected_size=None):
        """Stage a matching required PDF, or return None if no trusted file matches."""
        BlobManifest(digest, expected_size or 1)
        if digest in self.manifests:
            row = self.manifests[digest]
            if expected_size is not None and row["size"] != expected_size:
                raise ValueError("Original source size differs from retained manifest")
            return row
        self._scan()
        matches = self._index.get(digest, [])
        if not matches:
            return None
        original, expected = matches[0]
        if expected_size is not None and expected != expected_size:
            raise ValueError("Original source size differs from retained manifest")
        destination = self.staging / digest
        try:
            measured, size = hashlib.sha256(), 0
            with path(original).open("rb") as incoming, destination.open("xb") as output:
                while block := incoming.read(1024**2):
                    size += len(block)
                    if size > expected or size > MAX_FILE:
                        raise ValueError("Original source changed while staging")
                    measured.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            if size != expected or measured.hexdigest() != digest:
                raise ValueError("Original source changed while staging")
            validate_pdf(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        row = {"sha256": digest, "size": expected, "media_type": "application/pdf"}
        validate_manifest(row)
        self.manifests[digest] = row
        self.objects[digest] = destination
        for matching, size in matches:
            if size != expected:
                raise ValueError("One original source hash has inconsistent sizes")
            self.aliases[matching] = (digest, size)
        return row

    def require(self, digest, expected_size=None):
        row = self.find(digest, expected_size)
        if row is None:
            raise ValueError("Original source PDF is missing or changed in the trusted PDF roots")
        return row
