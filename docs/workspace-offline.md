# Selected research offline preparation

Status: local service slice, not automatic downloading or cache retention.

`workspace_offline.OfflineService` supplies explicit device-local pin intent,
metadata planning and bounded verification for an already capture-enrolled
workspace. It takes an explicit database and optional `current_path` callback;
ordinary non-enrolled research is rejected rather than enrolled implicitly.
The service never invokes transport, AI, publication, legacy-file migration,
materialization or cache eviction.

## API

```python
service = OfflineService(database, current_path=current_database)
plan = service.plan(local_paper_ids, ticket)
report = service.status(local_paper_ids, ticket)
service.set_pins(local_paper_ids, enabled=True, ticket=ticket)
service.set_pins(local_paper_ids, enabled=False, ticket=ticket)
pinned = service.pins()
```

Selections contain **local** paper IDs, at most 100 per action. Duplicates are
collapsed while preserving their order. Portable IDs are resolved inside the
bound database; the UI must not construct or guess them. Pins are stored only
under `ui.offline.paper.<portable UUID>` KV keys. These are local UI preferences,
excluded by the existing capture boundary from research operations. Retrying a
pin operation creates no additional research data or outgoing sync operations.
Unpinning removes intent, never file bytes. Missing/damaged asset metadata does
not prevent unpinning an otherwise existing mapped paper. Pin intent survives
restart but **does not yet guarantee download or protection from eviction**.
At most 1,000 intent keys are supported; orphaned/deleted-paper intent cleanup
is not implemented automatically.

`plan` is metadata-only and always returns `ready=False`. `status` re-reads and
validates actual existing bytes using the established `verify_document` and
`verify_closure` functions, then compares selected metadata and sealed file
proofs again before returning. It does not create projections or touch the
research outbox. A status result is a point-in-time observation, not a lease on
future file integrity.

## Scope and interpretation

Both results contain:

- `scope: selected_current_manifests`, and one `papers` entry per selected paper.
- Each entry has local/portable identity, a bounded title, current pin intent,
  desired/applied PDF information and both supported editable-deck slots
  (`notes`, `guide`) when declared.
- `required_bytes` and `required_assets` deduplicate current PDF/deck closure
  descriptors. They count the entire declared closure, not estimated new download
  bytes; disk space for extra projections/temporary files remains separate.
- `whole_workspace_offline_verified=False` always. This service does not inspect
  arbitrary legacy caches, all historical versions, linked external papers,
  online citation targets, remote Google Slides, or every reader interaction.

`status` adds per-paper and aggregate `ready`, plus `partial`, `verified_bytes`,
`verified_assets`, `checked_assets` and `verification_bytes`. Verified totals
exclude invalid/stale proofs and deduplicate shared blobs; work totals may be
larger because existing closure verifiers can inspect a shared image twice.

A paper is ready only if its current desired PDF is applied and verified, the
artifact inventory exists, and every declared current editable deck is applied,
byte-verified and tied to that PDF's exact source hash. Missing PDF manifests,
unapplied replacement versions, absent assets, corrupt bytes and unknown or
mismatching deck source provenance never become a ready claim. Intact deck bytes
with unknown source provenance remain distinguishable from corrupt bytes.
A selected paper with no declared deck does not cause the service to generate one.
Verified stored closure does not prove native rendering or writable projection
space; those remain reader/platform acceptance checks.

PDF/artifact states include `unchecked`, `missing_manifest`, `unbound`, `stale`,
`verified`, `unconfigured`, `budget_exceeded`, `unavailable` and `invalid`.
Artifact `source_state` is independently `current`, `unknown` or `mismatch`.
User-facing copy should distinguish absent bytes, pending versions, integrity
failures and a verification budget limit rather than treating them all as
network failures.

## Resource bounds and invalidation

The default and maximum per-pass budgets are 64 MiB of manifest-described
verification work, 256 blob checks and 10 seconds (time may be explicitly set
up to 30 seconds). No workspace-wide blob scan occurs. Selection, metadata row
sizes, deck slots and descriptor counts are bounded before invoking verifiers.
Budget-limited work returns `partial=True`, not a fabricated completion percent.
A larger-than-budget document cannot be fully verified through this API yet;
a resumable large-document verifier is a remaining integration seam, not a
reason to label it ready on repeated clicks.

Cancellation and time checks occur between the established bounded PDF/closure
verifications; the service does not forcibly interrupt a parser mid-file. A
single verifier may finish after the requested wall-clock budget, in which case
its result is not counted ready. This is cooperative budgeting, not a hard real-
time deadline.

Changed workspace path, database identity, capture identity, storage registration
or blob ownership raises `WorkspaceChanged`. Changed selected targets during a
pass raise `SnapshotChanged`. `Ticket` cancellation raises `Cancelled`; pin writes
use its existing final-publication lock and roll back storage failures. These
results never update another workspace or return a stale-ready report.

## Evidence and remaining work

`tests/test_workspace_offline.py` uses real isolated research tables, capture
bindings, PDFs, editable deck bodies/PNG assets and blob stores. It covers local
pin persistence and outbox isolation, empty/invalid/repeated selection, storage
failure/retry, cancellation, source/workspace changes, ownership mismatch,
corruption, applied/desired version differences, unknown source provenance,
shared assets and budget-limited verification. It performs no real login, paid
call, network access, cache eviction or production research operation.

Desktop selection/status/pin controls, explicitly selected download execution,
pin-aware cache lifecycle, resumable large-file verification, physical device
acceptance and automatic background scheduling are separate integration work.
The service must not be advertised as completing those capabilities.
