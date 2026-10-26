# ADR 0006: Bound attachment-read verification work

Status: planned, not implemented or benchmarked. Follow the owned-blob contract in
[ADR 0004](0004-owned-document-transfer.md); keep per-request authorization.

## Problem

The conservative reference service hashes the entire object before every 256 KiB
read. A 150 MiB PDF requires about 600 reads and 90 GiB of repeated verification.
That is a delivery blocker for larger documents even when correctness tests pass.
A stat-only cache would miss corruption that preserves size and timestamps; do not
silently exchange the current integrity contract for that assumption.

## Proposed decision

- During explicit commit, verify the complete file against its declared SHA256 and
  size while computing fixed 256 KiB block digests. The maximum primary PDF has
  600 block records; zero-length generic blobs have no records.
- Persist the digest set, its version/block size and complete-file identity in the
  same authority transaction that grants workspace ownership. Only server-computed
  digests from a fully verified object are valid. Client-supplied block lists never
  establish ownership or verification.
- Keep the physical-file/authority commit boundary explicit. A crash after physical
  finalization but before ownership leaves private bytes; authenticated retry
  recomputes the digests and completes ownership. Partial digest rows cannot grant
  read access. Exact operation receipts remain immutable.
- A bounded read covers at most two adjacent blocks. Authenticate workspace access,
  validate the owned manifest and complete digest-set shape, reject links/invalid
  paths, read each covered block with its expected exact length, and compare its
  SHA256 before returning the requested slice. Validate the opened file's size and
  identity; do not trust a path check alone. Handle EOF without unbounded reads.
- The receiving client still verifies the final full-file hash and PDF readability.
  A correct block does not claim every other block is currently undamaged. Corruption
  in any requested block fails that request; incomplete/invalid final files cannot bind.
- Metadata puts may retain the current full-file availability check because they
  are infrequent. Do not weaken namespace authorization or receipt semantics to
  optimize the download path.

## Compatibility and bounded work

The initial private service may already own objects without block records. Choose
an explicit lazy-upgrade path that fully verifies and records the digests once, or
require a trusted maintenance step. Never manufacture digests from unchecked data.
The first upgrade can be expensive; publish that state honestly and bound concurrent
verification. Subsequent chunk reads must do O(chunk size) work, not O(file size).

Keep a consistent authority-before-BlobStore lock order. Avoid opening a second
authority write transaction from a helper that already owns one. Revocation must
remain effective for subsequent requests, and file I/O must not create an unbounded
global write-lock hold. No token, local path or private filename is persisted in
the wire digest metadata. Retention/GC and trusted finalized-object repair remain
independent decisions.

## Observable acceptance

- Bound read-byte work with an instrumented file fixture; do not rely on flaky
  timing thresholds. Aligned/unaligned reads, final short block, EOF and empty blobs
  return exactly the requested bytes within the protocol cap.
- Modify requested bytes while preserving file size/mtime: the block fails. Missing,
  replaced, truncated, extended and symlinked files fail without leaking other bytes.
- Missing/extra/reordered/malformed or cross-workspace digest records cannot authorize
  a read. A declared full-file hash mismatch cannot create committed block metadata.
- Crash around file finalization, block insertion and ownership commit; retry restores
  a complete consistent object without duplicate reservations or public orphan bytes.
- Wrong/revoked tokens, another workspace's known hash, device-bound upload sessions
  and quotas retain existing behavior. Exercise actual loopback HTTP in addition to
  pure helpers, then run the full project check.

This ADR records a concrete next implementation, not a claim that large-file transfer
performance is ready or that a production service has been deployed.
