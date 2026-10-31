# v0.5 delivery status

Updated 2026-10-31. Branch: `feature/0.5-sync-foundation`; build identity:
`0.5.0.dev`. This is an unreleased local candidate. The v0.4 maintenance line
remains separate; daily research and installed apps have not been migrated.

## Recorded baseline and candidate gates

Recorded full-gate baseline: **06183e1**. Its complete frozen gate passed on 833
inputs: **4,294 Python/desktop, 18 frontend, 198 mobile tests and four actual HTTP
programs / six acceptance checkpoints**. Privacy/Ruff passed; no input drift.
Evidence: `build/research-source-closure-full-4.log` and its frozen input receipt.

Work after that baseline remains an unreleased development candidate. An earlier
complete attempt on 890 inputs stopped at **2,302 passed / one Windows native
database-replacement failure**, before frontend/mobile phases. Native observations
found retained compiled statements around closed connections and a separate
wrong-workspace background poll. Scoped observers now land on maintenance first;
their contextual 0.5 integration must pass its own complete gate. Neither green
subsets nor the separate finding alone establishes the original failure's cause.
No retry, sleep, cache disabling, test skip or weakened assertion masks it.
A later frozen 973-input attempt stopped at **1,125 passed / one initializer
failure**: an optional content initializer attempted to install a PDF-position
cleanup trigger before the caller had created its paper table. The parent-presence
fix preserves the original transaction tests and adds parent-later/rollback/retry
coverage; its affected selection passed 86 cases. No source or font drift occurred.
The earlier Windows replacement case was not reached, and frontend/mobile did not
run. A subsequent frozen 984-input attempt stopped at **2,210 passed / one legacy
note-migration failure**, before frontend/mobile. The second caller installed the
same optional position initializer without a paper table. Its parent-presence
fix passed 48 affected cases, including the unchanged original note migrations
and new parent-later, rollback/retry and malformed-schema behavior. The later
position/Inbox integration rechecked those migrations. These failures are retained
in the gate ledger; neither focused pass certifies the complete candidate.
These fixes require a new frozen full gate; its receipt must match the eventual checkpoint.

The next attempt was stopped during admission when four required local parser
assets were found to be ignored by Git. Scoped inclusion, pinned license/hash
checks and an actual autocrlf-enabled checkout regression now preserve their
upstream bytes. The following complete attempt on 1,054 source inputs plus two
runtime fonts stopped at **5,463 Python passed / one workspace-observer lifecycle
failure**, before frontend/mobile. All frozen inputs remained unchanged.
Controlled Qt/SQLite regressions subsequently showed that an old MainWindow and
its notification/update callbacks could still read the next global workspace.
The watcher-only guard is insufficient. The bounded common window fix is now on local master as `e926be9`, after
1,527 Python passes, one existing conditional skip and 24 frontend passes;
470 source inputs and two fonts stayed unchanged. Its contextual 0.5 integration
is now present with reader preparation lifecycle barriers. These findings do not establish the cause of the earlier
native replacement failure.

After that gate ended, 39 reviewed paths integrated the dependency lock,
checkout-byte controls, editable-recovery ownership, reader review fixes and
mobile source-preservation API. Their backend selection passed **77 Python,
447 mobile and eleven actual HTTP programs / nineteen checkpoints**, in 343.3s,
with Privacy/Ruff and all 39 afterimage hashes unchanged. This is a partial check:
desktop reader acceptance and a new combined complete gate remain required.
The read-only saved-reader helpers first passed a combined 370-case canonical
selection in 493.9s. Bounded background chat preparation is now wired into
ReaderPage with atomic transcript/snapshot/pending-action delivery and explicit
restart/update/close barriers. Its combined canonical selection passed 205 Python,
476 mobile tests and nineteen HTTP checkpoints in 214.1s; all 29 integrated
afterimage hashes stayed unchanged. These overlapping partial checks do not
certify the complete candidate or the still-synchronous deep-reading paths.

