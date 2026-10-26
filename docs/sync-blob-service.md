# Authenticated reference attachment service

Status: isolated local authority implementation for ADR 0004 and ADR 0006. Storage requires an
explicit directory; this is not public enrollment, production hosting, or automatic
capture of existing research files.

```python
service = ReferenceService(
    database_path,
    blob_root=private_storage_directory,
    blob_quota_bytes=4 * 1024**3,
    blob_max_bytes=150 * 1024**2,
    blob_max_uploads=16,
)
```

Omitting `blob_root` keeps attachment storage disabled. Limits are administrative
configuration and must be consistent across instances sharing this authority.
They bound each workspace's full committed/reserved bytes, each object, and open
upload sessions. Decoded append/read chunks are capped at 256 KiB. The generic blob
store supports zero-byte objects; primary-PDF manifests require positive size.

## Native API

Before transmitting bytes, the coordinator calls `session_info(token)` and compares
its exact `{workspace_id, device_id}` response to the immutable local binding. A
token is bound to one workspace/device for its lifetime; local session generation
changes require a fresh handshake. This read-only method reauthenticates and creates
no namespaces, uploads, or files. Checking only a token's presence is insufficient:
an otherwise valid token for another workspace must never receive local PDF bytes.
Every later blob request still authenticates independently, so the handshake does
not bypass revocation. The HTTP route is `POST /v1/session/info` with an empty object.

Every method authenticates the current token independently. A manifest is exactly
`{"sha256": <lowercase 64-character digest>, "size": <nonnegative integer>}`.

| Method | Result |
| --- | --- |
| `blob_begin(token, manifest)` | `upload_id`, `sha256`, `size`, durable `offset`, `complete` |
| `blob_append(token, upload_id, offset, data: bytes)` | `{"offset": <durable next offset>}` |
| `blob_commit(token, upload_id)` | `sha256`, `size`, `complete: true` |
| `blob_cancel(token, upload_id)` | `{"cancelled": true}` |
| `blob_read(token, sha256, size, offset, limit=256*1024)` | Bounded bytes; empty at exact EOF |

Begin is also resume/status. Repeated begin on an open upload by its owning device
returns the same opaque session ID. A committed object returns `upload_id: null`,
full offset, and `complete: true`. Upload IDs are identifiers, never authorization
capabilities. A different device cannot take over an open session; other authorized
devices in the workspace can read a committed object.

Matching overlapping chunk retries append only missing bytes. Gaps, changed retry
bytes, invalid offsets and oversized chunks cannot overwrite content. Commit
verifies the complete size and SHA256 before publishing. Repeating commit or a
matching append retry after commit is safe. Cancel is idempotent for unfinished
uploads and releases their reservation; cancelled session IDs cannot resume writes.
Committed attachments cannot be cancelled as partial uploads.

## Isolation, storage, and crash repair

`sync_blob_service.py` is a mixin of `ReferenceService`. Authority tables hold:

- `sync_blob_namespaces`: workspace to server-generated opaque directory ID.
- `sync_workspace_blobs`: workspace/digest, declared size, reserved/committed state.
- `sync_blob_uploads`: opaque session ID, workspace/device, manifest, and lifecycle.
- `sync_blob_integrity`: verified manifest, encoding version, fixed block size/count,
  and server-owned filesystem identity snapshot.
- `sync_blob_blocks`: workspace/digest-scoped contiguous block indexes and SHA256 values.

There is one active session per workspace/digest. Each workspace owns a separate
BlobStore namespace, including its physical objects and reservations. Knowing a
digest from another workspace grants neither read permission nor a deduplication
hit: beginning the same content there starts its own upload. Caller paths, URLs,
filenames, tokens, and account credentials are not stored in these records.

When both locks are needed, acquisition remains authority first, BlobStore second.
Explicit commit finalization/full verification runs outside an authority transaction;
its BlobStore lock is released before the authority publication transaction begins.
The publication reauthenticates and rechecks the upload/file binding. Namespace registration
is durably committed before touching files. Authority SQLite and the BlobStore index
and files are separate transactions: physical verification/finalization occurs
before authority ownership commit. If interrupted between them, verified but
unowned bytes cannot be read or referenced by a new paper manifest. The same device's
authenticated begin/commit retry verifies those bytes and repairs ownership. A
failed reservation may leave private underlying reserved bytes; its namespace stays
recorded and its BlobStore quota still counts them. This is recovery, not a claim of
cross-database/filesystem atomicity.

All methods, including exact retries and reads, reauthenticate. Revocation blocks
subsequent calls; it cannot retract bytes already returned by a completed call.
Workspace authorization precedes object access, and every read requires committed
ownership matching both hash and size. Read results expose no server filesystem path.

