# Desktop completion and sync setup — 2026-11-04

Uncommitted isolated v0.5 candidate; not installed, packaged, or released.

## User-visible changes

- References offers a per-run selector: no automatic additional call (default),
  at most one, or at most two. The chosen bound is captured in the CLI command
  before admission to the existing private account/model handoff. It is not a
  global setting for the whole deep-analysis pipeline. Reanalysis is labeled as
  reanalysis; it may regenerate citation answers while retaining manual edits.
- Sync setup starts with saved-connection actions. Manual connection fields and
  advanced joining/details are independently expandable. Collapsing preserves
  field values; expanding does not contact a service. Loading a saved connection
  exposes the required Verify button without starting research synchronization.
- Existing manual sync, credential validation, joining, worker cancellation,
  close/drain and workspace guards are retained.

## Evidence

`desktop-sync-choices-v4`: **51 passed**, zero failures/errors/skips; privacy and
Ruff passed; 63.03 seconds including wrapper; 1,170 frozen inputs, zero drift.
Includes new native selection/stale-control/disclosure cases plus existing sync,
credential-vault, citation view, context-card and CLI tests. Fixtures simulate
providers/vault/service; no real credentials, paid model calls or user research.

Chinese dialog screenshots were rendered with system CJK fonts and inspected.
The expanded state exposes all four connection fields and Verify. The first
collapsed screenshot caught the initial local probe; that image is not evidence
of a persistent busy state. This is Windows offscreen inspection, not macOS QA.

Previous complete gate `v05-completion-full-20261103`: **1,157 passed, 1 failed**,
zero skips/errors; 1,228.16 seconds; 1,168 frozen inputs, zero drift. It stopped at
`test_citation_action_scope.py::test_current_rendered_edit_updates_only_its_actual_saved_reference`:
the legacy HTML harness expects `_rows`, which the native CitesPane lacks. That
file also assumes HTML URLs/RichView scroll callbacks. Preserve its saved-target,
stale-callback and cancellation guarantees when adapting it; do not fabricate
HTML compatibility fields in the app or skip its cases to claim a green suite.
Frontend/mobile phases were not reached. Current full gate is not green.

## Mac handoff

Follow [Apple Silicon acceptance](mac-acceptance-0.5.md). Obtain a matching
candidate arm64 bundle after integration gates are resolved. The existing
`verify_built_app.py` exercises packaged imports/exports and native foreground
activation on Mac. Real Windows/Mac offline sync additionally needs a reachable
test authority and distinct device credentials. No production authority or
artifact was provisioned in this task; no physical Mac run is claimed.

Remaining: integrate whole-analysis continuation policy, align legacy native
view regressions without weakening behavior, pass the full gate, package the
matching candidate, and execute the physical acceptance record. Current changes
reuse established account-scope and local-integration rules; no global skill
promotion or installation is warranted.

Additional check: desktop-private-handoff-20261104 passed 13 cases in 8.86 seconds, with privacy/Ruff and zero drift across 1,170 inputs. It includes the real disposable child-process repeated-click/close test. Twelve cases overlap the 51-case selection; do not sum these as 64 unique cases.
