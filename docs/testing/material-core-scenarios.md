# Material collection and independently retained originals

Updated 2026-11-01. Isolated0.5.0.dev; unreleased. This is a verified read/collection
foundation recorded before the UI integration. Current [material UI evidence](material-ui-scenarios.md) supersedes the earlier missing-adapter status below.

## What is exercised

| Situation | Actual action | Required outcome |
| --- | --- | --- |
| Read a material from A after primary B replaces it | Real local/managed collector, actual retained original ownership, exact immutable item selection and independent PDF read. | Read byte-exact independently owned A; never choose B or a different paper's matching hash. |
| Source not retained | Collect actual source with no separate original owner. | Keep every scientific item; explicitly mark historical reading unavailable instead of inventing ownership or deleting the list. |
| Select the wrong or modified item | Supply a foreign key or altered payload to the captured collection. | Refuse. A bare dictionary/hash is not a historical source permission. |
| GUI selection/status checks | Forbid SQL, JSON parsing, hashing and PDF parsing during small/native admission. | Exact selection/native status still works without heavy work on the GUI thread. |
| Retained bytes or metadata changes | Actual same-byte writes with restored mtime, source retirement, incomplete CAS, foreign bindings and native DB/index changes. | Revoke/refuse changed original authority; unrelated note writes allow worker revalidation of the same capture. |
| Use existing read ownership | Read real paper lifetime/marks through readonly connections, with initialization/writer functions forbidden. | No schema/identity/receipt creation and no research write; missing lifetime/native/paper refuses. Existing highlight editing defaults still pass their old tests. |
| Collector globals point elsewhere | Capture real loaded A and explicit database/path roots, then point globals to a separate real fixture database/root. | Collect A's correctly located headings; original SQL and all other-workspace bytes remain unchanged. Derived caches may be written only under the captured source roots. |
| Reader retains A while B is desired | Attach A, capture its real loaded source, attach B, then collect from A off-GUI. | A remains the collection source, despite not being desired; B is not relabeled as A. |
| Cancel or change used source | Cancel before source/DB observation, or actually mutate the source with restored mtime. | Refuse early/stale work without relabeling content or writing research. |

The source library preserves every supported scientific payload (exhibit/table
rows, headings, sentences, anchors, reasons and IDs). Its sealed Collection,
Selection and OriginalProof are process-only, immutable and non-pickleable;
they are not fields in Materials/asdict or MIME/sync/package JSON. The actual UI
must still attach/select them through its private collection context.

Historical ownership is independent of the mutable primary alias. At capture,
used A bytes must match genuine retained A. After capture, replacing primary B
does not invalidate A merely because the alias changes; retained A's own native
bytes, receipt/operation, parent and workspace binding remain guarded.

## Exact local evidence

- Current core integration: **48passed,0failures/errors/skips**,108.49s pytest /
  109.70s wrapper,924 source/test/script inputs unchanged. Includes new material
  source, scoped collector/read-owner controls and maintained material/source
  normal behavior. `build/material-source-core-integration-result.json`.
- Earlier readonly owner + maintained highlight editing:58passed,74.64s pytest /
  75.67s wrapper,921 inputs unchanged. Earlier generic viewer lifecycle:8passed,
  49.73s pytest/50.89s wrapper,920 inputs unchanged. They are different source
  snapshots, not extra cases to add to48.
- Independent frozen backend:27passed,92.26s pytest/93.204s wrapper. Root admitted
  only its two new files;14 dependencies were exact. Root's changed materials.py
  retained the exact scientific dataclass and passed explicit compatibility and
  scope checks; no older shared dependency was copied over it.
- Ruff passes. All existing pre-checkpoint test files remain unchanged. No model,
  account, network, installed Mac/phone, installer or owner's research database was used.

## Preserved development admissions

The first new read-owner legacy fixture omitted mandatory title_key; only that
fixture field was corrected. New scope fixtures initially omitted actual parent
initialization, then used a general managed-reader fixture without desktop capture
installation. The new fixture now uses a real CaptureConnection transaction,
capture installation and genuine owner initialization **before** the tested
readonly operation. No old behavior assertion was weakened. The plain general
managed-reader fixture itself remains unchanged.

A real old-call compatibility regression was also found: passing cache_root to
an unscoped legacy cached-reader call broke its maintained seam. Code now sends
new options only for an explicit scope. Existing tests/assertions were retained;
the11-case maintained material selection passed after that fix.

All first failures remain in ignored build logs/receipts. Readonly observation
does not repair an incomplete desktop workspace, create a lifecycle or install
capture. The actual UI must preserve the earlier loaded-owner/request context;
capturing an epoch for the first time on a delayed worker is insufficient.

## Earlier missing UI (now superseded by selected integration)

At this earlier core checkpoint, the native audit reproduced: collect A -> actual Use Latest B -> click the
stale A material -> zero independent original viewers. B, drafts and saved state
remain safe. The backend passing above does not turn that UI audit green.

The next step at that checkpoint was owned background collection, typed Panel item selection, distinct material
snapshot/view adapter and parent close/update barriers. See the
[integration contract](../material-source-integration-plan.md). Complete sync
writers/history/recovery, mobile, production identity/hosting, full check and
physical Windows/Mac/phone acceptance remain v0.5 requirements.

The existing local-integration ownership/lifetime patterns cover this evidence;
no new global skill rule or installation is claimed.