## Bounded read integrity

Explicit commit computes fixed 256 KiB block digests and the complete file hash from
the same opened file. It checks the declared whole-file SHA256/size and stable
opened-file identity before atomically publishing the complete digest set with
workspace ownership. A failed digest/ownership transaction leaves no partial index
authorized for reads. Authenticated begin/commit retries rebuild the index from
verified bytes; client-supplied block lists never establish trust.

Every indexed read authenticates and checks committed ownership, validates the
complete bounded digest-set shape, rejects symlinks/reparse points, and matches the
opened handle to the verified file identity. It reads and hashes the one or two
blocks covering the requested range, checking their exact lengths before returning
the requested slice. A 150 MiB PDF has 600 records; one range reads at most 512 KiB
of object bytes. EOF reads inspect no content. Generic empty objects have a valid
zero-block header. The byte bounds are measured by fixture instrumentation, not
wall-clock estimates.

A valid returned block does not claim every other block is currently undamaged.
Corruption in a requested block fails that request, including corruption preserving
size/mtime; the receiver still verifies the final full-file hash and PDF readability.
New document metadata puts retain full-file availability verification.

Legacy committed objects with neither header nor block rows receive one lazy full
verification/backfill before their first range read. Full commit/backfill scans run
outside authority write transactions, with at most two scans active per process.
Publication reauthenticates after the scan, so revocation during verification cannot
publish ownership/index data or return bytes. Partial, extra, malformed or mismatched
existing metadata fails closed rather than silently becoming a trusted backfill.
The first legacy upgrade is proportional to file size; subsequent object-byte work
is bounded by the requested covered blocks, plus bounded index validation.

## Document prerequisite and independent availability

After exact operation-receipt retry lookup, a new `paper_document` put must resolve
to a committed owned blob with verified bytes. An unavailable prerequisite raises
`BlobUnavailableError` without allocating an event. Normal revision/graph rules
then decide accepted versus conflict. Exact existing operation receipts still replay
unchanged even if bytes later become unavailable; history is not rewritten.

Manifest conflict or deletion does not collect bytes referenced by retained history.
The authority verifies byte integrity, not PDF readability; receiving-client PDF
validation and desired-versus-applied binding are separate responsibilities. Missing
local bytes must not prevent the receiving client from durably advancing its metadata
cursor or recording the manifest.

Failures use `BlobDisabledError` for absent configuration, `BlobUnavailableError`
for missing/uncommitted manifest prerequisites or lost/corrupt owned bytes,
`BlobQuotaError` for storage/session limits, and `PermissionError` for unauthorized
workspace/session access. Intrinsically malformed requests use `ValueError`/`BlobError`.
Transport maps these to fixed errors without raw paths, content, URLs, or tokens.

## Verification and remaining gates

`tests/test_sync_blob_service.py` uses isolated bytes and authorities. It covers
known-hash isolation, session takeover, revocation in every phase, concurrency,
quota reservation, restart/overlap retry, finalization-before-ownership interruption,
manifest prerequisites, corruption/loss, and history retention. Existing
`test_sync_blobs.py` retains the local file-integrity primitives.
`test_sync_blob_integrity.py` adds instrumented read bounds, exact/unaligned/EOF
ranges, malformed indexes, legacy upgrade, opened-handle/link checks, corruption,
revocation during verification, atomic recovery, isolation, and actual loopback HTTP.

Automatic lease expiry, orphan reconciliation, committed-blob garbage collection,
trusted repair of lost/corrupt previously committed authority objects, global server
disk admission, and production rate/concurrency limits remain explicit later gates.
Large-file wall-clock performance and production concurrency/disk admission remain
unbenchmarked. Indexed reads avoid the former repeated full-file scans; explicit
commits and first legacy upgrades still perform bounded complete verification.
No stat-only cache or persistent unverified availability flag grants byte access.
The store does not sandbox a hostile process replacing its owned filesystem entries.
No real-account, real-research, cloud, deployment, or cross-device test is claimed.


## Research-file publication

`research_file` puts require a complete owned body/assets closure. The service
authenticates the operation's workspace/device and checks retry receipts first.
At most two closure verifications run concurrently; each validates the closed deck
format and full size/SHA256 of at most 8 MiB body plus 64 MiB assets outside the
authority write transaction. No caller path, URL or hash alone grants access.

The publication transaction authenticates again, handles a concurrent exact retry,
and rechecks committed workspace ownership, namespace path and verified file
identity before allocating an event. Revocation or replacement during validation
prevents publication. Existing exact receipts remain stable even when bytes later
need repair. Primary PDF manifest checks remain unchanged. This assumes the owned
immutable storage boundary; it is not a defense against a privileged process
concurrently modifying service files while restoring their complete OS identity.
