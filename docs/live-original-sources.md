# Live original-source artifacts

Status: isolated source-closure implementation with focused fixtures; not a
complete enrollment, deployment or professional-reading release acceptance.

## Portable immutable source

An `original_source` is a versioned `research_file`, not a new current primary
PDF. Its stable file ID combines the portable paper UUID, feature and exact PDF
SHA256. The operation has exactly one current paper-incarnation parent. Its closed
version-1 body contains only `version`, `paper_id`, and `document_hash`; exactly
one `original_pdf` asset declares the same hash, positive byte size and
`application/pdf` media type. No source path, database inode, runtime lifecycle,
account, credential or private receipt is sent. Unknown feature/body versions and
inconsistent owner/hash descriptors fail closed.

Source PDFs have their own 150 MiB bound, matching primary PDFs. The existing
64 MiB deck asset budget remains unchanged. Both JSON and PDF bytes use the
existing owned BlobStore, authenticated resumable FileTransfers, desired/applied
metadata and verified immutable closure. Receiving metadata does not claim that
bytes are locally available. Materialization writes `source.json` and `source.pdf`
in a registered immutable version directory and never changes `paper_document`.

## Shared operations and publication

`sync_source_files.encode(paper_uuid, pdf_bytes)` validates a real readable PDF and
returns its closed manifest plus blob bytes. `publish(...)` is an explicit local
path action against an observed paper incarnation. Identical owner/hash writes
reuse the existing artifact. The path is an explicit local capability, never a
field decoded from remote research.

For a larger caller-owned operation:

```python
prepared = prepare_source(
    client, paper_uuid, explicit_pdf_path,
    document_hash=sha256, parent_incarnation=observed_or_planned_parent,
    store=owned_store, version_root=registered_versions, request_id=operation_id,
)
with client.journal.transaction() as conn:
    # A planned new parent may be created here by the typed operation first.
    operation = publish_source_in(conn, client, prepared)
    # Other typed writes and the caller's retry receipt use this same transaction.
```

Preparation runs the byte/hash/PDF closure validation before the write lock. The
native prepared object cannot be reconstructed from wire JSON. Application checks
the original database/workspace/device binding, exact current parent and native
byte-proof freshness. It never commits the caller transaction. A later child
failure rolls source metadata and outbox ownership back; staged bytes may remain
as a private harmless cache. Deleted/retired originals require explicit source
restoration rather than generic automatic reattachment.

Accepted ClaimJob publication stages the exact captured original, then commits
its source artifact, claim row, outbox and generation receipt together. Stale,
failed or cancelled output emits no shared source operation. Completed original
work and ownership receipts remain locally recoverable. A lost commit reply does
not duplicate the source or repeat AI. This hook does not extend source coverage
to every other research writer automatically; enrolled list-package import has a
separate compound integration requirement.

`resolved(conn, paper_uuid, sha256)` returns a verified owned PDF path only for an
applied source artifact in the current paper incarnation. It never substitutes a
newer hash or activates the old original as today's primary document. Desktop
inspection of that path needs an explicit read-only original-version window;
in-place reader jumps retain their current-source guard.

## Enrollment and private history

First enrollment can represent a saved claim grounded in original A while the
selected primary is B. It stages A as an immutable source and B as a primary PDF.
Its coverage report names original-source and archival-receipt counts. Unknown
nearby PDFs, changed bytes, missing owners and missing originals remain blockers.
Active annotation-known markers are admitted only when backed by their typed
saved row; known deletion markers still require explicit migration.

All validated owned snapshot receipts, including unsuccessful previous attempts,
are preserved in `research_source_archive(record_id, body_json)`. Each record ID
hashes the canonical validated original receipt. This is a private archive-only
protocol, never SQL capture/shared content and never a current-job authority. Old
DB/device/workspace observations are retained unchanged, rather than rebound to
fresh runtime identities. Every declared original is deduplicated by hash and
retained in owned storage and complete recovery backups, even when no current
claim needs it on the shared wire. Detached restore archives these records without
activating the old identities.

This does **not** make real generated workspaces fully enrollable. Normal ClaimJob
history still has separate registered migration requirements:

| Local format | Existing validator | Required treatment |
|---|---|---|
| `research_generation_requests` and sidecar `research_generation_recovery`: request_id, context_json, row_json, status, candidate_id, reason | `research_generation.validate_request_record` | Preserve validated original observations/results as archive-only provenance; never create live jobs from them. |
| `research_parent_lifecycle`: kind, entity_id, token, active, with six exact parent triggers | `research_lifecycle.validate_record` | Archive old local epochs/triggers as observations; install fresh active epochs for the new runtime. |
| `research_capture_candidates`: id, content | Existing typed candidate/review decoder | Keep unresolved candidates and their original owner/source, not only canonical current rows. |
| Known annotation deletion markers without a current typed row | Feature registry and scoped tombstone operation | Preserve explicit deletion semantics in the new graph; never treat absence as missing AI work. |

Other registered chat/compound/review history formats remain separate work. This
slice deliberately reports unsupported history instead of discarding it or calling
first enrollment complete.

## Offline and recovery boundaries

The selected attachment helper includes original-source artifacts. Offline plans
require the original hash declared by each saved claim when it differs from the
primary. A valid historical original qualifies as original provenance without
requiring equality with current B. Missing manifests, unapplied bytes, corruption,
unknown ownership and exhausted verification budgets never produce a ready
result. Existing resumable native proofs and aggregate budgets remain in use.
Unused private history is retained but is not automatically required by every
current-paper offline pass.

Complete backups preserve the exact body/PDF closure and private archival source
receipts. A detached source remains provenance, never a replacement primary or a
restored live device. Fixtures exercise source A/current B, actual two-device blob
transfer, selected download, offline rechecks, atomic rollback/retry, ownership
changes, unknown schema and private failed-attempt retention. Full combined gates,
live services, desktop original-version UX and packaging remain separate checks.
