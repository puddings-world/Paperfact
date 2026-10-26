# Local attachment transfer foundation

Status: v0.5.0 local primitive, not complete research attachment sync.

`paper_daily.sync_blobs` is independent of app configuration, AI accounts, research
databases and network transport. The caller supplies a private store directory.
The store owns that directory; do not point it at an existing PDF/cache directory.

## API

```python
from pathlib import Path
from paper_daily.sync_blobs import BlobManifest, BlobStore

store = BlobStore(Path("isolated-workspace/sync-blobs"))
item = BlobManifest(sha256=expected_sha256, size=expected_bytes)
state = store.begin(item)             # {offset: int, complete: bool}
offset = store.append(item, state["offset"], received_chunk)
path = store.finalize(item)           # only after full size and SHA-256 verification
```

- `begin(manifest)` reserves the whole declared size and resumes existing bytes.
- `append(manifest, offset, bytes)` accepts a bounded chunk. Repeated or overlapping
  retries must match saved bytes; only a missing suffix is appended. Gaps fail.
- `finalize(manifest)` verifies size/hash and atomically publishes the staged file.
  Repeated finalization is safe. Failure never returns a partial object as complete.
- `verified_path(manifest)` hashes published bytes before returning a local path;
  absence or corruption raises. `available(manifest)` returns false for either.
- `discard_partial(manifest)` cancels unfinished work and releases its reservation.
  It cannot remove a finalized object. Cancellation is idempotent.
- `usage()` reports reserved bytes, object count and the configured quota.

Defaults: 4 GiB reserved-byte quota, 1 GiB per attachment, 1 MiB chunks. These are
prototype limits configurable by the caller; no new limit is imposed on existing
Paperfact research. Chunks cannot exceed 16 MiB. Empty attachments are supported.

## Persistence and failure behavior

- Lowercase SHA-256 identities determine paths; remote filenames are never used.
- SQLite transactions serialize reservations and mutations across local processes.
  A digest has one declared size and one reservation, including concurrent retries.
- Staged bytes are fsynced before acknowledging an offset. Their physical length is
  the restart offset; a partially written chunk can be retried with matching overlap.
- Publication uses an atomic rename in the same store. If interruption happens
  after rename but before metadata commit, `begin()` verifies and recovers the object.
- Wrong hashes remain staged and unavailable. Explicitly cancel and retry the
  transfer; never overwrite a finalized file to hide corruption.
- Missing/corrupt finalized content is reported unavailable. Repair, eviction and
  verified re-download transitions need an explicit higher-level recovery operation.
- Root ancestors, store directories, object entries and metadata files reject
  symlinks/reparse points. The directory must remain private to the application;
  these checks are not a sandbox against a hostile local process racing path changes.

## Integration work still required

The transport must authenticate the owner and authorize each manifest independently
of possession of its hash. Blob identity does not grant workspace access. The
research manifest must bind media type, owner/entity revision, PDF version and
source anchors. Byte correctness alone does not decide which PDF belongs to a paper.

Still required: authorized upload/download endpoints, reference/history retention,
repair and garbage collection, offline pinning/quota UX, selected-list dependency
closure, deck manifest publication, and UI progress. Cache eviction is not deletion
of research. A missing asset must not make an incomplete deck appear fully offline.

`tests/test_sync_blobs.py` uses synthetic files for restart, retry, concurrency,
quota, corruption, cancellation, path validation and publication failure. Reparse
point tests simulate filesystem metadata portably. These are not live cloud,
power-loss, hostile-filesystem or cross-device network checks. Full-suite validation
is recorded by the parent implementation checkpoint before commit.
