# Native Lineage import comparison: behavior and evidence

Status: locally integrated development work, 2026-11-14. No release/device/cloud
acceptance is claimed. Existing staged activation/refusal tests remain unchanged
pending the owner's earlier decision; the last full report remains failed.

## Ten native decision cases

`tests/test_lineage_import_review.py`:

| Cases | Actual behavior checked |
|---|---|
| Keep / replace (two) | Full saved scientific body, correct local paper bindings, prior history retained, exact retry adds no duplicate operation |
| Forged or incomplete decision | Raw dictionaries, changed JSON, wrong seal and invalid/missing choices cannot publish |
| SQL changed after comparison | Old approval cannot replace newly changed local research |
| Cancel approved preview | Exact research/outbox/history/receipt rollback |
| Late scientific writer failure | Failure after the row write rolls everything back; reprepare/retry works |
| Different archive | Approval for one fingerprint cannot authorize another package |
| Missing projection marker | Old permission becomes stale; fresh review offers Keep only and does not silently re-enroll |
| Actual peer and backup | Both reports appear in the receiving version catalog, current version is correct, all three exact PDFs bind, independent backup/inspect/detached restore preserve research/history |
| Unrelated package | A valid scientific decision cannot authorize a package with no Lineage content |

## Eight desktop comparison cases

`tests/test_lineage_import_dialog.py` checks actual saved fixture data:

- Both scientific texts, quotations and located-page metadata are visible; Keep
  is the default and viewing makes no research writes.
- Keep and replace (two cases) still require separate final import confirmation.
- Cancel preserves research/mapping and leaves confirmation disabled.
- A workspace switch inside comparison cannot queue publication elsewhere.
- Closing the parent inside comparison drains cleanup once without saving.
- Unsupported ownership offers Keep only, with no restore action.
- Missing model metadata says not recorded rather than inventing a model/version.

The final screenshot uses the same pinned Noto/Fusion setup as app startup and
synthetic papers. It was visually inspected; it is not an installed Mac capture.

## Receive and optional storage

A newly exposed bug was real: two accepted scientific events received together
coalesced into one head, and only that head reached native history. The fix retains
each accepted event before projection, with actual inbox/graph-receipt checks in
the same receive transaction. It grants no file bytes. The peer case checks the
user-visible catalog, current version and exact source bytes, as well as stored
history. Existing generic receive/cursor, prefix, schema rollback, visibility and
shared-version scenarios run in the final affected gate.

`test_lineage_capacity_optional.py` adds two read-only cases: absent optional
storage has room without creating schema; a view masquerading as the report table
fails closed. An old visibility test exposed the missing-table error; its assertion
was preserved while the shared capacity helper was corrected.

## Exact receipts

| Scope | Result and log |
|---|---|
| Initial native decisions | 5 passed in 43.16 s; `lineage-import-review-history-20261114.log` |
| Expanded decision/default-import guard scope | 24 passed in 229.62 s; `lineage-import-review-guards-20261114.log` |
| Comparison plus previous desktop import actions | 25 passed in 147.83 s; `lineage-import-comparison-ui-20261114.log` |
| Final decisions/peer/backup/receive/schema/capacity/version scope | **76 passed in 215.79 s**; `lineage-import-history-final-20261114.log` |
| Final comparison UI and unrecorded model | **8 passed in 71.47 s**; `lineage-import-comparison-final-ui-20261114.log` |

Selections overlap; do not sum them into a release total. Model responses and
workspaces are synthetic/isolated. No live login, paid provider call, publishing,
owner database, actual phone/Mac or GCP resource was used.

## Failure evidence and limits

The first comparison incorrectly compared in-memory nested tuples with their JSON
list representation (one failed, 10.14 s). Canonical JSON comparison fixes that
without removing any binding field. A new test then compared portable history
bindings with local SQL IDs (one failed, 9.14 s); it now uses the maintained identity
conversion and still checks the full scientific body and all local bindings.

The new peer test first failed because native history had one version instead of
two (9.80 s). Its assertion was retained and production receive was fixed. Next,
its new download fixture expected `downloaded`; the maintained artifact API's
terminal state is `bound` (one failed, 11.96 s). The test now requires that stronger
actual binding and reads all exact bytes. The following adjacent gate had 54 pass,
one fail in 63.74 s: old read-only capacity queried an absent optional report table.
The production helper was fixed; no old assertion was weakened or skipped.

Existing beta inbox history backfill is still required, despite raw prior accepted
events being retained. Unowned result adoption, maximum-size/performance checks,
complete audit/recovery, coherent full validation and physical/hosted acceptance
also remain open. [User/API guide](../lineage-import-comparison.md).
