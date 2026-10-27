# Retained-work review

This slice implements the ADR 0011 review operation layer and a desktop dialog
opened from Research data → Review retained work. It does not complete v0.5.

## Supported decisions

| Origin | Preview | Apply | Keep / copy / export |
|---|---|---|---|
| Generated SQL candidate | Original, current, retained text | Closed generation registry; exact displayed base | Yes |
| Remote note / research-content put conflict | Original when retained history exists, current, incoming | Explicit `resolution_of`, exact displayed head and parent state | Yes |
| Typed compound producer candidate | Original/current/retained group | Exact displayed group; explicit target selection | Yes |
| Raw SQL capture candidate | Whole original/current/retained mutations | Disabled; no generic SQL replay | Yes |
| File candidate / draft | Validated manifest or draft metadata; available original/current manifests | Disabled until verified asset/revision application is implemented | Yes |
| Owned generation recovery sidecar | Validated retained output and available current target | Explicit target selection and confirmation | Yes |
| Detached recovery records | Supported research provenance; unsupported types explicitly identified | Disabled; old-device operations are never activated | Yes |

Missing original history is shown as unavailable. It is never inferred from the
current row or current PDF. File metadata preview does not claim that asset bytes
were loaded or verified. Copy/export produces bounded readable research text and
the original source hash, excluding local paths, generation input receipts,
workspace configuration and credentials. Exports exclusively create the chosen
file; they do not overwrite an existing file. Viewing and deciding never call AI.

Typed citation, followup and resource groups now use the same review entry with
read-only grouped previews and atomic application. Historical source hashes remain
attached; restored or differing targets require confirmation. See
[Compound retained-work review](compound-review.md), including its explicitly open
legacy PDF backup-adoption gate.

## Displayed-base application

`ResearchReview(explicit_database_path)` pins the database's filesystem identity
and enrollment binding. `preview(origin, id)` returns an immutable, session-sealed
snapshot. The GUI retains that snapshot while the user edits the draft; Save does
not recapture a newer base. Mutation, queued sync operation and review receipt
share one transaction. A stable request ID makes an exact retry return the original
result; changing the draft or decision under the same ID is rejected.

Generated application preserves the candidate's original source-document hash.
It checks the displayed SQL row, graph observation, selected parent row, local
lifecycle epoch, database identity and workspace binding. A failed comparison
leaves research and outbox unchanged and keeps the GUI draft visible. The user may
explicitly review the latest version while retaining the draft, then decide again.

Remote application calls `SyncClient.resolve_conflict_in(conn, sequence,
expected=displayed_observation, ...)`. This transaction-owned seam checks the
canonical head, parent state and outstanding operations before constructing and
saving the normal resolution envelope. Existing `resolve_conflict` behavior is
preserved. Keep current records a **local review decision**; it does not claim a
remote conflict has been resolved by the authority.

## Offline target selection

Legacy candidate contexts cannot retrospectively prove a parent's incarnation.
The review therefore offers **Choose target**, shows a bounded page of titles and
IDs, loads that target's current content, and requires a separate confirmation on
Apply. This explicitly reattaches the retained result; it does not assert that old
and new parent identities match. The original source hash remains unchanged.

`research_lifecycle.ensure_lifecycle(conn)` installs device-local epochs inside a
caller-owned transaction, independently of sync enrollment. Subsequent calls
check the installed schema without rescanning all papers. `parent_lifecycle(conn,
kind, id)` reads the active token. Insert, replacement, deletion and ID changes
invalidate an old token; ordinary metadata updates preserve the epoch. The review
also compares the displayed parent row, so renamed targets require another review.
Callers must install the helper **before** capturing new work. It cannot establish
historical identity for already-created legacy contexts.

The capture authorizer allows only INSERT/UPDATE from the helper's exact named
triggers into `research_parent_lifecycle`; arbitrary direct protected writes remain
denied. Both lifecycle records and `research_review_receipts` are included in
recovery archives as protocol provenance. Detached restore does not reactivate old
epochs, review operations, device identities or enrollment. New local epochs are
created when the restored workspace is reviewed.

## Desktop integration

```python
from paper_daily.desktop.review_dialog import ReviewDialog

dialog = ReviewDialog(explicit_database_path, parent=window, language="zh-TW")
dialog.show()
```

The host must retain the dialog and close it before switching workspaces. A closed
service rejects new writes; delayed previews are discarded and cannot update a
different selection. Preview and research-application operations run outside the GUI thread.
Private draft flushes have bounded serialization and SQLite lock waits.
The lists use bounded pagination; native keyboard navigation, text selection,
copy/paste and undo remain available. No background result steals focus. Narrow
windows stack navigation above the text tabs; splitters remain adjustable.

Draft text, cursor and preview are retained when switching items. Edited drafts
also persist across close/restart with their original displayed base, source hash
and workspace ownership. Stale drafts require explicit refreshed review. A failed
close flush keeps the dialog visible; the host must honor `close()` returning
false. Separately saved variants remain accessible in the bounded draft picker.
See [Durable edited review drafts](review-drafts.md) for storage bounds, corruption
handling, API details and the detached recovery contract.

## Evidence and remaining work

Fixture tests cover actual generated application, original source hashes, stable
retries, concurrent edits, failed receipt rollback, original-workspace isolation,
database replacement, explicit offline target choice, delete/recreate and
replacement epochs, remote resolution over the reference authority, grouped
read-only adapters, detached backup provenance, and real Qt cancellation/rapid
activation/late-preview behavior. Exact commands and final counts are supplied in
the integration handoff manifest. No real account, research database, paid model,
cloud deployment or public upload is used.

MainWindow retains one dialog per workspace, focuses it on repeated activation,
and prevents parent teardown while the review remains open. Workspace-change polling
closes the old pinned service, honoring a rejected close. Thirteen combined native
entry/dialog tests passed. Durable edited drafts now preserve their displayed base across restart; see the
draft handoff for its separate fixture evidence.

Pending integration: shared QA review navigation, verified artifact application,
typed conversion of raw capture candidates, legacy PDF backup adoption, and richer
conflict target choices. These are open ADR requirements, not completed
capabilities. Native macOS/Linux rendering and the merged full check remain release
gates. Windows offscreen synthetic screenshots are recorded separately.
