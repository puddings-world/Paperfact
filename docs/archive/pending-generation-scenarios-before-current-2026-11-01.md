# Completed but unsaved presentations

Status: integrated in the isolated development tree; not released. Updated 2026-11-01.
This is a behavior map, not a product-completion percentage.

| User journey | What the tests actually do | Required observable result |
| --- | --- | --- |
| AI finishes while storage is unavailable | Return a fixed valid deck; fail image staging and the independent recovery receipt. | Hold the actual result before UI delivery. Keep the old saved/editor deck. Show an unsaved banner. |
| Save the completed result later | Fail the first retry, then restore storage. | Failure retains the result; success retains one original-workspace draft for review. No second model call. |
| Leave, restart or update | Exercise an actual MainWindow and close/restart/update preparation. | All defer while pending. Cancel preserves the result. Forced termination/power loss remain outside this guarantee. |
| Original view disappears | Destroy the native pane or change database/deck directory before delivery. | No wrong-view write/display; a replacement pane discovers the held result. |
| Export a rescue copy | Cancel the chooser, choose an existing file, then choose a new file. | Cancel/failure retains pending content and never overwrites the old file. Success verifies portable deck/evidence and all used/unused PNG bytes. |
| Discard deliberately | Activate discard twenty times, cancel, then confirm. | One confirmation. Cancel preserves the result; confirm removes only that result, leaving saved research unchanged. |
| Equal request names in two workspaces | Create two actual incomplete results with equal request names and different original owners. | Both remain addressable; discarding one leaves the other. |
| First image write fails | Run actual publication and generation/save; fail the first blob write, reopen, back up, restore and explicitly retry. | Every used/unused image survives before repair, then retry completes without another model call. |

## Current evidence

- Two real producer/UI failures reproduced before connection: the producer swallowed the typed result and delivery discarded it. Receipt: build/pending-before-ui-result.json in the isolated UI candidate.
- First connected selection: 14 passed, zero skipped, 72.44 seconds, no source drift. Four later owner/MainWindow/confirmation/export cases passed, zero skipped, 29.53 seconds. These overlap and use different snapshots; do not add their totals or call them an application-wide pass.
- The reconciled first-write regression on unfixed integration source gives two healthy passes and two fault failures, 18.17 seconds. Both failures occur at independent backup creation because unique images were not retained.
- Original diagnostic observations remain preserved. They required both missing and available images in the same branch, so were not a usable passing regression. Only that newly authored test was reconciled to the consistent preservation contract above. Older maintained tests were not weakened.

## Boundaries still open

The isolated neighboring gate passed 89 cases, zero skipped, 197.34 seconds with unchanged inputs. Reviewed backend receipts are integrated into the isolated root; its independent first-write/receipt selection passed 27 cases, zero skipped, 89.90 seconds. UI integration/current combined gate remain pending. Durable-receipt errors preceding UI delivery need separate review; no broad exception-contract change is implied. Recovery export has a verified read-only reader but no complete app import/review journey yet. Draft/history enrollment, package sharing, live sync/mobile projection and physical-device acceptance remain required. This candidate does not finish v0.5.0.

## Measured cost of this selection

The completed 89-case selection took197.34s. Its slowest case took6.893s and actually replaced a native database while delivering a completed presentation. The actual MainWindow close/restart/update case took6.217s; duplicate delivery preserving a later edit took5.956s. These are measured pytest case times, not estimates of app progress or AI work. SQLite, file reads and native Qt controls run; model responses are simulated. Full-case timings remain in the ignored XML/JSON receipt, not a guessed percentage.

## Current combined source result

The reviewed receipt backend, per-owner namespace isolation and producer/UI
changes are integrated together. The matching nine-file root selection passed
70 cases, zero skipped,313.72s;860 source inputs stayed unchanged. Receipt:
build/retained-generation-joint-root-result.json and matching XML/log. This
supersedes separate partial candidates for this scope; do not add prior counts.

Independent review genuinely reproduced missing unused-figure metadata and
ambiguous owner labels. Rescue export now preserves the full supported scientific
figure/evidence catalog; unknown fields refuse export without clearing the actual
result. Owner labels are precomputed before GUI delivery. A queued settlement
race also reproduced a KeyError and is now covered. One B fixture incorrectly
borrowed A private artifact ownership; it was corrected to genuine captured B
inputs, keeping original assertions and adding capture admission.

All complete-application, rescue import/review and installed-device gates remain
open. No current full check, commit, publish or owner research write is claimed.
