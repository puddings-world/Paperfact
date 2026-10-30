# Observed manual highlight actions

Actual `ReaderPage.load` captures a `HighlightOwner` before loading PDF bytes.
The owner binds the explicit research database path/inode, sync binding (if any),
local parent lifecycle and active synchronized paper incarnation. Opening a PDF
does not enroll a workspace or contact an AI provider.

`manual_highlight_ops.load(owner, path, fingerprint, document=...)` then captures
the displayed document and bounded mark rows with their sync observations.
The reader's add/remove actions use this view; they never resolve a destination
through the latest global database path. An active-workspace mismatch rejects the
UI action and preserves selection, because existing material refresh callbacks
are workspace-global. Direct typed operations remain explicitly workspace-bound.

`add(view, anchor, quote)` checks exact PDF bytes and verifies the selected text
against the same indexed horizontal-word stream as `SelectionOverlay`. Rotated
watermarks are excluded without renumbering words; line-end hyphen joining and
cross-page selection match the actual reader. A repeated identical add is a no-op.

`remove(view, displayed_ids)` deletes manual rows and sets AI `hidden=1`. It uses
the displayed row and graph bases; it does not overwrite a subsequently edited
mark. Repeated removal/hiding is a no-op. Business rows and outbox operations share
one capture transaction, including rollback on source change or storage failure.
An incompletely enrolled DB (a `research_sync_binding` row without enabled capture)
fails explicitly instead of quietly writing unsynchronized research.

AI regeneration owns analysis, quotation and reason; the user owns `hidden`.
Historical AI rows remain available to preserve that preference if a quote returns.
When canonical highlight analysis is known, the visible AI set requires:

- Its exact current `source_hash` and `document_hash`.
- Membership of `source_key` in the current body's numbered items, using the same
  SHA-256 of `page:text` as `pdf_highlights.locate`.
- Matching quotation text and `hidden=0`.

Canonical deletion or an unknown/different PDF hash hides AI rows without removing
history or manual marks. Membership is necessary because unchanged inputs can
produce different selections with the same input digest. Legacy-only workspaces
keep the historical visibility behavior until canonical content exists.

A retained, verified managed PDF A remains editable while PDF B is newly desired;
its anchors stay tagged A. Replaced bytes, workspace identity or parent incarnation
reject edits. Completing an action cannot clear or repaint a newly loaded paper.
No worker/model/login is started for these immediate local edits.

The public `pdf_highlights` compatibility helpers are unchanged. Standalone legacy
reader fixtures that assign a paper directly retain that API path. Actual
`ReaderPage.load` always marks the observed path, including capture failures:
a missing/deleted paper never falls back to legacy writes.

Bounds are explicit: the existing 150 MiB PDF limit, at most 100 pages per selection,
32 KiB quotation text, 5,000 rows per mark table, and a 4 MiB local view snapshot.
SQL byte/count preflights reject oversized legacy content before fetching it.
No new private table, backup record, synchronization kind or credential is added.

Tests use synthetic PDFs and isolated enrolled/unbound databases. They cover real
reader actions, unchanged legacy helpers, rotated/cross-page text, repeated actions,
stale parents/workspaces/bytes, rollback, managed old/new PDF provenance, and
canonical hidden-state membership. Native macOS/Linux interaction and large-file
latency remain release checks; passing these fixtures is not a platform benchmark.
