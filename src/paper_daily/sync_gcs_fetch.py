"""Explicit bounded retrieval of an immutable GCS authority backup, never restore."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
from functools import partial

from paper_daily import sync_authority_backup as backup
from paper_daily import sync_gcs_backup as publication
from paper_daily.sync_blobs import BlobManifest

MAX_BYTES = 16 * 1024**3
PENDING = ".manifest.pending"


class RetrievalError(ValueError):
    """Bounded operator failure, without cloud response contents."""


class _Sink:
    def __init__(self, target, limit, check):
        self.target, self.limit, self.check = target, limit, check
        self.size = 0

    def write(self, data):
        self.check()
        if self.size + len(data) > self.limit:
            raise RetrievalError("Downloaded range exceeded its exact byte budget")
        count = self.target.write(data)
        self.size += count
        return count


def _entries(raw, max_bytes):
    value = backup._decode(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"format", "policy", "files"}
        or value["format"] != backup.FORMAT
        or value["policy"] != backup.POLICY
        or not isinstance(value["files"], list)
        or not 1 <= len(value["files"]) <= backup.MAX_FILES + 1
    ):
        raise RetrievalError("Unsupported bounded authority manifest")
    names, total = set(), 0
    for item in value["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise RetrievalError("Invalid backup entry")
        name = item["path"]
        if (
            not isinstance(name, str)
            or name in names
            or not (name == "authority.sqlite" or backup.OBJECT.fullmatch(name))
        ):
            raise RetrievalError("Invalid or duplicate backup entry path")
        BlobManifest(item["sha256"], item["size"])
        names.add(name)
        total += item["size"]
        if total > max_bytes:
            raise RetrievalError("Declared backup exceeds the approved byte budget")
    if "authority.sqlite" not in names:
        raise RetrievalError("Authority snapshot is missing")
    return value["files"]


def fetch(
    bucket_name,
    snapshot_sha256,
    output,
    *,
    prefix=publication.PREFIX,
    seconds=300,
    max_bytes=MAX_BYTES,
    cancelled=lambda: False,
    progress=lambda _value: None,
    client=None,
):
    """Download to a new private directory; verify closure before completion.

    Uses explicit operator ADC only. Does not enroll a device, restore a service,
    delete remote objects, resume partial outputs or touch desktop research.
    SDK calls have bounded request/retry options; cancellation is cooperative.
    """
    if (
        not isinstance(bucket_name, str)
        or not publication.BUCKET.fullmatch(bucket_name)
        or not isinstance(prefix, str)
        or len(prefix) > 200
        or not publication.KEY_PREFIX.fullmatch(prefix)
        or not isinstance(snapshot_sha256, str)
        or not re.fullmatch("[0-9a-f]{64}", snapshot_sha256)
        or type(max_bytes) is not int
        or not 0 < max_bytes <= MAX_BYTES
    ):
        raise RetrievalError("Use a valid explicit bucket, prefix, snapshot digest and byte budget")
    if os.environ.get("STORAGE_EMULATOR_HOST"):
        raise RetrievalError("GCS retrieval does not accept an emulator endpoint")
    check = backup._guard(seconds, cancelled)
    check()
    root = backup._path(output)
    if root.exists():
        raise RetrievalError("Choose a new unused backup output directory")
    if not root.parent.is_dir():
        raise RetrievalError("Create the private backup parent directory first")
    try:
        import google_crc32c
        from google.api_core.exceptions import GoogleAPIError
        from google.auth.exceptions import GoogleAuthError
        from google.cloud import storage
        from google.cloud.storage.exceptions import DataCorruption
        from google.cloud.storage.retry import DEFAULT_RETRY
        from google.resumable_media.common import InvalidResponse
    except ImportError:
        raise RetrievalError(
            "Install the locked GCP operator dependencies before retrieval"
        ) from None

    def options():
        check()
        return {
            "timeout": (5, min(30, seconds)),
            "retry": DEFAULT_RETRY.with_timeout(min(30, seconds)),
        }

    def describe(item):
        blob = bucket.blob(publication._name(prefix, snapshot_sha256, item))
        blob.reload(**options())
        # SHA metadata is not a byte proof; download() independently hashes bytes.
        generation = publication._remote(blob, snapshot_sha256, item, blob.crc32c)
        if not isinstance(blob.crc32c, str) or not re.fullmatch(r"[A-Za-z0-9+/]{6}==", blob.crc32c):
            raise RetrievalError("Remote object has no bounded CRC32C checksum")
        return blob, generation, blob.crc32c

    def download(blob, generation, expected, target, size, digest):
        sha, crc = hashlib.sha256(), google_crc32c.Checksum()
        for start in range(0, size, backup.CHUNK):
            options_value = options()
            length = min(backup.CHUNK, size - start)
            # Each request is bounded even if a server ignores Range. Whole-object
            # SHA/CRC verification is independent of SDK ranged-checksum support.
            block = io.BytesIO()
            sink = _Sink(block, length, check)
            blob.download_to_file(
                sink,
                start=start,
                end=start + length - 1,
                raw_download=True,
                if_generation_match=generation,
                checksum=None,
                **options_value,
            )
            if sink.size != length:
                raise RetrievalError("Downloaded range was incomplete")
            data = block.getvalue()
            sha.update(data)
            crc.update(data)
            check()
            target.write(data)
        if sha.hexdigest() != digest or base64.b64encode(crc.digest()).decode("ascii") != expected:
            raise RetrievalError("Downloaded bytes failed SHA-256 or CRC32C verification")
        blob.reload(if_generation_match=generation, **options())

    owned = client is None
    try:
        if client is None:
            try:
                client = storage.Client()
            except ValueError:
                raise RetrievalError("Configure approved operator ADC/project first") from None
        bucket = client.bucket(bucket_name)
        publication._private(bucket, options)
        marker_item = {"path": backup.MANIFEST, "sha256": snapshot_sha256}
        marker = bucket.blob(publication._name(prefix, snapshot_sha256, marker_item))
        marker.reload(**options())
        if type(marker.size) is not int or not 0 < marker.size <= backup.MAX_MANIFEST:
            raise RetrievalError("Remote completion manifest exceeds its byte budget")
        marker_item["size"] = marker.size
        marker, marker_generation, marker_crc = describe(marker_item)
        memory = io.BytesIO()
        download(
            marker, marker_generation, marker_crc, memory, marker_item["size"], snapshot_sha256
        )
        raw = memory.getvalue()
        entries = _entries(raw, max_bytes)
        check()
        root.mkdir(mode=0o700, exist_ok=False)
        root_identity = root.stat().st_dev, root.stat().st_ino

        def live():
            check()
            current = backup._path(root).stat()
            if (current.st_dev, current.st_ino) != root_identity:
                raise RetrievalError("Backup output directory was replaced")

        records, completed, byte_count = [], 0, 0
        for item in entries:
            live()
            blob, generation, crc = describe(item)
            path = backup._path(root / item["path"])
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup._write(
                path,
                partial(download, blob, generation, crc, size=item["size"], digest=item["sha256"]),
            )
            records.append((blob, generation))
            completed += 1
            byte_count += item["size"]
            progress(
                {
                    "stage": "downloaded",
                    "completed": completed,
                    "total": len(entries),
                    "bytes_verified": byte_count,
                }
            )
        live()
        backup._write(root / PENDING, lambda stream: stream.write(raw))
        progress({"stage": "verify_authority"})
        _receipt, _value, identity, identities = backup._inspect(
            root, seconds=seconds, cancelled=lambda: (live(), False)[1], manifest_name=PENDING
        )
        publication._private(bucket, options)
        for blob, generation in [(marker, marker_generation), *records]:
            blob.reload(if_generation_match=generation, **options())
        live()
        if backup._identity(root / PENDING) != identity or any(
            backup._identity(root / name) != observed for name, observed in identities.items()
        ):
            raise RetrievalError("Downloaded backup changed after verification")
        for directory, _folders, _files in os.walk(root, topdown=False):
            backup._sync_directory(backup._path(directory))
        live()
        (root / PENDING).rename(root / backup.MANIFEST)
        backup._sync_directory(root)
        backup._sync_directory(root.parent)
    except (GoogleAPIError, GoogleAuthError, DataCorruption, InvalidResponse):
        raise RetrievalError(
            "GCS retrieval failed; verify access/network and retry into a new directory"
        ) from None
    finally:
        if owned and client is not None:
            client.close()
    return {
        "state": "downloaded_verified",
        "snapshot_sha256": snapshot_sha256,
        "files": completed,
        "bytes": byte_count,
        "restored": False,
    }
