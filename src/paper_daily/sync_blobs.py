"""Opt-in, local immutable blobs with resumable writes; no network or app state.

The store owns its directory. It rejects symlinks/reparse points but is not a
sandbox against a hostile process replacing filesystem entries concurrently.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path


class BlobError(ValueError):
    """Invalid manifest, damaged content or inconsistent transfer state."""


class BlobSourceMismatch(BlobError):
    """The explicitly supplied file does not match the requested immutable bytes."""


class BlobQuotaError(BlobError):
    """Declared transfer sizes would exceed this store's byte budget."""


@dataclass(frozen=True)
class BlobManifest:
    sha256: str
    size: int

    def __post_init__(self):
        if not isinstance(self.sha256, str) or not re.fullmatch("[0-9a-f]{64}", self.sha256):
            raise BlobError("Expected a lowercase SHA-256 digest")
        if type(self.size) is not int or self.size < 0:
            raise BlobError("Expected a nonnegative byte size")


def system_link(link, folder, *, posix=os.name == "posix") -> bool:
    """A root-owned link in a root-owned folder nobody else may write, such as macOS
    /var -> private/var under every temporary folder. Only an administrator can
    redirect it, so it is part of the system layout, not a link into the store."""
    return (
        posix
        and stat.S_ISLNK(link.st_mode)
        and getattr(link, "st_uid", None) == 0
        and getattr(folder, "st_uid", None) == 0
        and not folder.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def _no_link(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) and system_link(info, path.parent.lstat()):
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        raise BlobError("Symlinks and reparse points are not allowed in the blob store")


class BlobStore:
    """Serialized writes and reservations for one explicitly chosen private directory.

    Quota reserves the entire declared size at begin(), not just received bytes.
    Acknowledged offsets are fsynced. Metadata transactions serialize writers;
    after interruption the staged file's actual length is the resume offset.
    """

    def __init__(
        self,
        root: Path,
        *,
        quota_bytes: int = 4 * 1024**3,
        max_blob_bytes: int = 1024**3,
        chunk_bytes: int = 1024**2,
    ):
        for value in (quota_bytes, max_blob_bytes, chunk_bytes):
            if type(value) is not int or value <= 0:
                raise BlobError("Store limits must be positive integers")
        if chunk_bytes > 16 * 1024**2:
            raise BlobError("A chunk cannot exceed 16 MiB")
        self.root = Path(root).absolute()
        self.quota_bytes = quota_bytes
        self.max_blob_bytes = max_blob_bytes
        self.chunk_bytes = chunk_bytes
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("objects", "partial"):
            path = self.root / name
            _no_link(path)
            path.mkdir(exist_ok=True)
        with self._transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS blobs (digest TEXT PRIMARY KEY, "
                "size INTEGER NOT NULL, complete INTEGER NOT NULL DEFAULT 0)"
            )

    def _check_root(self):
        for path in reversed((self.root, *self.root.parents)):
            _no_link(path)

    def _path(self, manifest: BlobManifest, *, partial=False) -> Path:
        if not isinstance(manifest, BlobManifest):
            raise BlobError("Expected a BlobManifest")
        if manifest.size > self.max_blob_bytes:
            raise BlobQuotaError("Attachment exceeds the per-file limit")
        self._check_root()
        folder = self.root / ("partial" if partial else "objects")
        _no_link(folder)
        path = folder / manifest.sha256
        _no_link(path)
        if path.exists() and not path.is_file():
            raise BlobError("Blob entry must be a regular file")
        return path

    @contextmanager
    def _transaction(self):
        self._check_root()
        path = self.root / "index.sqlite"
        for suffix in ("", "-journal", "-wal", "-shm"):
            _no_link(Path(str(path) + suffix))
        conn = sqlite3.connect(path, timeout=5)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row(conn, manifest):
        row = conn.execute(
            "SELECT size,complete FROM blobs WHERE digest=?", (manifest.sha256,)
        ).fetchone()
        if row and row[0] != manifest.size:
            raise BlobError("The digest was already registered with a different size")
        return row

    @staticmethod
    def _verify(path, manifest, *, check=lambda: None):
        if not path.exists():
            raise FileNotFoundError("Attachment bytes are unavailable")
        if path.stat().st_size != manifest.size:
            raise BlobError("Attachment byte size does not match its manifest")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                check()
                chunk = stream.read(1024**2)
                if not chunk:
                    break
                digest.update(chunk)
        check()
        if digest.hexdigest() != manifest.sha256:
            raise BlobError("Attachment hash does not match its manifest")

    def begin(self, manifest: BlobManifest, *, restore_missing=False, check=lambda: None) -> dict:
        """Reserve one object or resume it; identical calls share one reservation."""
        if type(restore_missing) is not bool:
            raise BlobError("Missing-object restoration must be explicit")
        if not callable(check):
            raise BlobError("Expected a cancellation/lifetime check")
        final, part = self._path(manifest), self._path(manifest, partial=True)
        with self._transaction() as conn:
            check()
            row = self._row(conn, manifest)
            if not row:
                reserved = conn.execute("SELECT COALESCE(SUM(size),0) FROM blobs").fetchone()[0]
                if reserved + manifest.size > self.quota_bytes:
                    raise BlobQuotaError("Attachment store quota would be exceeded")
                conn.execute(
                    "INSERT INTO blobs(digest,size) VALUES(?,?)", (manifest.sha256, manifest.size)
                )
            if final.exists():
                self._verify(final, manifest, check=check)
                conn.execute("UPDATE blobs SET complete=1 WHERE digest=?", (manifest.sha256,))
                return {"offset": manifest.size, "complete": True}
            if row and row[1]:
                if not restore_missing:
                    raise BlobError("A finalized attachment is missing; restore it explicitly")
                conn.execute("UPDATE blobs SET complete=0 WHERE digest=?", (manifest.sha256,))
            if not part.exists():
                with part.open("xb") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
            offset = part.stat().st_size
            if offset > manifest.size:
                raise BlobError("Staged content exceeds its declared size")
            return {"offset": offset, "complete": False}

    def append(self, manifest: BlobManifest, offset: int, data: bytes) -> int:
        """Append or retry matching bytes, returning the durable next offset.

        A retry may overlap an interrupted write. Existing overlap must match;
        only the missing suffix is appended. Changed retries never overwrite bytes.
        """
        if type(offset) is not int or offset < 0:
            raise BlobError("Expected a nonnegative offset")
        if not isinstance(data, bytes) or not 0 < len(data) <= self.chunk_bytes:
            raise BlobError("Expected a nonempty, bounded byte chunk")
        final, part = self._path(manifest), self._path(manifest, partial=True)
        if offset + len(data) > manifest.size:
            raise BlobError("Chunk exceeds the attachment size")
        with self._transaction() as conn:
            row = self._row(conn, manifest)
            if row is None:
                raise BlobError("Begin the transfer before appending bytes")
            if final.exists():
                self._verify(final, manifest)
                with final.open("rb") as stream:
                    stream.seek(offset)
                    if stream.read(len(data)) != data:
                        raise BlobError("Retry differs from finalized content")
                return manifest.size
            if row[1] or not part.exists():
                raise BlobError("Transfer bytes are missing")
            current = part.stat().st_size
            if current > manifest.size:
                raise BlobError("Staged content exceeds its declared size")
            if offset > current:
                raise BlobError("Chunk has a gap; resume at the reported offset")
            overlap = min(len(data), current - offset)
            with part.open("r+b") as stream:
                stream.seek(offset)
                if stream.read(overlap) != data[:overlap]:
                    raise BlobError("Retry differs from staged content")
                if overlap < len(data):
                    stream.seek(current)
                    stream.write(data[overlap:])
                stream.flush()
                os.fsync(stream.fileno())
            return max(current, offset + len(data))

    def finalize(self, manifest: BlobManifest) -> Path:
        """Verify full bytes before atomic publication; repeated finalization is safe."""
        final, part = self._path(manifest), self._path(manifest, partial=True)
        with self._transaction() as conn:
            if self._row(conn, manifest) is None:
                raise BlobError("Begin the transfer before finalizing")
            if final.exists():
                self._verify(final, manifest)
            else:
                self._verify(part, manifest)
                os.replace(part, final)
            conn.execute("UPDATE blobs SET complete=1 WHERE digest=?", (manifest.sha256,))
        return final

    def import_file(self, manifest: BlobManifest, source: Path, *, check=lambda: None) -> Path:
        """Explicitly supply exact bytes through bounded, indexed resumable staging.

        Final objects are never overwritten. Only a verified full local source
        authorizes restarting unfinished staging; interrupted prefixes retain
        their reservation. This neither publishes research nor activates a reader.
        """
        if not callable(check):
            raise BlobError("Expected a cancellation/lifetime check")
        final = self._path(manifest)
        incoming = Path(source)
        check()
        if not incoming.is_file() or incoming.stat().st_size != manifest.size:
            raise BlobSourceMismatch("Selected file size differs from the known original")
        with self._transaction() as conn:
            check()
            if self._row(conn, manifest) is None:
                reserved = conn.execute("SELECT COALESCE(SUM(size),0) FROM blobs").fetchone()[0]
                if reserved + manifest.size > self.quota_bytes:
                    raise BlobQuotaError("Attachment store quota would be exceeded")
        try:
            self._verify(incoming, manifest, check=check)
        except BlobError as exc:
            raise BlobSourceMismatch("Selected file does not match the known original") from exc
        check()
        # Commit the reservation before writing. A killed process leaves a known,
        # bounded partial, not an unindexed per-attempt temporary file.
        state = self.begin(manifest, restore_missing=True, check=check)
        if state["complete"]:
            check()
            return final
        with self._transaction() as conn:
            check()
            final = self._path(manifest)
            if self._row(conn, manifest) is None:
                raise BlobError("Local supply reservation changed; retry")
            part = self._path(manifest, partial=True)
            if final.exists():
                self._verify(final, manifest, check=check)
            else:
                if part.exists() and incoming.samefile(part):
                    raise BlobError("Supply an external file, not the active partial itself")
                # Unlink only the owned staging name, never truncate an inode
                # that might also be linked to the caller's external original.
                with incoming.open("rb") as stream:
                    part.unlink(missing_ok=True)
                    with part.open("xb") as output:
                        total = 0
                        while chunk := stream.read(1024**2):
                            check()
                            total += len(chunk)
                            if total > manifest.size:
                                raise BlobSourceMismatch("Selected file changed during supply")
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                try:
                    self._verify(part, manifest, check=check)
                except BlobError as exc:
                    raise BlobSourceMismatch("Selected file changed during supply") from exc
                check()
                try:
                    os.link(part, final)
                except FileExistsError:
                    self._verify(final, manifest, check=check)
            conn.execute("UPDATE blobs SET complete=1 WHERE digest=?", (manifest.sha256,))
            # A locked private partial can remain; verified final bytes are usable.
            with suppress(OSError):
                part.unlink(missing_ok=True)
        return final

    def verified_path(self, manifest: BlobManifest) -> Path:
        """Return only bytes matching the manifest; never return a partial object."""
        final = self._path(manifest)
        self._verify(final, manifest)
        return final

    def available(self, manifest: BlobManifest) -> bool:
        try:
            self.verified_path(manifest)
        except (BlobError, FileNotFoundError):
            return False
        return True

    def discard_partial(self, manifest: BlobManifest) -> None:
        """Cancel an unfinished transfer and release its reservation; keep final objects."""
        final, part = self._path(manifest), self._path(manifest, partial=True)
        with self._transaction() as conn:
            row = self._row(conn, manifest)
            if final.exists() or (row and row[1]):
                raise BlobError("A finalized attachment cannot be discarded as a partial transfer")
            part.unlink(missing_ok=True)
            conn.execute("DELETE FROM blobs WHERE digest=?", (manifest.sha256,))

    def usage(self) -> dict:
        with self._transaction() as conn:
            reserved, count = conn.execute(
                "SELECT COALESCE(SUM(size),0),COUNT(*) FROM blobs"
            ).fetchone()
        return {"reserved_bytes": reserved, "objects": count, "quota_bytes": self.quota_bytes}