The next frozen full gate on 1,089 source inputs and 87 runtime assets stopped
at **1,239 Python passed / one restart compatibility failure** in 1,044.7s total.
The new preparation barrier assumed that the reader already existed before the
active-sync restart check. Source and asset hashes stayed unchanged; frontend
and mobile did not run. A narrow optional-reader correction retains the existing
stop-and-wait behavior. The affected canonical gate passed 136 Python cases in
98.3s, including actual preparation/window lifetimes and every original sync
assertion. The new complete feature gate remains required.

The subsequent frozen full gate on 1,107 source inputs and 87 runtime assets
stopped at **4,405 Python passed / one review-retirement failure** in 5,506.7s
wrapper time. Frontend and mobile did not run; all frozen inputs stayed unchanged.
The stale-window guard prevented retiring the previous workspace's review. The
narrow correction closes that pinned review before refusing new workspace reads;
its canonical selection passed **100 Python cases in 107.3s total**, including
save failure/retry and closed-window controls. These are not a full-suite pass.

A later reviewed batch adds pending-comparison reading continuity, readable report
labels, honest output-budget/reported-model metadata, inactive lineage validation
and capture helpers, and operation-scoped recovery schema metadata. These still
require the combined complete gate. Progressive figures are now integrated after
207 isolated cases passed in 623.2s, with all 1,131 frozen inputs unchanged. The
original reading-state regression and a retry-notice regression are corrected;
images and TOC survive ordinary reading/note writes through one bounded read-only
source check. Hard source changes still revoke. This focused result does not
certify the complete feature candidate; existing ready-to-deep-dive work remains
synchronous. See [progressive figures](progressive-figures.md).

Each checkpoint's commit and ignored build receipt record its matching validation;
the roadmap does not substitute for that gate or for release acceptance.

The professional-reading union passed **203 canonical Python cases in 126.5s**,
with all 18 integrated afterimage hashes unchanged. The later lifecycle correction
removes a cached-result/job reference cycle without GC or source-guard changes;
its producer gate passed 253 cases. The modeless comparison view and accepted-close
release have separate focused evidence (167, 80 and 36 cases, overlapping), now
composed into one five-path integration. These are partial gates; the matching
complete checkpoint result belongs in its commit and ignored build receipt.

## Current capability map

| Area | Integrated local candidate | Still required |
|---|---|---|
| Sync | Authenticated reference authority, atomic journal/cursor, conflict retention, opt-in session sync, peer-device controls | Production identity/pairing, hosting and operator acceptance |
| Originals/offline | Verified hashes and ownership, selected downloads, resumable transfer/verification, exact historical-source viewing | Installed native-store and physical-device acceptance |
| Existing research | Copy-based enrollment; nullable list notes; typed goals, references, pins, claims/annotations, Q&A links and supported histories | Remaining unsupported compound/review/integration/file variants; no silent flattening |
| Legacy reading | Queue/log identity, ranks, context, exact Markdown and typed queue pins; import conflict provenance and repeated recovery | Explicit upgrade/copy for older unsafe runtime triggers; combined full gate |
| Recovery | Independent inspected backup, detached restore, fresh editable copy, bilingual desktop inspect/copy/open flow | Remaining unsupported scopes and final cross-device journey |
| Specialist reading | Study-design-aware task drafts, per-list purpose, source-pinned claim extraction and original lookup | Grounded-lineage preservation/reader integration and complete A1/A2/A3 audit |
| Evidence review | Deterministic desktop/CLI/MCP checks; editable-deck checks; explicit claim appraisal and private saved reviews; temporary desktop fact/statement comparison with requested/reported model distinction | Remaining corpus/CLI adapters, persistent fact-sheet workflows, idle continuity and human evaluation |
| Reading continuity | Saved-activity desktop/mobile view; source-bound native position save/resume with exact-original list-package support; desktop/mobile Inbox; source-preserving v2 snapshots and pinned offline PDF page parser | Combined runtime/full gate and physical-device acceptance |
| Maintenance | Scoped observers, wrapping header, completion/citation/preference/source-status fixes and display discovery cache | Feature full gate, master ancestry reconciliation and remaining synchronous reader/thumbnail paths |

Model appraisal is a review proposal. Located quotations establish location, not
semantic support. Note/answer source association uses actual saved anchor/Q&A
identity; missing versions remain unknown and old sources are never relabelled.
Opening saved evidence/reviews makes no model call. Explicit model work captures
its route and budget; no account or paid fallback is silently substituted.

