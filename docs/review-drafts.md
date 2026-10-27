# Durable edited review drafts

Edited review text now survives dialog close and application restart. Drafts are
private device-local records; they do not call AI, create sync operations or alter
research until the user applies a reviewed result.

## Saved state and boundaries

`research_review_drafts` stores a stable draft ID, retained origin, pinned database
path/inode/binding, the exact original displayed preview, edited text, request ID,
CAS revision, save sequence, timestamp and integrity fingerprint. The snapshot
includes the original source-document hash and selected parent lifecycle. It does
not store credentials or service configuration. Its local path is provenance,
never a restore destination or an instruction to open another workspace.

The closed validator bounds text to 200 KiB and a complete record to 8 MiB.
The store permits at most 500 variants and 64 MiB of snapshot/text content per
database. Hitting a limit preserves existing records and the unsaved visible text;
it does not evict another draft. The history picker returns at most 20 lightweight
items per page, with a service maximum of 50. Database-transaction save sequence,
not wall-clock time, determines the latest variant.

An exact save retry returns the same revision. Another window's changed revision
causes a conflict instead of an overwrite. **Save a separate draft** preserves both
versions, and **Drafts…** opens older variants without refreshing their bases.

## Restart and review states

| State | Restored behavior |
|---|---|
| Ready | Restore the exact old preview/base, text and retry identity; application remains guarded |
| Stale | Preserve text and displayed base; require explicit Review latest version before applying |
| Earlier workspace/binding | Preserve text; require explicit target selection and confirmation |
| Already decided | Keep the text available; require another review for a new change; exact request retries remain idempotent |
| Corrupt metadata | Preserve the original record and recoverable text; copy/export only, no application capability |

Restoration re-seals the stored snapshot for the current review session. It never
obtains a new base and silently attaches the old draft to it. A parent renamed,
deleted/recreated, or moved to another database/binding invalidates the saved
target. Explicit refresh or target selection is a separate user action.

## Desktop close contract

The editor autosaves after a 500 ms typing pause. Apply flushes the edited draft
before changing research. Close flushes pending edits before disposing the dialog.
SQLite lock waits are bounded to 250 ms, including connection initialization.

If saving fails, `ReviewDialog.close()` returns false and the dialog remains visible
with its text and an honest unsaved message. The host must honor this result for
workspace switches and application shutdown. The user can retry or export the
text; exporting a valid displayed snapshot does not require the original database
to remain available. No failed save is relabeled as saved.

Private draft saving may finish after a review operation has been cancelled, but
only in its pinned original database/binding. It cannot publish research or write
into a replacement workspace. Draft errors remain associated with their original
item when the user navigates between retained results.

## API and recovery

```python
saved = review.save_draft(preview, text, request_id)
saved = review.save_draft(preview, changed_text, next_request_id, **saved)
restored = review.load_draft(origin, origin_id)
page = review.list_drafts(origin, origin_id, limit=20)
variant = review.load_draft(origin, origin_id, draft_id=selected_id)
```

The review action fingerprint excludes ephemeral UI-session data, so a saved
request can be retried after restart without duplicating a research mutation.
Draft persistence itself is independently transactional and never queues an AI
request or research operation.

Recovery archives include validated draft records as protocol provenance.
Detached restore keeps them in `recovery_records`; it does not recreate live draft
state, old device sessions, or old apply capabilities. The recovery review adapter
can display and export retained text and its original source hash. Corrupt records
block a complete backup explicitly, leaving the source untouched.

Current typed draft origins are generated SQL candidates, owned generation
sidecars and remote note/research-content conflicts. QA and compound adapters must
provide their own closed snapshot validation/currentness checks before joining
this registry. There is no generic SQL replay or arbitrary-object deserialization.

Fixture evidence covers restart, original source hashes, stale and replaced
targets, concurrent windows, exact retries, corrupted records, quotas, independent
variants, wall-clock changes, detached recovery, and real Qt close failure/retry.
No real user database, login, model call, upload or deployment is used. The parent
integration remains responsible for the merged full check and native platform QA.
