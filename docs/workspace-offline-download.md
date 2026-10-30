# Explicit selected attachment download

Status: local/reference implementation candidate. This action downloads already
known current attachments for selected papers. It is separate from metadata sync,
first enrollment, pin intent, complete offline verification and automatic upkeep.

## API and scope

```python
result = session.prepare_offline(
    local_paper_ids,
    ticket,
    progress=on_progress,
    steps=64,
    seconds=20,
)
```

`SyncSession.prepare_offline` accepts at most 100 selected **local** paper IDs.
The existing `OfflineService.plan` resolves and validates their portable identities
and current desired PDF/editable-deck manifests. Duplicates are collapsed. Empty
selection is a local no-op; invalid selections/budgets fail before authentication.
A nonempty selection requires an explicitly connected matching workspace/device.
There is no implicit enrollment, metadata push/pull, provider/model call or pin.
Unknown remote manifests remain unknown until a separate explicit metadata sync.

The action downloads exactly the current primary PDFs and both supported editable
deck slots (`notes`, `guide`) for those selected portable papers. The blob store
naturally deduplicates shared assets; bytes shared by two decks need not be fetched
again. Unrelated desired/applied bindings and transfer rows remain untouched.

`AttachmentSteps.download_selected(portable_ids)` is the private integration seam.
`download_pending(paper_ids=None, include_applied=False)` and
`status(paper_ids=None)` retain the old global default behavior for ordinary sync.
An explicit empty filter means no targets, never all targets. The selected action
also rechecks already-applied targets: a matching applied metadata row does not
prove the corresponding immutable bytes still exist or are intact.

## Authentication and invalidation

The operation uses the existing `_job`, `authorized`, `_Live`, `GuardedJournal`,
`DocumentTransfers` and `FileTransfers` boundaries. It authenticates the intended
workspace/device before reading private bytes. Credentials remain in the session;
existing transfer receipts persist only operation/endpoint/progress metadata.

A selected guard revalidates local/portable identity, current desired PDF targets,
canonical deck operations and artifact inventory before/after coordinator steps,
private transport requests and guarded commits. Applied-version changes caused by
the download are permitted; a new desired version is not silently substituted for
the one selected when the action began. Workspace/session changes, disconnect,
cancellation and selected source replacement abort without a stale-success result.
Already staged immutable chunks may remain for an explicit retry, but cannot bind
to the wrong current source. A second action cannot start while another session
job is running.

## Bounded progress and results

`steps` is a positive integer up to 256 (default 64); `seconds` is a finite positive
number up to 60 (default 20). A step is one existing coordinator call, not a claim
about total wall-clock time or exact remaining network requests. Existing bounded
PDF/closure verification and local publication are cooperative; a parser or closure
validation already running is not forcibly interrupted mid-call.

Progress contains actual coordinator steps, available offsets/sizes or completed
asset counts. It never invents a total percentage or ETA. The result contains:

- `state`: `empty`, `partial` or `downloaded`.
- `paper_ids` and `portable_ids`: the explicitly selected identities.
- `attachments`: selected pending metadata count, actual steps/failures,
  `transfer_targets`, `attempted_targets`, `completed_targets` and
  `remaining_targets`, plus storage availability.
- `missing_pdf_manifests`: selected papers with no known current PDF manifest.
- `partial`: true for unfinished, failed, missing-manifest or unconfigured work.
- `verification_required=True`; `complete_offline_verified` stays false.

A zero metadata pending count cannot hide an unattempted or corrupt already-applied
target. `downloaded` means the selected transfer pass completed using the existing
coordinator verification/binding contract. It is not a complete research/offline
readiness badge: run `OfflineService.status` explicitly to inspect the selected
current closure and source-version relationship. Unknown deck provenance can
prevent that separate readiness check even when its bytes downloaded correctly.
The action does not advance the session's last successful **metadata** sync time.

Retries reuse existing operation identities and durable verified-length partial
chunks. Invalid partial PDF data follows the existing explicit-retry repair path.
A corrupt final immutable cache object may fail with repair required; this action
does not silently remove or overwrite a possibly open applied object. Such failure
remains partial/failed even when its metadata binding is current. A separate safe
quarantine/repair lifecycle is still needed for damaged final objects.

## Evidence and remaining integration

`tests/test_workspace_offline_download.py` uses native/reference and real loopback
HTTP authorities with two unrelated papers and editable decks. It checks exact
selected scope, preserved unsent metadata/cursor, no pin changes, idempotent retries,
resumable chunk offsets, invalid/empty selection, work budgets, revoked credentials,
duplicate jobs, cancellation/disconnect/workspace/source races, corrupted partial
repair and honest failure for corrupted already-applied bytes. It does not access
production research, external services or AI accounts.

The parent integration still owns desktop download controls, complete-current-tree
validation, native device acceptance and pin-aware background/cache lifecycle.
This is not an automatic synchronization or eviction-retention guarantee.