## Exact recent focused evidence

These are overlapping selections, not a summed total or a completion percentage.
A focused pass never replaces the matching complete gate. One early full attempt
was stopped after identifying four required parser assets omitted by an old
vendor ignore rule. The scoped whitelist and clean-checkout regression now retain
those exact pinned files and their license; unreviewed downloads remain ignored.

| Selection | Result | Evidence |
|---|---|---|
| Legacy core/mobile integration | 173 Python, 273 mobile; seven HTTP programs / nine checkpoints; 312.9s total | `build/legacy-mobile-canonical-focused.log` |
| Model appraisal/routing integration | 348 Python including CLI/MCP; 321.1s total | `build/appraisal-canonical-focused.log` |
| Saved SQL output audit adapters | 119 Python; 160.6s total | `build/audit-sql-canonical-focused.log` |
| Model reply caller compatibility | 272 Python; 356.4s total | `build/json-callers-canonical-focused.log` |
| Topic/bibliography reply compatibility | 72 Python; 12.8s total | `build/reply-json-canonical-focused.log` |
| Study-design-aware task drafts | 41 Python; 20.7s total | `build/professional-task-types-focused-2.log` |
| Captured translation/selection/math behavior | 123 Python; 411.7s total | `build/translation-canonical-focused.log` |
| Native positions, Inbox and restart/update union | 248 Python, 368 mobile; ten HTTP programs / twelve checkpoints; 511.7s total | `build/continuity-r4-canonical-focused.log` |
| Study-design prompts and supported-question outcome | 170 Python; 127.9s total | `build/study-design-canonical-focused.log` |
| Background chat, window lifecycle, native positions and mobile union | 205 Python, 476 mobile; eleven HTTP programs / nineteen checkpoints; 214.1s total | `build/joint-reading-mobile-canonical-focused.log` |
| Mobile page dialog, native citation scope and entry fixtures | 26 Python, 476 mobile; eleven HTTP programs / nineteen checkpoints; 43.7s total | `build/mobile-entry-citation-canonical-focused.log` |
| Combined reader saved-input/reentry/source/layout integration | 370 Python; 493.9s total | `build/reader-preparation-canonical-focused.log` |
| Recovery, phone-first source retention and checkout/lock integration | 77 Python, 447 mobile; eleven HTTP programs / nineteen checkpoints; 343.3s total | `build/continuity-next39-backend-focused.log` |
| Clean-checkout pinned parser/license inclusion | 40 Python; 4.7s total | `build/pdf-parser-distribution-focused.log` |
| Portable positions and offline parser integration | 86 Python, 412 mobile; eleven HTTP programs / nineteen checkpoints; 121.0s total | `build/position-snapshot-parser-canonical-focused.log` |
| Editable-deck source audit and worker admission | 101 Python; 208.1s total | `build/deck-audit-canonical-focused.log` |
| Legacy note-position migration | 48 Python; 64.1s total | `build/position-store-init-focused.log` |
| Pocket reader PDF.js eval guard | 1 Python, 6 frontend; 4.3s total | `build/pocket-feature-focused.log` |
| Optional position initialization/transaction guards | 86 Python; 148.4s total | `build/position-init-canonical-focused.log` |
| Saved note/Q&A source adapters | 131 Python; 163.1s total | `build/audit-source-links-canonical-focused.log` |
| Editable-recovery desktop flow | 67 Python; 69.8s total | `build/recovery-ui-canonical-focused.log` |
| Closed-review PDF lifetime | 45 Python; 74.1s total | `build/audit-lifetime-canonical-focused.log` |
| Typed queue-pin integration | 178 Python, 318 mobile; nine HTTP programs / eleven checkpoints; 546.1s total | `build/queue-pin-canonical-focused.log` |
| Guarded position core/native union | 230 Python, 318 mobile; nine HTTP programs / eleven checkpoints; 379.4s total | `build/reading-position-canonical-focused.log` |
| Maintenance feature-context union | 91 Python; 243.9s total | `build/common-maintenance-canonical-focused.log` |
| Native Escape/result/modal lifecycle | 53 Python; 150.7s total | `build/audit-escape-focused-3.log` |
| Recorded activity/native worker proofs | 97 Python, 294 mobile; eight HTTP programs / ten checkpoints; 167.6s total | `build/activity-responsive-canonical-focused.log` |
| Queue-pin inspection honesty | 24 Python; 52.5s total | `build/recovery-pin-inspection-green.log` |
| Display discovery/connection identity | 31 Python; 5.2s total | `build/maintenance-canonical-focused.log` |
| Planning/usage/distribution docs | 44 Python; 2.7s total | `build/current-planning-docs-focused.log` |

