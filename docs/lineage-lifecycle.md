# Lineage analysis lifecycle contract

Status: backend and desktop integration in development, 2026-11-13; unreleased.
Confirmed remove/restore, version selection and independently verified historical
PDF inspection and fresh detached editable Lineage adoption are locally
implemented. Final full/release/device acceptance remains open work.
This preserves the full v0.5 requirement rather than treating generation/viewing
as completion. The [current reader](lineage-reader.md) and its verified original
routing are prerequisites, not substitutes for this work.

## User actions

- **Remove analysis** acts on the displayed corpus after confirmation. It removes
  canonical visibility and frees its active slot; it does not delete PDFs, source
  ownership, the original generation record or immutable operation history.
- **History** displays previous and removed results as historical content. Reading
  history is not authority to activate a report or open an unowned original.
- **Restore** is explicit, requires an empty current target, and checks the exact
  historical origin and current selected-paper/source lifetimes. It invokes no AI.
  A conflicting new target or obsolete source permission requires review, not
  silent replacement or rebasing to a same-hash file.

Native workspaces use genuine typed journal retire/restore operations, stable
request IDs and existing projection history. Restoration creates a new scientific
incarnation while retaining the old original pins; it cannot revive a retired or
replaced source grant. These backend semantics already have integration evidence,
and the shared application lifecycle facade and desktop controls now use those
operations. The version catalog includes generated, imported/displaced and native
scientific versions, independently of the smaller local action-history view.

Unbound workspaces need an explicit local lifecycle receipt/history in the same
transaction as the canonical row transition. Do not label this an import or a new
AI completion. Resolve a generated publication or imported receiver receipt by
exact identity, then validate its retained parents and source associations. Never
infer a generated origin from the absence of an import match. The current
`lineage_source_reader` selects these origins for current-row inspection; it is
not a restore grant and must not be weakened to accept an absent row.

## Required invariants

1. The action carries an observed row/absence, focal owner and scientific lifecycle.
   Recheck them after confirmation and inside the actual capture-aware transaction.
2. A stable request ID plus payload fingerprint makes retries return the same
   action; reuse with different content refuses. Repeated clicks create no jobs.
3. Keep historical row/model/source metadata immutable. Native action receipts
   are real journal entries; portable archive records never fabricate acceptance.
4. A missing file cache is distinct from deleted source ownership. Restoring
   metadata does not download bytes or grant source access. Changed paper/database
   lifetimes require reviewed fresh adoption; never rehydrate native leases from
   stored JSON or borrow today's primary PDF.
5. Preserve earlier caller work on action failure and roll back row/history/outbox
   together. Cancellation/view/account changes cannot apply to another target.
6. Whole-workspace backup retains historical content and exact original closure.
   Validate any new lifecycle schema in export, detached restore, enrollment and
   budget checks before exposing the action. Detached restoration is not device
   enrollment or replay authority.
7. List sharing exports current research by default. Sharing removed/private
   history needs an explicit option; do not silently add deleted content to a link.

## Acceptance contract for controls

| Journey | Observable result |
|---|---|
| Remove/cancel/retry | Cancel changes nothing; success hides exactly the observed corpus; identical retry creates one action and frees one slot. |
| Concurrent incoming edit | A changed row/target refuses or becomes an explicit conflict; neither version is lost. |
| Restore at capacity/new target | Existing content is preserved; explain the required choice and keep the historical report. |
| Source retirement/restoration | Same bytes under a new source incarnation do not authorize restoration of old science. |
| Local and native origins | Generated, imported and peer-received histories retain their actual provenance; no reader fallback or fabricated model run. |
| Close/changed context | Active workers drain safely; stale results never enter the new paper/workspace. |
| Backup/reopen/share | Independent restore preserves removed history and originals without identity reactivation; default list sharing excludes removed entries. |

Use generated PDFs and simulated providers. Add actual Qt and two-client journeys,
then validate affected archive/enrollment contracts and the final full application
gate. Linux hosting and installed Mac/phone acceptance remain external gates.

## Shared lifecycle API (development)

`lineage_lifecycle.apply_in(conn, owner, row, *, request_id, action, origin=None,
cancelled=...) -> dict` requires a worker, a loaded `HighlightOwner`, and the
caller's actual capture-aware transaction. `action` is `retire` or `restore`.
A restore requires an explicit origin selected from retained history. The result
reports `saved_local` or `queued_sync`, the request/operation identities and
`applied`; queued is not remote acceptance. The caller commits or rolls back.

`lineage_lifecycle.change(owner, row, *, request_id, action, origin=None,
cancelled=...) -> dict` owns that transaction for worker callers. Neither API
invokes a model, downloads files, grants source ownership or replaces PDFs.
Repeated exact requests do not create another action; later target changes and
request-ID reuse with different intent refuse. A selected paper may be renamed;
deleting and recreating its ID changes its lifetime and refuses old restoration.

`lineage_lifecycle.history(owner, *, limit=100) -> dict` is a bounded read-only
view of local lifecycle receipts with `items` and `more`. Each item retains its
actual generated/import/native origin, row, action and current-row status. This
is action history, not yet a complete browser of every historical scientific edit.
Returned metadata is not source access or restoration permission.

