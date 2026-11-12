# Completed but unsaved presentations: tested behavior

Updated 2026-11-01. Integrated in the isolated development tree; unreleased.
Current combined gate: **70 passed, zero skipped,313.72s**,860 recorded inputs
unchanged. Whole-tree Ruff passed. This is not the complete application gate.

| User journey | What the test does | Required observable result |
| --- | --- | --- |
| AI finishes but nothing can save | Return a valid fixed deck; fail primary image writes, independent receipt and SQL metadata. | The app holds the actual result before delivery; older disk/editor content stays unchanged; banner says unsaved. |
| Retry saving | Keep storage unavailable, then restore it. | Failed retry retains content; success retains one original-workspace proposal for review. No second model call. |
| Leave, restart or update | Exercise an actual MainWindow and its normal preparation paths. | All defer until explicit disposition. Cancel preserves every byte. |
| Original view disappears | Change DB/deck directory or destroy the native pane before delivery. | No wrong-view application; a replacement pane discovers the held result. |
| Export a rescue copy | Cancel, choose an existing file, then a new destination. | Cancel/failure keeps the result and existing file. Success verifies deck/evidence and all used/unused images, including scientific metadata. |
| Unsupported metadata | Add an unknown scientific figure/evidence/paper field. | Export refuses instead of silently dropping data and clearing the result. |
| Explicit discard | Activate twenty times, cancel, then confirm. | One confirmation names the original workspace; cancel keeps content; confirm clears only that result. |
| Equal names in different workspaces | Use equal request/paper/deck names with distinct original owners. | Results remain independently identifiable and disposable. |
| Worker settles during refresh | Settle after the GUI copies its pending rows, before reading a context label. | No KeyError; current editor and saved research stay unchanged. |
| First image write fails | Run actual publication/generation, reopen, back up, restore, then explicitly retry. | All images and full raw explanation survive before repair; retry creates no duplicate/model call. |
| Two DBs share a folder | Create genuine A/B receipts; corrupt or overload B. | A backs up only A; B cannot block A's retention; own limits still reject excess data. |

## Exact selection

- tests/test_pending_deck_results.py
- tests/test_pending_generation_ui.py
- tests/test_generation_incomplete_result.py
- tests/test_raw_retention_stage_loss.py
- tests/test_raw_deck_receipts.py
- tests/test_raw_deck_receipt_namespaces.py
- tests/test_presentation_delivery.py
- tests/test_update_draft_recovery.py
- tests/test_workspace_changes_window_close.py

Result, XML, input manifest and log are in ignored build/retained-generation-joint-root*.
These include unchanged neighboring presentation/update/close controls. They use
synthetic model responses and disposable SQL/files with selected real Qt controls.
They do not certify actual vendor billing, scientific accuracy or physical devices.

## Failures reproduced and retained

- First-write regression: two healthy passes/two genuine backup-loss failures
  before repair; the consistent four cases now pass inside70.
- Actual producer/delivery: typed completed result was swallowed/discarded.
- Independent review: unused figure captions/evidence were omitted at export;
  equal titles concealed original owners. Both genuinely reproduced before fixes.
- Queued settlement: a genuine context-lookup KeyError now has a regression.
- Shared parent: a genuine foreign-owner refusal now has independent A/B controls.

The original newly authored first-write diagnostic mixed observed-bug assertions
with the opposite intended invariant. Its frozen original remains available; it
was reconciled to consistent stronger preservation/backup/retry behavior. Older
maintained assertions were not weakened. The namespace limit fixtures changed
only their two setup locations; all original limit assertions stayed identical.
One new B fixture borrowed A's private artifact capability; it was corrected to
independent captured B inputs, retaining assertions and adding capture admission.

## Timing and remaining limits

The slowest case was first-write failure/publication backup and restore:11.12s.
Foreign excessive-receipt isolation took10.318s; normal publication backup9.959s.
Full per-case timings are in the matching XML/JSON; no percentage estimates app
completion or AI duration. Different earlier selections overlap and must not add.

Rescue-file import/review, remaining source/owner-refusal carriers, full enrollment,
package/live history/mobile scope and physical-device acceptance remain open.
Forced termination or power loss cannot preserve memory-only results when every
storage target fails. No current full check, commit or release is claimed.