Privacy/Ruff passed for these maintained canonical selections. Native bilingual,
light/dark and compact review/recovery fixtures were inspected. A closed review
releases its sealed PDF capture after work drains; saved results remain. No real
account, paid research call, native vault, daily data or production service was
used in these tests. Screenshots and fixture passes do not prove installed Mac
or mobile behavior.

## Immediate integration work

- Maintenance commit `987c365` is on master after its complete gate. Its scoped
  watcher, wrapping toolbar and SDK-fixture provenance are contextually present
  in the feature, retaining observed writers and existing main.py edits. Feature
  compatibility passed 91 cases; complete the frozen full gate and remaining
  semantic master merge.
- Recorded activity is integrated with worker-only SQL/hash verification and
  native/reader/draft guards. Ordinary legacy paper-open I/O remains a separately
  identified maintenance gap; this panel does not make that path asynchronous.
- Typed queue pins now have canonical focused coverage for initial copy, actual
  writer, packages, durable conflict provenance, repeated recovery, independent
  mobile validation and older-receiver refusal. Include this union in the frozen
  full gate. Older unsafe runtime triggers still require explicit installation or
  an independent copy; no automatic read-side repair is provided.
  See [the handoff](queue-pin-migration.md).
- Saved explanation-link, research-question and context adapters are integrated.
  Their closed provenance keeps input digests separate from PDF identity; a changed
  linked highlight never supplies a replacement quotation. New categories remain
  outside paid appraisal selection, preserving older eligibility. Selected editable
  decks now have bounded source-version checks and real worker/restart admission
  tests. List/corpus, lineage and consistency/fact-sheet coverage remain separate work.
- Model-reply parsing now tolerates validated prose/fenced wrappers in bounded
  legacy callers. Scientific/source validators, captured routes, writers and saved
  JSON parsers retain their boundaries. Mixed scalar/object citation/followup
  arrays are rejected whole instead of silently accepting a subset.
- Finish grounded-lineage source/history and reader integration, remaining writer/
  history gaps and the full analysis audit. Preserve source bytes and explicit
  unsupported states throughout sharing and recovery.
- Native source-bound position save/resume, exact-original list packages and the
  desktop/mobile research Inbox are integrated. The sealed editable-recovery
  bridge now supplies verified fresh receiver-local position ownership within the
  caller's atomic transaction. Joint preservation tests cover original A, current
  B, Inbox histories and fresh enrollment through repeated recovery cycles.
  Invalid or retired ownership still refuses adoption without partial writes.
- Source-preserving v2 snapshots, independent wire validation and the pinned
  local PDF page-count parser are integrated. Phone-first primary-source
  retention and explicit page-save/recovery operations are now integrated at the
  API layer, including changed-source-incarnation quarantine. The manual page
  dialog is now integrated after twelve exact-source browser checkpoints for
  source changes, native Enter/Escape, offline recovery and the real app's
  PDF-card/note-draft flow. Its combined canonical selection passed 26 Python,
  476 mobile tests and nineteen HTTP checkpoints in 43.7s. Native PDF viewport
  observations and reliable automatic page jumps are not implemented. These
  operations preserve the exact selected original rather than relabelling it
  after replacement; installed/physical-phone acceptance remains separate.
  Recorded activity is distinct from last-opened/page observations.
  See [the position handoff](reading-position-handoff.md).
- Reader review fixes are integrated for stale-dialog reuse, rejected source
  jumps reported as success, and inaccessible text beyond a preview limit.
  Isolated native geometry and interaction checks passed, including complete
  expandable text at compact widths. Canonical reader checks and the full gate
  remain required; no new default toolbar was added.
