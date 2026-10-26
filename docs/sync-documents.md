# Primary PDF manifests and verified local bindings

This private v2 slice implements document metadata, durable transfer intents and
verified immutable-byte bindings. It does not activate the desktop/mobile reader,
change legacy PDF aliases or caches, reanchor research, fetch paper URLs or call AI.
See [ADR 0004](adr/0004-owned-document-transfer.md) for the transfer and reader boundaries.

## Wire and research identity

`paper_document` has the portable paper UUID as entity ID and one exact
`paper` incarnation parent. Its logical role is implicitly `primary_pdf`.
Put payloads contain exactly `paper_id`, `sha256`, `size`, and `media_type`.
The paper must match the entity and parent; SHA256 is lowercase hexadecimal;
size is a positive integer at most 150 MiB; media type is `application/pdf`.
Paths, URLs, filenames, credentials and arbitrary additional fields are rejected.
A delete has an empty payload and detaches the desired manifest without removing
bytes, applied history, notes, highlights or other research.

Explicit `sync_research.prepare` adds the tables below without enrolling any legacy
PDF. Successful v2 paper projection records `research_paper_projection` containing
`sync_id` and `incarnation`. A document put requires this exact paper projection
and an existing mapped paper row. Its desired target and transfer intent commit
in the same transaction as the operation receipt. Missing bytes have no bearing
on this metadata transaction or the incoming metadata cursor.

## Coordinator API and ownership

`sync_documents` exports:

- `desired_document(conn, paper_id)`: active desired target, or null.
- `applied_document(conn, paper_id)`: last successfully bound target, or null;
  it may differ from desired and does not prove current byte availability.
- `list_desired_documents(conn, after="", limit=100)`: active targets ordered by
  portable paper ID; use the last paper ID as the next cursor, maximum 1,000.
- `verify_document(store, target)`: explicit BlobStore verification followed by
  readable-PDF validation; returns a process-local `VerifiedDocument` snapshot.
- `bind_verified_document(conn, target, verified)`: caller-owned transaction;
  returns false for obsolete targets, replaced/missing files or mismatched paper
  incarnations. It never commits independently and never activates a reader.

A target is a closed object with `workspace_id`, `paper_id`, `operation_id`,
`incarnation`, `parent_incarnation`, `sha256`, `size`, and `media_type`.
The coordinator owns session generation, origin/token revocation checks, transfer
offsets, retry scheduling and cancellation. It must recheck its session immediately
before binding. These helpers cannot infer the current remote session from a local
SQLite connection. Keep credentials out of all persisted transfer records.

Table ownership is explicit:

| Table | Fields | Owner |
|---|---|---|
| `research_document_desired` | paper_id primary key, target JSON, active | document metadata writer |
| `research_document_applied` | paper_id primary key, target JSON | verified binding helper |
| `research_document_intents` | operation_id primary key, paper_id, target JSON, state | document helpers |

Intent states are `pending`, `superseded`, and `bound`. Replacing/detaching desired
metadata supersedes prior pending intents; binding marks the matching intent bound.
The coordinator uses a separate bookkeeping table instead of modifying these state
rules. Applied targets survive replacement/deletion for recovery. Repeating an
identical binding performs no SQLite updates. Failed metadata/binding transactions
roll back; already verified immutable objects remain reusable cache objects.

## Verification boundary

Verification uses BlobStore's full hash/size check, rejects linked/reparse paths,
checks the PDF header and EOF, and uses PyMuPDF to reject password-required,
empty or unreadable PDFs. File identity is captured before verification and checked
after parsing. The returned snapshot contains private local path/stat information;
it must never be serialized, accepted from a remote claim or exposed in the DTO.

Binding compares the exact desired operation/document incarnation, paper parent
incarnation, workspace and verified snapshot. A cheap file identity check rejects
subsequent deletion, replacement or observable modification. Verification runs in
background work, outside the read/UI path. This is not a sandbox against a hostile
local process deliberately defeating filesystem metadata checks; refresh/reverify
after known file changes. No old or unknown-hash anchor is migrated or enabled by
this binding. Reader activation requires the separate hash-aware reader/cache work.

## DTO2 document manifests

`papers[].document` contains `desired` (the closed four-field manifest or null),
`applied_sha256` (or null), `availability`, `revision`, and `sync_state`.
`papers[].pdf_asset_id` references `sha256:<digest>` for the desired manifest.
`assets[]` deduplicates `{id, sha256, size, media_type, availability}` objects.
Conflicting sizes for one content digest fail rather than presenting ambiguous bytes.

Availability is `unchecked` by default, even when a stored applied binding exists.
Call `read_manifest(..., schema_version=2, verified_documents=[snapshot, ...])` with
explicit verification snapshots to expose `available` for an exact still-current
target. DTO reads only perform cheap snapshot identity checks, never PDF hashing,
parsing or network operations. Missing/invalid verification raises at the verifier;
coordinator progress/error UI can distinguish those outcomes without inventing
availability in a stored flag. Manifest and cursor share the existing read snapshot.

DTO2 capabilities `assets=true` and `document_manifests=true` mean manifest metadata
is supported, not that files exist locally or can be opened by the reader.
`document_contract_version=2`, `reader_activation=false`, and `sync_bootstrap=false`
make those limits explicit. DTO1 fields and behavior remain unchanged.

`tests/test_sync_document_research.py` and `tests/test_sync_document_projection.py`
use actual-schema temporary databases and synthetic PDFs. They cover closed schema,
durable intents, metadata-before-bytes, cursor advancement, retry/reopen/rollback,
replacement and stale completion, missing/corrupt/unreadable PDF rejection, independent
desired/applied bindings, default unchecked DTOs, exact snapshots, no read-time hashing,
legacy research preservation and consistent cursor/manifest reads. Production data,
network PDF discovery and reader activation are not exercised.
The post-verification symlink case simulates filesystem metadata on platforms where
creating a real symlink requires additional privileges; it does not skip coverage.
