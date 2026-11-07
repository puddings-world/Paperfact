# v0.5.0 implementation status

Updated 2026-11-01. Version: **0.5.0.dev; unreleased**.
The work described here is in the isolated integration tree, based on checkpoint
3843894 with maintenance reconciliation. It has not replaced the owner's daily
release or research database. No new release, push or deployment is claimed.

Start with the [readable acceptance overview](testing/acceptance-overview.html)
and [test scenario map](testing/acceptance-map.md). These explain observable
behavior, not a completion percentage.

## Current delivery state

| User outcome | Implemented evidence | Still required |
| --- | --- | --- |
| Continue research across desktops | Reference sync, transactional outbox, retries, retained conflicts and device controls have local coverage. | Complete supported writer/history enrollment, production identity/hosting and physical desktop acceptance. |
| Read offline and on a phone | Verified originals, reading position and mobile PWA reading/text notes have local coverage. | Installed Apple Silicon Mac, iPhone/Android offline/reconnect journey. |
| Preserve research packages and recover | Supported original/source-aware backups, detached restore, fresh editable recovery and explicit local PDF preparation exist. | Remaining draft/history package/enrollment/review scopes and full installed recovery journey. |
| Keep completed AI output when saving fails | Independent verified recovery receipts, app-owned pending results, explicit retry/export/discard and original-view isolation are integrated. | Enrolled rescue import/review is integrated. Unenrolled local-only receivers, remaining source/owner-refusal carriers and complete portability remain. |
| Keep presentation edits | Actual producer results remain editable; late results cannot replace newer manual content. Retained drafts require explicit review. | Complete history sharing/sync and receiver review coverage. |
| Research with inspectable sources | Per-list goals, source-bound claims and bounded audit/appraisal/consistency slices exist. | Complete grounded lineage producer/review/UI, durable complete-output audit/consistency workflows and portable provenance. |
| Install a public beta | Packaging/update/support foundations remain available. | Current complete check, matching installers, physical device journey and documented service/operator decisions. |

## Latest combined integration gate

**187 passed; 0 failed; 0 skipped; 635.81 seconds of pytest execution**
(637.84 seconds including the wrapper).
Whole-tree Ruff passed before the gate. Its recorded 867 inputs under src, tests
and scripts remained unchanged. This is a scoped integration gate, not a whole
application/build/runtime certificate.

The selection exercises:

- Actual valid result surviving primary image, independent receipt and SQL
  metadata failures; older saved research remains unchanged.
- Exact original bytes and evidence, including unused PNGs and their scientific
  metadata; backup, detached restore and explicit no-model retry.
- Independent workspaces sharing a parent and request name, including malformed
  or oversized foreign receipts; existing per-owner limits remain enforced.
- Actual native UI confirmation/cancellation, duplicate activation, stale/deleted
  views, and MainWindow close/restart/update preparation barriers.
- Existing managed presentation delivery and update/close controls.
- Full rescue-file backend and actual English/Traditional Chinese native import,
  verification, cancellation and explicit Apply, with saved notes/layout/images.
- Exact original A versus primary B, source-cache ownership, stale/changed file
  refusal, cancellation and duplicate-request control.
- Parent delete/recreate before review and during staging; an old observation
  cannot authorize the recreated parent. Ordinary rename still permits review.
- Both unchanged legacy workspace-switch regressions, repaired without treating
  metadata-only retention as durable or dropping the actual incomplete result.

Receipts: build/rescue-import-joint-root-result.json and its matching
XML/log/input manifest. [Detailed behaviors](testing/pending-generation-scenarios.md)
record the failures reproduced before fixes and the precise assertions.
The [rescue scenario map](testing/rescue-import-scenarios.md) explains all 36
new functions / 56 expanded cases in five files. Selections from other snapshots
overlap; do not add them to this total.

## Full-check boundary

There is **no complete passing check for the latest integrated tree** and no new
commit. Historical Full7 at checkpoint3843894 passed6469 Python/desktop,
24 frontend and476 mobile tests, zero skipped. It does not certify this source.

Iteration uses affected behavior tests; integration checks interacting features.
Before completion, commit or release, run the required complete scripts/check.py
against the final source. Do not skip or weaken old assertions to pass a change.

## Next implementation work

1. Complete unenrolled local-only rescue import/review and the portable proposal
   carrier. Current enrolled import is integrated; read-only preview needs no
   enrollment. Never enable sync automatically or restore sender writer authority.
2. Complete original/raw draft migration, enrollment, list packages, recovered
   receiver review and the required live history/mobile scope. A new public package
   regression genuinely shows successful export/import omitting a retained rescue
   proposal, all three images and its owned historical original A while packing
   current B. This isolated RED is not part of the passing 187 selection. The
   [portable proposal design](portable-proposals-design.md) records the verified
   boundary, transaction/ownership constraints and complete adapter acceptance.
3. Finish grounded lineage's saved producer/review/UI and complete audit/appraisal/
   consistency provenance and persistence. Partial helpers are not these workflows.
4. Resolve remaining common maintenance integration/performance issues; preserve
   existing research and the user's/Claude's changes.
5. Pass the current full gate and prepare matching platform installers.

## External acceptance and release decisions

- Record Windows to offline Apple Silicon Mac to phone to desktop convergence,
  interrupted transfer, conflicts, revoked devices and independent recovery.
- Approve production identity/pairing/recovery, hosting/operator, storage/cost
  limits and retention. AI-provider login is not sync identity.
- Decide encryption/key recovery and offline policies. Do not advertise end-to-end
  encryption or unlimited history before implementation and acceptance.
- Record real provider auth/quota checks separately from simulated AI tests.
  No credentials or subscriptions travel with research.

These are explicit gates; local fixture passes do not perform them. Research
correctness, semantic support and scientific influence are not certified by a
located quote, model proposal or green test count.

The [roadmap](roadmap-0.5.0.md) remains authoritative for scope. Earlier chronological
observations are preserved in [the archived status](archive/status-0.5.0-before-current-2026-11-01.md),
including unsuccessful probes. No active goal requirement was removed.
