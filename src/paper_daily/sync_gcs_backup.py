"""Explicit private GCS publication of an already verified authority snapshot.

No client workspace, provider account, infrastructure, IAM or scheduling changes.
Cloud credentials are resolved only when an operator explicitly calls publish.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re

from paper_daily import sync_authority_backup as backup

PREFIX = "paperfact/authority-backups"
LAYOUT = "paperfact-authority-gcs-v1"
BUCKET = re.compile(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]")
KEY_PREFIX = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*")


class PublicationError(ValueError):
    """A bounded operator-facing failure, without raw cloud responses/credentials."""


class _Reader:
    def __init__(self, stream, live):
        self.stream, self.live = stream, live

    def read(self, size=-1):
        self.live()
        return self.stream.read(size)

    def seek(self, *args):
        self.live()
        return self.stream.seek(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _metadata(snapshot, item):
    result = {
        "paperfact-layout": LAYOUT,
        "sha256": item["sha256"],
        "paperfact-role": "manifest" if item["path"] == backup.MANIFEST else "object",
    }
    if item["path"] == backup.MANIFEST:
        result["paperfact-snapshot"] = snapshot
    return result


def _name(prefix, snapshot, item):
    if item["path"] == backup.MANIFEST:
        return f"{prefix}/snapshots/{snapshot}/{backup.MANIFEST}"
    return f"{prefix}/objects/{item['sha256']}"


def _remote(blob, snapshot, item, crc):
    if (
        blob.size != item["size"]
        or blob.crc32c != crc
        or blob.metadata != _metadata(snapshot, item)
        or blob.content_encoding not in (None, "identity")
    ):
        raise PublicationError("Existing GCS object differs from this verified snapshot")
    try:
        generation = int(blob.generation)
    except (TypeError, ValueError, OverflowError):
        raise PublicationError("GCS object has no verified generation") from None
    if generation <= 0 or isinstance(blob.generation, bool):
        raise PublicationError("GCS object has no verified generation")
    return generation


def _private(bucket, options):
    bucket.reload(**options())
    policy = bucket.iam_configuration
    if (
        policy.public_access_prevention != "enforced"
        or policy.uniform_bucket_level_access_enabled is not True
    ):
        raise PublicationError(
            "Require explicit public-access prevention and uniform bucket access"
        )


def _checksum(path, identity, item, crc_module, live):
    if backup._identity(path) != identity:
        raise PublicationError("Verified backup changed before GCS publication")
    digest, crc, size = hashlib.sha256(), crc_module.Checksum(), 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != identity[:2]:
            raise PublicationError("Verified backup file was replaced")
        while chunk := stream.read(backup.CHUNK):
            live()
            digest.update(chunk)
            crc.update(chunk)
            size += len(chunk)
    if (
        size != item["size"]
        or digest.hexdigest() != item["sha256"]
        or backup._identity(path) != identity
    ):
        raise PublicationError("Verified backup bytes changed before GCS publication")
    return base64.b64encode(crc.digest()).decode("ascii")


def publish(
    snapshot,
    bucket_name,
    *,
    prefix=PREFIX,
    seconds=300,
    cancelled=lambda: False,
    progress=lambda _value: None,
    client=None,
):
    """Publish immutable objects first, completion manifest last; safe exact retry.

    The optional client is a test seam, never an alternate public endpoint option.
    Uses existing operator ADC only; never logs in, provisions or changes policy.
    Cooperative time/cancel checks are not a hard limit on SDK credential/HTTP I/O.
    """
    if (
        not isinstance(bucket_name, str)
        or not BUCKET.fullmatch(bucket_name)
        or not isinstance(prefix, str)
        or len(prefix) > 200
        or not KEY_PREFIX.fullmatch(prefix)
    ):
        raise PublicationError("Use an explicit bucket name and bounded plain object prefix")
    if os.environ.get("STORAGE_EMULATOR_HOST"):
        raise PublicationError("GCS backup publication does not accept an emulator endpoint")
    check = backup._guard(seconds, cancelled)
    root = backup._path(snapshot)
    progress({"stage": "verify"})
    _receipt, manifest, marker_identity, identities = backup._inspect(
        root, seconds=seconds, cancelled=lambda: (check(), False)[1]
    )
    marker = root / backup.MANIFEST
    marker_hash = backup._hash(marker, check)
    with marker.open("rb") as stream:
        marker_bytes = stream.read(backup.MAX_MANIFEST + 1)
    if (
        backup._identity(marker) != marker_identity
        or len(marker_bytes) != marker_hash["size"]
        or hashlib.sha256(marker_bytes).hexdigest() != marker_hash["sha256"]
    ):
        raise PublicationError("Verified backup manifest changed before publication")
    snapshot_hash = marker_hash["sha256"]
    remote_root = f"{prefix}/snapshots/{snapshot_hash}"

    def live():
        check()
        if backup._identity(marker) != marker_identity:
            raise PublicationError("Verified backup manifest changed")

    def all_local():
        live()
        for name, identity in identities.items():
            if backup._identity(root / name) != identity:
                raise PublicationError("Verified backup changed after inspection")

    all_local()
    try:
        import google_crc32c
        from google.api_core.exceptions import GoogleAPIError, NotFound, PreconditionFailed
        from google.auth.exceptions import GoogleAuthError
        from google.cloud import storage
        from google.cloud.storage.exceptions import DataCorruption, InvalidResponse
        from google.cloud.storage.retry import DEFAULT_RETRY
    except ImportError:
        raise PublicationError(
            "Install the locked GCP operator dependencies before uploading"
        ) from None

    def options():
        live()
        return {
            "timeout": (5, min(30, seconds)),
            "retry": DEFAULT_RETRY.with_timeout(min(30, seconds)),
        }

    items = [*manifest["files"], {"path": backup.MANIFEST, **marker_hash}]
    total, completed, verified_bytes, created, reused = len(items), 0, 0, 0, 0
    records = []
    owned_client = client is None
    try:
        if client is None:
            try:
                client = storage.Client()
            except ValueError:
                raise PublicationError(
                    "Configure the approved GCP project and operator ADC first"
                ) from None
        bucket = client.bucket(bucket_name)
        _private(bucket, options)

        def ensure(item, identity):
            path = root / item["path"]
            crc = _checksum(path, identity, item, google_crc32c, live)
            blob = bucket.blob(_name(prefix, snapshot_hash, item), chunk_size=1024**2)
            exists = True
            try:
                blob.reload(**options())
            except NotFound:
                exists = False
            made = False
            if not exists:
                blob.metadata = _metadata(snapshot_hash, item)
                blob.cache_control = "no-store"
                # The completion bytes are frozen in owned memory, not reread
                # from an input path that can change after validation.
                is_marker = item["path"] == backup.MANIFEST
                with io.BytesIO(marker_bytes) if is_marker else path.open("rb") as stream:
                    if not is_marker:
                        opened = os.fstat(stream.fileno())
                        if (opened.st_dev, opened.st_ino) != identity[:2]:
                            raise PublicationError(
                                "Verified backup file was replaced before upload"
                            )
                    try:
                        blob.upload_from_file(
                            _Reader(stream, live),
                            size=item["size"],
                            content_type="application/json"
                            if item["path"] == backup.MANIFEST
                            else "application/octet-stream",
                            if_generation_match=0,
                            checksum="crc32c",
                            crc32c_checksum_value=crc,
                            **options(),
                        )
                        made = True
                    except PreconditionFailed:
                        # A concurrent publisher or a lost successful ACK can win.
                        # Never overwrite it; reload and verify the exact object.
                        pass
                blob.reload(**options())
            if backup._identity(path) != identity:
                raise PublicationError("Verified backup file changed during upload")
            generation = _remote(blob, snapshot_hash, item, crc)
            return crc, generation, made

        for item in items:
            all_local()
            if item["path"] == backup.MANIFEST:
                # Verify the actual earlier generations again before completion.
                _private(bucket, options)
                for previous, crc, generation in records:
                    blob = bucket.blob(_name(prefix, snapshot_hash, previous))
                    blob.reload(if_generation_match=generation, **options())
                    _remote(blob, snapshot_hash, previous, crc)
                all_local()
                progress({"stage": "complete_manifest", "completed": completed, "total": total})
            identity = (
                marker_identity if item["path"] == backup.MANIFEST else identities[item["path"]]
            )
            crc, generation, made = ensure(item, identity)
            records.append((item, crc, generation))
            completed += 1
            verified_bytes += item["size"]
            created += made
            reused += not made
            progress(
                {
                    "stage": "verified_remote",
                    "completed": completed,
                    "total": total,
                    "bytes_verified": verified_bytes,
                }
            )
        all_local()
    except (GoogleAPIError, GoogleAuthError, DataCorruption, InvalidResponse):
        raise PublicationError(
            "GCS publication failed; check approved access/network and retry "
            "the same unchanged snapshot"
        ) from None
    finally:
        if owned_client and client is not None:
            client.close()
    return {
        "state": "published",
        "snapshot_sha256": snapshot_hash,
        "remote_prefix": f"gs://{bucket_name}/{remote_root}",
        "object_prefix": f"gs://{bucket_name}/{prefix}/objects",
        "files_verified": completed,
        "bytes_verified": verified_bytes,
        "files_created": created,
        "files_reused": reused,
    }
