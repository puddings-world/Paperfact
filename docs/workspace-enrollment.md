# Staged first-enrollment candidate

`workspace_enrollment.EnrollmentService` is an explicit, local-only service for a
**bounded supported subset** of an unbound research directory. It prepares a new
candidate directory and an independently inspected recovery archive. It never
changes the source binding, selects the candidate as the current workspace,
contacts a service, uploads data, persists a session credential or starts sync.
This is not complete first enrollment for an arbitrary existing workspace.

```python
service = EnrollmentService(database, source_root=research_directory)
plan = service.plan(pdfs={local_paper_id: trusted_pdf_path}, ticket=ticket)
# Present plan["blockers"] before offering preparation.
result = service.prepare(
    new_directory,
    backup_output=new_backup_zip,
    request_id=canonical_request_uuid,
    pdfs={local_paper_id: trusted_pdf_path},
    ticket=ticket,
    progress=show_worker_message,
)
```

Both output paths must be new, in existing parent directories, outside the source
and separate from each other. Source links/reparse points and unexpected files
are rejected. `plan` reads only; it creates neither directories nor identities.
`EnrollmentBlocked.plan` gives the same structured coverage report on failure.
Invalid paths/selections and bounds raise `ValueError`; source changes raise
`SnapshotChanged`; cancellation raises `Cancelled`. Run preparation on a worker.
Repeated activation of one service is rejected while running. Existing output
and backup files are never replaced.

## What is covered

The source must have the exact initialized current trusted table columns;
centrally registered optional recovery tables may be absent in older workspaces.
Coverage derives from `sync_content.CONTENT_TABLES` and the research section of
`sync_recovery._registry()`, including optional research extensions. A present
capturable table without recovery coverage blocks rather than disappearing.
A future extension also needs its trusted `store.SCHEMA` initialization; otherwise
an unexpected table is explicitly rejected. The
existing capture serializers handle papers, lists, memberships/reading state,
notes and `sync_content.CONTENT_TABLES` (including deep readings, context,
citations, followups, resources, chat and database highlights). The staged copy
preserves every represented research row exactly: a serializer normalization that
would change the source row is rejected rather than silently accepted. Saved
`lists.order` is retained; a new order can be generated when none was saved.
Author enrichment tables are preserved locally, explicitly not represented as
portable edits. The workspace invalidation counter is rebuilt locally.

Every source PDF must be explicitly mapped to its **local** paper ID. The service
hashes bounded actual bytes, stages them with the existing immutable `BlobStore`,
creates existing `paper_document` manifests through `ResearchOperations`, verifies
PDF readability, and binds the exact current desired target using the existing
sealed verifier. PDFs are also included in the independent recovery archive.
Final reader/store bindings refer to the new directory, never the temporary stage
or source. Private configuration files and `ui.`, `ai.`, `provider.`, `account.`,
`usage.` and `auth.` KV scopes are excluded from both candidate and archive. They
are not interpreted or copied. Unknown KV scopes block enrollment.

The current limits are 100,000 inventoried SQL rows / 64 MiB encoded SQL values,
256 explicitly mapped PDFs / 512 MiB total bytes / 150 MiB per PDF, and 2,048
source filesystem entries. Cancellation is checked during inventory and between
staging steps. A native PDF verification or recovery call is not interruptible
mid-call; cancellation still prevents final publication. No percentages are
inferred from these limits.

## Explicit blockers and remaining work

Per-list pins with an actual current membership and timezone-aware timestamp are
covered by the [list-pin domain](list-pins.md). Paper-scoped legacy queue pins
are also supported; orphan pins, invalid timestamps and an unrecognized cleanup
trigger block preparation.

Queue entries and reading logs are no longer blanket blockers: the current
`legacy_workflow` adapter and `capture_existing` retain their declared fields,
portable identities and timestamps. Declared Markdown briefs are inventoried and
materialized through `legacy_briefs`; missing bytes or unsupported legacy
semantics block rather than being guessed. This preserves legacy research; it
does not make the optional ML daily workflow mandatory.

Current enrollment also inventories verified source provenance, reading positions,
Lineage source dependencies, retained chat/review history and supported manual
deck observations. These have separate source/ownership checks in
`workspace_enrollment.py`; archived observations do not automatically become
active live revisions or authorize an old AI job. A deck's verified recovery
record is distinct from live `sync_deck_files`/`sync_files` publication.

Custom tables, unrecognized schema writers/views, unsupported integration
receipts/KV scopes, missing original bytes and any remaining unmapped research
file still block. Unknown annotations, extracted text or sidecars are not silently
dropped. The inventory and returned `plan["blockers"]` are authoritative for the
particular workspace; this is not a claim of arbitrary legacy-directory coverage.

## Consistency, backup and adoption

A source read snapshot is copied into trusted schema and passed through the
existing capture transaction. The service checks supported rows after capture,
creates and inspects the existing complete-or-fail recovery archive, and checks a
fresh source SQL/schema/file inventory again before publication. Files are
verified by actual bytes, not manifest existence. Cancellation and source changes
cannot publish a stale candidate. A final source change immediately after the
last check can only make the independent snapshot old; it cannot change its bytes.

The source is never write-locked by this service. Complete runtime enrollment
still requires a shared workspace maintenance lock honored by UI, CLI, MCP and
workers, draining pending writers/drafts, a final reviewed baseline, and explicit
runtime rebinding/restart. No final hash check can replace that adoption lock.
Every successful result has `runtime_enrollment_complete=False`,
`requires_review_and_adoption=True`, `adopted=False` and `uploaded=False`.
Keep the source for rollback. Do not use this slice to enroll daily research
without the remaining coverage and adoption gates.

The same request UUID retains workspace/device/paper identities across an
unpublished retry. Operation IDs are not a durable resumable enrollment log.
Published candidates must not be independently copied into two running devices
with the same device identity; use the existing new-device join flow instead.

Preparation carries stable identities for the explicit request, not an automatic
source-to-destination adoption decision. Reusing a request UUID for a second
independently adopted output is unsupported; choose a fresh request for a distinct
workspace or use new-device join.

Directory publication is atomic and refuses replacement. Backup publication
uses an exclusive hard link on the backup filesystem; incompatible filesystems
fail closed. If directory publication fails, the newly linked backup is removed
only while it is still the same owned inode. A process crash between these two
publications can leave a valid independent backup without the candidate. There
is no claim of an atomic two-filesystem transaction. Existing recovery verification
and detached restore are the rollback/read-only recovery seams.

## Evidence and integration seam

`tests/test_workspace_enrollment.py` uses actual trusted SQL tables, journal
capture, readable PDF bytes, sealed document binding, inspected recovery archives
and detached restore in isolated temporary directories. It covers coverage
blocking, private-data exclusion, source changes/replacement, cancellation,
retry, repeated activation, corruption and publication failures. No production
research, remote authority or model account is used.

The desktop enrollment dialog already previews the plan, displays blockers,
selects explicit new candidate/backup paths, runs preparation on a worker and
opens a prepared candidate through the existing workspace flow. Its tests cover
actual preview/prepare/open, unsupported coverage, repeated activation,
cancellation and source/workspace changes. This is not an in-place adoption of
the owner's source or automatic upload. Complete maintenance locking, supported
writer/file coverage and installed-device acceptance remain separate gates.