Whole-workspace recovery includes the closed `research_lineage_actions` records
and checks exact generated publication, imported receipt or immutable native
operation closure. Independent source verification remains required. Detached
restore keeps these records in its archive, never as live action receipts or
reactivated device identity. Enrollment history can retain their closed data shape;
that alone does not prove end-to-end enrollment/adoption of all Lineage content.

Initial local evidence: nine unbound lifecycle cases passed, one native two-device
round trip passed, then twelve lifecycle/recovery cases passed in 56.32 s. These
selections overlap. Additional imported/source-lifetime and archive/enrollment
regression is recorded in the continuation ledger; no whole-release pass is implied.

Native late action-receipt failure/cancellation, historical-version selection,
list-sharing privacy and actual Qt lifecycle journeys now have focused local
evidence. Independently verified historical-original inspection now has its own
API and scenario coverage below. Complete detached editable adoption, installed
Mac/phone and hosted Linux acceptance remain open gates.

See the [behavior scenario map](testing/lineage-lifecycle-scenarios.md) for concrete
user outcomes and the boundaries each test protects.

Latest focused evidence: 97 lifecycle/recovery/enrollment cases passed in 339.24 s
(343.1 s overall), followed by one real list-sharing privacy case in 3.20 s
(6.6 s overall). Privacy/Ruff passed in both. Ordinary list sharing was verified
to exclude removed reports, private lifecycle/generation history and peer-only
Lineage originals while preserving local history. UI and final release gates
listed above remain open; a future explicit history-sharing option is not provided.


## Version catalog and desktop controls

`lineage_versions.collect(owner, *, limit=100, offset=0) -> dict` is worker-only
and read-only. It lists distinct actual generated/imported/native scientific rows,
including import-displaced content and locally removed versions. `items` retain
`row`, actual `origin` where proven, exact `current` equality and whether the
corpus slot is `occupied`. `more`, `offset` and `total` support bounded paging.
Source bytes are not read, AI is not invoked and no source/identity grant is made.
Missing provenance can leave historical data browseable with no direct restore
origin; the app must request reviewed adoption rather than fabricate one.

The desktop picker starts at **Current analyses**. Choose **History** for retained
versions and use **Older/Newer** for additional pages. The same selected content
remains visible across a successful remove/restore. Confirmation is cancel-first;
source, observed row/absence and owner are checked in the actual transaction.
Buttons disable during work; stop, close and a changed reading context cancel
admitted writes before commitment and drain the worker. A committed change whose
follow-up refresh fails reports saved/refresh-needed instead of claiming rollback.
Actions report through the existing activity area and never require an AI login.
If that post-commit refresh fails, lifecycle/source controls pause until a fresh
read succeeds; completed changes cannot be described as cancelled by a late stop.

Restore is disabled while a current row occupies the corpus slot, or when the
selected historical content lacks maintained provenance. An enabled button is
not a source permission: changed source/parent lifetimes still refuse on submit.
Current reports retain their existing exact-original readers. Noncurrent
historical versions can open originals through the independent history proof
boundary below. A listed provenance enables an inspection attempt, not a source
grant: all actual source/paper lifetimes and file bytes must still verify. No
activation or current-PDF substitution is performed.

Whole-workspace detached recovery keeps protocol data archived. Its editable
copy exposes archived reports in the version catalog as data without a runtime
origin; detached JSON does not become a live historical source proof. Current
reports receive fresh native origins through actual verified enrollment.


## Historical original API

`lineage_history_originals.prepare(owner, row, origin, source_id, *,
cancelled=...) -> Original | None` is worker-only. It requires the actual loaded
owner and an exact retained generated publication, receiver import receipt or
native scientific put. Original grants and selected-paper/source incarnations
must remain valid even if the scientific report is removed or replaced. It
verifies bytes off the UI thread and returns a sealed process-local proof, never
an exported permission, device identity or restoration operation.

`for_delivery(proof, owner, row, source_id) -> bytes` rechecks identity, exact
selected provenance, source ownership and file observations before returning
immutable verified bytes. `metadata_current(proof) -> bool` is the read-only
native/SQL/file metadata guard used by the open source window; it does not hash
PDFs or write research. Lost ownership, replaced files, a recreated paper/source
or missing original provenance invalidate the proof.

The desktop also rechecks the selected origin at delivery, not just equal-looking
report content. It uses the separate historical reader only for noncurrent
versions; current rows and ordinary package exports retain their existing strict
reader selection. [Concrete behavior scenarios](testing/lineage-historical-original-scenarios.md)
cover all three origins, old/new version separation and delayed UI delivery.


## Fresh editable recovery integration (development)

The normal workspace enrollment and detached recovery entry points now retain
current generated, imported and native Lineage, verify their actual original
PDFs, and publish genuine fresh native source/scientific baseline operations.
They retain old generation/import/lifecycle receipts and nested native history
as archive data, without installing the old workspace or device identity.
Current and ancestor enrollment identity collisions are rejected. Source
retirement, replacement and recreated parents cannot supply current authority.

The recovered version catalog also exposes displaced native reports as readable
archive rows with no runtime origin. Current content uses its new native origin;
this does not enable direct restoration using an old device's permissions.
See [behavior scenarios and evidence](testing/lineage-enrollment-scenarios.md).
These latest integration results supersede earlier temporary enrollment blockers
described above; arbitrary live package admission and installed-device/hosted
acceptance remain separate gates.
