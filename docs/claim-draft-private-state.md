# Private structured claim continuation

2026-11-02, isolated `0.5.0.dev`, unreleased. **Receiver selection, private saves,
restart and independent recovery now have local backend evidence.** Source
verification/application has since gained [selected backend evidence](claim-draft-application.md);
the desktop form is still required. These methods
are not new buttons or registered CLI/MCP tools yet.

## Shared operations

`ResearchReview` exposes `claim_draft_targets`, `select_claim_draft`,
`save_claim_draft` and `load_claim_draft`. All use its explicit native database,
binding and session; none invokes a model. Run database/PDF work in an owned
worker when connecting the desktop UI. Transport wrappers must reuse these
operations rather than writing their own SQL or generic text conversions.

Selection returns `(preview, encoded_structured_draft)`. It captures the current
paper lifetime/portable identity, actual claim row and graph observation, parent
row and selected PDF descriptor. The retained original claim baseline remains
separate; no current analysis is silently substituted for its original inputs.
Explicit reselection can carry the caller's unsaved structured body.

Private storage uses the existing eleven-column `research_review_drafts` format
with a distinct `claim_resume` origin and closed version-1 expected state. Its
body is validated by the source-bound claim revision codec. It accepts 220 KiB
for this typed origin; older text draft limits remain 200 KiB. Existing total
storage and record/detail budgets still apply. Claim bodies are not free text.

The editor supplies a stable UUID `draft_id` before saving. Repeated identical
saves return one revision; competing updates require the displayed revision.
Separate variants may share a future application request ID, but not their draft
UUID. A closed review refuses a new save. An already-admitted private save may
finish against its pinned owner, preserving work without publishing research.

Restart preserves the exact body, original baseline and displayed receiver base.
It returns `verification_required`, `stale` or `foreign` as appropriate, always
without application authority. A newer claim set is never recaptured behind the
reader's back. An unrelated note does not make a claim draft stale. Native database
replacement cannot reuse the earlier owner's private save authority.

Generic `ResearchReview.decide` explicitly refuses this origin for both Apply and
Keep. Typed source verification/application must be implemented before creating
claim decision receipts. Saved boolean flags and old retry identities are not
permission to write.

## Recovery and read-only inspection

The private-history codec enumerates declared originals from retained/current
claims and the selected PDF, without opening recorded owner paths. An actual
producer/private-save -> complete backup -> detached restore -> editable adoption
-> explicit fresh target -> another private save now passes after the original
folder is physically moved away. This proves private continuation, not published
claim synchronization or a device round trip.

This journey found an existing defect: `ResearchReview.preview` initialized live
parent-lifecycle state even in a detached recovery. That changed the recovered
schema and blocked adoption. Detached previews now remain byte/schema exact;
ordinary live previews still establish their required lifecycle state. Unknown
recovered tables remain rejected. Already-modified detached copies are not
automatically edited or trusted; restore a fresh independent copy when needed.

The local generation-candidate and archived-draft paths are exercised here.
Sidecar and remote-conflict decoding exists but needs its own actual end-to-end
acceptance. Further source, lifecycle, size, cancellation and UI interactions
remain in the full recovery contract.

## Original delivery plan (source/backend stages now have selected evidence)

1. Verify retained A under a receiver-owned source capability while current B
   remains selected; validate edited quotes against those exact captured bytes.
2. Bind a verified revision to the edited draft digest. Apply source, accepted
   claim content, outbox and decision receipt in one caller-owned transaction.
   Repeated requests must not duplicate or overwrite later research.
3. Add the structured desktop form, original/current comparison, source actions,
   private save/restart, confirmation and owned cancellation/close/switch controls.
4. Exercise actual remote conflicts/sidecars, application rollback/retry, independent
   re-backup, offline peer convergence and the remaining typed highlight/deck flows.
5. Complete whole checks, canonical product integration and platform/device gates.

## Exact evidence

Final selected gate: **93 passed, 22 new and 71 existing**, zero failures/errors/
skips; 156.74s pytest / 157.92s runner. The same 981 Python source/test/script inputs
remained unchanged. Whole-tree Ruff passes. This is not the whole application gate.

Development failures remain recorded: an incorrectly timed new fixture was refused
before AI; the corrected fixture changes inputs during the mocked provider call.
The first real recovery found the lifecycle-table mutation. A 92-case run then had
91 passes/one closed-save admission failure; that entry guard and an admitted-save
control were added before the final 93-case pass. No older test was weakened.

Only synthetic PDF/SQLite/workspaces and mocked provider responses were used.
No owner's data, installed Mac/phone, real AI login/model, production service or
telemetry was exercised. The known citation full-gate boundary remains open.

[Human actions/results](testing/claim-draft-private-state-scenarios.md) ·
[Content revision core](claim-draft-resumption.md) ·
[Full recovery contract](review-draft-resumption.md).