- Saved chat now uses one owned preparation worker plus one replaceable pending
  request. SQL, source-byte verification and Markdown run off the GUI thread;
  the transcript, typed Q&A identities and pending actions install together.
  Busy ownership continues through queued GUI delivery. Restart/update/close
  barriers drain this work, preserve drafts and retain the existing position
  cancellation-on-close behavior. Source interference permits only one bounded
  semantic recheck; a native WAL checkpoint is not a research replacement.
  Deep-reading figures, PDF words and legacy cache previews remain separate
  preparation gaps; their existing display has not been replaced by partial HTML.
- Native citation buttons and map callbacks in the current widget presentation
  now retain their displayed paper/list and native database lifetime; repeated
  card submissions are single-flight. Actual original-module controls reproduced
  wrong-paper edits, a map submission to the next list and queued next-workspace
  reads. Typed edit writers remain unchanged. The common graph callback scope
  is now committed on local master as `8bc4a3b`: 1,549 Python and 24 frontend
  passes, no skips; 471 source inputs and 87 public runtime assets unchanged.
  The native 0.5 adaptation passed 163 Python cases in 99.5s, including unchanged
  typed editors, window lifecycle and entry behavior. Actual Graph-button and
  queued-preparation regressions then exposed stale-list first-view behavior. The
  three-method correction passed 92 affected cases in 65.2s and is now integrated;
  all fourteen prior native-map test functions remain unchanged. The complete
  feature gate remains required.
- An older claim-entry fixture lacked the new view/native metadata and a genuine
  source. Its sole test-file adapter now uses a real PDF, resolver and successful
  native passage selection. All fifteen original assertion ASTs remain intact;
  the combined canonical entry/citation/mobile selection above passed.
- Freeze one coherent candidate and run `scripts/check.py` completely. Verify
  input hashes before committing; do not commit on red, publish or bump versions
  merely because a partial candidate was repaired.

## Separate maintenance gate

Maintenance commit **987c365** passed its complete frozen gate on 464 inputs:
**1,471 Python/desktop passed, one existing conditional skip, 18 frontend passed**.
Privacy/Ruff and both pinned public font hashes passed without source drift. The
clean maintenance worktree fast-forwarded from `94566d1`; no release, push,
version bump, daily-app restart or research-data migration occurred.

The official MCP SDK fixture explicitly pins the child source while retaining
exact tool/persistence assertions. Native toolbar fixtures now exercise user
control before resizing and assert actual wide dimensions: a real observation
showed the startup fitter shrinking 1800px to 796px on the 800px synthetic screen.
Every old assertion remains, and the ineffective product size-policy experiment
was reverted. Feature contextual integration passed 91 relevant Python cases. These
maintenance/partial counts do not certify the complete 0.5 candidate or physical devices.

Maintenance commit **97c0676**, based on 987c365, also passed its complete frozen
gate: **1,472 Python/desktop passed, one existing conditional skip and 24 frontend
passed**, with 467 inputs and both pinned fonts unchanged. It disables PDF.js
evaluation in both display and extraction paths of newly exported pocket readers.
The same four paths are contextually integrated into the feature and their affected
checks passed. Existing exported HTML must be exported again to receive the fix.
No release, push, version bump, daily-app restart or research-data change occurred.

## External release gates

- Choose the hosted service operator, region, budget, identity/pairing/recovery
  flow and encryption threat model. There is no end-to-end-encryption claim.
- Keep device credentials, AI accounts/usage, local preferences and analytics
  consent outside research synchronization. Login alone never uploads research.
- Verify the packaged Windows/Mac/phone offline journey on owned test workspaces,
  including actual Apple Silicon, iOS/Android storage, IME and accessibility.
- Obtain scientific evaluation before accuracy/precision claims. Synthetic model
  fixtures verify software boundaries, not scholarly correctness.
- Publish only after owner acceptance. No production migration, research upload,
  release publication or account action is authorized by this status document.

Implementation history remains in [the session ledger](implementation-0.5.0.md).
The authoritative scope is [the roadmap](roadmap-0.5.0.md); detailed reading
contracts are in [professional workflows](professional-research-workflows.md),
[analysis audit](analysis-audit.md) and [model appraisal](model-appraisal.md).
