# Understand Paperfact tests

## Start here: scope, not case counts

Updated 2026-11-14. The default development gate is now the curated critical
journeys, not every historical test. See [development checks](../development.md#development)
for commands, budgets and report meaning. Historical results below are dated
snapshots and do not describe the current default or certify the present source.

| Test family | User behavior and failure boundaries protected | Representative source |
|---|---|---|
| Reading and notes | Open papers, save/reopen notes and questions; preserve drafts when navigation or a worker races | `tests/test_reader_chat.py`, `tests/test_list_notes.py` |
| AI routing and analysis | Keep account/model settings isolated; retain durable questions and avoid duplicate delivery | `tests/test_ai_profiles.py`, `tests/test_ai_providers.py`, `tests/test_research_chat.py` |
| Originals and research evidence | Preserve exact PDF/source versions, citation locations, highlights and claim/lineage decisions | The original, highlight and Lineage scenario maps below |
| Slides and attachments | Preserve editable slide content and only activate fully verified attachment closures | `tests/test_sync_files.py` |
| Lists and sharing | Carry PDFs, analyses, list names/order and pinned papers; preserve receiver edits and reject unsafe paths | `tests/test_bundle.py`, `tests/test_package_review.py` |
| Offline synchronization | Restart/retry, lost acknowledgments, concurrent edits, deletion conflicts, atomic receive and source-authored intake-note timestamps | `tests/test_sync_client.py`, `tests/test_sync_operations.py` |
| Selected offline preparation | Actual PDF/deck verification and retry; invalidate changed PDF, research or storage ownership between worker completion and display; clear previous success; no delivery SQL or rehashing | `tests/test_offline_verification_ui.py`, `tests/test_workspace_offline_verification.py`, `tests/test_offline_download_ui.py` |
| Authority control history | Actual issuance/pairing/revocation, concurrent deltas, no-op reads, corruption/rewritten-chain refusal, atomic checkpoint failure, legacy backup/fresh recovery, capacity/cancellation | `tests/test_authority_control_history.py`, `tests/test_authority_control.py` |
| Device pairing | Explicit copy/pair/join, independent credentials, lost-reply resume and native-store/context refusal | [Pairing behavior map](../sync-device-management.md#desktop-pairing-and-retry) |
| Backup and recovery | Preview/restore without changing the source; reject corrupt or stale decisions; confirmed plain/positioned note removal, atomic receipts, peer delivery and later-restore-safe retries | `tests/test_workspace_dialog.py`, `tests/test_sync_recovery_note_removal.py`, recovery scenario maps below |
| Desktop, distribution and mobile | Worker/status delivery, dialogs, update notices, package contracts, safe per-stage packaged acceptance/failure reports, offline mobile domain and service behavior | `tests/test_update_notices.py`, `tests/test_distribution.py`, `tests/test_built_app_verification.py`, `mobile/tests/` |

These families include normal paths plus many variants of cancellation, repeated
clicks, stale windows, changed papers/accounts, corrupt files and interrupted
transactions. Several tests can protect one feature; case count is neither a
feature count nor a completion percentage.

The default `CRITICAL_JOURNEYS` in `scripts/check.py` currently selects 14 existing
cases across startup, packages/PDFs, notes/Q&A, AI isolation, offline sync and
backup/restore. A focused change adds only its relevant regressions. The old
suite remains available through explicit `--profile full`; it is not silently
deleted, skipped or reclassified as passing.

Preview the current curated map with `python scripts/check.py --profile release --plan`
(or `--profile critical --plan`). This reads the same selection as the runner,
without starting checks or replacing the last result. File selectors can expand
to multiple cases; the preview deliberately does not invent a case count.

### What is actually documented?

- This page is the human entry point; scenario maps below explain selected flows.
- `catalog.json` is **partial reviewed documentation**: 333 explained functions at
  this update. Its collection totals refer to older recorded snapshots, not a
  fresh collection or a current passing run. Unlisted functions have no reviewed
  human explanation in that catalog.
- `build/check-latest.json` describes the latest executed selection and outcome;
  it is local and ignored by Git. A critical pass does not set `full_check_passed`.
- Fixture checks do not certify live providers, installed Windows/Mac upgrades,
  physical phone behavior or a deployed sync service. Those are separate gates.

## What the native candidate actually verifies

A candidate is built once from a clean source commit. Windows, Apple Silicon Mac
and Linux use the same frozen verifier. CI stage progress describes completed
work, not a guessed percentage or remaining-time prediction.

| Stage | Concrete behavior required | What a pass does not establish |
|---|---|---|
| Critical source journeys | Start the app; preserve list package/PDFs, saved notes and Q&A; isolate AI config; converge/retry offline edits; preview and restore backups | Every historical edge case or a real provider call |
| First-sync preservation | Prepare existing research and private text/history without replaying old agent receipts or importing local controls | An installed old-release upgrade |
| Authority lifetime (six selected journeys) | Refuse a duplicate listener; release failed bind/process exit; wait for admitted work; interrupt incomplete headers; refuse database replacement/removal; keep online backup available | Cross-host leases, same-inode SQL rollback or durable control-history proof |
| Frozen research workflow | Run the packaged reader repeatedly; import/export synthetic research and exact originals; keep editable data and CLI/MCP retry/restart behavior; exercise platform-specific launch/installer checks | Physical keyboard/IME, long-running stability or every desktop editor |
| Frozen sync protocol | Reject a second listener, authenticate the device, verify linked history acknowledgments, reject a bad proof, retry the exact graph once, restart and reconnect with the retained checkpoint | A deployed HTTPS proxy or two installed devices |
| Exported mobile artifact | Verify every published static byte; use a fresh Chromium profile to prepare and reopen cached research offline | Safari/iOS/Android storage durability or deployment |
| Installed/physical acceptance | Execute the Mac M01-M21 checklist and corresponding Windows/phone journeys with exact build IDs | Remains **not run** until the operator records actual device results |

The six lifetime journeys reuse `tests/test_sync_http.py` and
`tests/test_sync_admin.py`; packaged behavior uses `scripts/verify_sync_protocol.py`.
The job retains a 30-minute cap; the small lifetime step has a three-minute cap.
These are selected requirements, not permission to run every historical test.

## Keep the suite small by testing requirements

The owner approved this reduction on 2026-11-14. The historical function count is
not a release target. Choose one representative for each observable invariant;
add a boundary case only when it protects a distinct failure or an actual bug.

| Occasion | Required scope | Budget |
|---|---|---|
| Edit/checkpoint | Changed behavior, callers and a relevant failure boundary (`focused`) | 3-5 minutes locally |
| Candidate build | Critical journeys on each desktop OS; frozen-app acceptance; affected regressions | Validation plus packaging: 20-30 minutes |
| Public release | Curated `release` journeys once; critical/frozen acceptance on every shipped desktop OS; device checklist | 20-30 minutes per CI build job |
| Deep diagnosis | Explicit historical `full` or a selected stress/migration matrix when a change warrants it | Opt-in; never the automatic development or release prerequisite |

The release requirements add atomic receive, delete/edit conflicts, revoked
access, editable attachment transfer/repair, late UI delivery, private diagnostics,
fresh-install identity, reading goals, exact claim/Lineage/highlight sources and
recovery provenance. Exact Python selectors are `RELEASE_JOURNEYS` in
`scripts/check.py`. Five existing frontend files, seven named mobile domain files
and one actual mobile-to-Python protocol program complete the curated automated
baseline. Changed domains still require their relevant regressions; this baseline
does not claim complete v0.5 feature/device acceptance.

The Lineage release representative now exercises complete native recovery, three
verified originals, an independent peer and the official source reader. It replaces
the narrow corpus-key-only representative in this gate; that historical assertion
remains available for addressing changes and exhaustive diagnosis. The release
selection does not grow by adding every variant of the new feature.

Original-source retirement/restoration adds one complete native peer lifecycle
representative to the release gate (38 Python selectors including retained-history continuity, service execution and agent-import enrollment, not collected cases).
The existing agent-import enrollment representative also preserves a recorded
citation analysis, exact inactive compound history and PDF through first copy and
detached restore. The selector count stays 38.
Original-source focused checks use a metadata-only fixture instead of downloading an
unrelated original first. The source-lifetime transition is distinct from deck
transfer or corpus-key validation; no historical assertion was removed to add it.

### Cross-platform split

The release workflow runs the common `release` selection once, on the Windows
tag build. Every shipped OS runs `critical` plus the existing frozen-app verifier.
Manual candidate builds use `critical`, not the larger release selection. All
build jobs have a 30-minute deadline; the source-check step has a 10-minute cap.
Common candidate [run 43688772032](https://github.com/puddings-world/Paperfact/actions/runs/43688772032)
passed critical and frozen acceptance on Windows/Mac/Linux for clean `c1cbef2`:
14 critical cases plus one source first-sync representative per OS; four PDFs preserved; three-original/five-quote audit;
CLI/MCP retry/restart and same-workspace handoff. The packaged sync service passed
authenticated pull, restart/stale-execution refusal and explicit reconnection on
each OS. Mac also passed three reader starts and native foreground/close; Linux
passed AppImage CLI/MCP. Native jobs took 6m45s / 4m37s / 3m09s respectively.
Windows mobile-artifact tests passed 5/5 with zero failures under fail-fast Bash.
Earlier failures and fixes remain in the dated ledger. No gate selectors added.
Installed upgrades, long-running use, own-provider login, hosted sync and physical
phone/two-device journeys remain open; this is not a public release pass.

| Platform boundary | Additional observation required |
|---|---|
| Windows | Installer/reinstall/upgrade, working data preserved, launch and shortcuts |
| Apple Silicon Mac | Native arm64 app activates, Chinese input/focus/shortcuts work, install/update preserves data |
| Linux | AppImage permissions/dependencies, launch and update preserve data |
| Windows + Mac | Real offline edits, reconnect/conflict, interrupted attachment retry and independent restore |
| iOS / Android PWA | Physical browser install, offline launch/save/reopen and foreground reconnect; record each OS separately |

Use [Mac and multi-device acceptance](mac-acceptance-0.5.md) for actual expected
results. Fixture success must not fill a physical-device result.

### Reuse only proven no-write setup

The offline invalid-input representatives retain every original parameter and
exception/no-network assertion. They now use a real captured research database,
pending operations and an authenticated native reference connection without
building unrelated PDF/deck transfers for each value. Only the no-write cases
share module setup; a function-scoped guard compares exact database bytes and
queued operations and requires zero authority/blob calls after every case.
Write/cancel/corruption/retry and real attachment journeys retain independent full
fixtures. A failing preservation guard is a regression, never a reason to reset
shared state silently. This is a fixture optimization, not a reduced gate claim.

Measured on Windows with max-two-processor/25% job CPU: the old two-case sample
spent 3.99s and 2.26s on setup (7.984s total). The intermediate per-case lean fixture
passed all 21 variants in 25.921s total. Shared no-write setup plus those same 21
variants and two unchanged full PDF/deck/pin journeys passed 23 cases in 12.625s
total. Those are different selections, not an apples-to-apples speedup percentage.
The final two validation setups took 1.09s and 1.02s once per module. No product
code, test parameter, historical assertion, critical14 or release38 selector changed.

### Consolidate historical cases without erasing protection

- Keep a case when it protects a unique user-visible invariant or a concrete past bug.
- Merge repeated setup and duplicate assertions into a shared behavior case;
  parameterize only genuinely different boundaries, not every internal combination.
- Remove a source-string/internal-shape assertion only when a behavioral replacement
  demonstrably covers its requirement. Packaging/security contracts can be distinct.
- Keep exhaustive malformed-input, long stress and legacy-migration matrices
  opt-in unless that domain changed or a specific regression requires them.
- For each actual retirement, record old test ID, replacement, requirement and
  verification. No bulk deletion by filename, age or raw count.

This is the selection policy and initial curated gate, not a claim that all
historical cases have already been reviewed or deduplicated.

## Historical results and detailed scenario maps

The following records retain their original scope and date. References to a
mandatory full check reflect the earlier policy, superseded by the current
[development policy](../development.md#development).


Updated 2026-11-02. `0.5.0.dev`, unreleased. Start with the
[visual feature overview](acceptance-overview.html) or
[plain Traditional Chinese status](current-status.zh-TW.md).

The new [desktop Lineage scenario map](lineage-desktop-scenarios.md) explains
20 application/Qt cases and their exact limits. The final action/coordinator/menu
scope passed 41 cases. The newer [schema lifecycle map](lineage-schema-scenarios.md)
explains first analysis/receive initialization and rollback; its related 21-case
gate passes the unchanged candidate-only absence assertion. Neither selected gate
certifies a release or overrides the requirement for a new coherent full check.

The [Lineage lifecycle scenario map](lineage-lifecycle-scenarios.md) explains
the original 19 backend/sharing cases plus actual retained-version, native
rollback and Qt control journeys. The newer related 48-case gate passes; the
ledger records later UI-only verification and remaining full-release and
installed-device limits. [Historical-original scenarios](lineage-historical-original-scenarios.md)
explain independent source proofs and real Qt windows for all three origins.

For the native Lineage synchronization work, see the
[17 scenario explanations](lineage-shared-scenarios.md): real publication,
conflicts, source lifetimes, HTTP/mobile delivery and competing-device capacity.
The [fresh enrollment/recovery map](lineage-enrollment-scenarios.md) explains
exact copies, fresh native authority, archive integrity and identity collision
refusal. The [continuation ledger](continuation-20261112.md) keeps dated results
and failures.

The [saved Lineage audit scenarios](audit-lineage-scenarios.md) explain which
original each quotation is checked against, read-only failure/invalidation and
real bilingual source navigation.

The [saved-text update map](saved-text-update-scenarios.md) explains the real
reader's background notice, draft/PDF preservation, explicit reload and retry,
plus the shared observer's stale-token and workspace delivery guards.

The [automatic-sync wakeup scenarios](continuous-outbox-scenarios.md) distinguish
actual new local writes from projection/acknowledgment changes, preserve offline
backoff/consent, and cover manual-sync and accepted-before-receive races.

The latest canonical full run stopped at **3,349 passed and one failed**
(old inactive-stage Lineage routing assertion); frontend/mobile were not reached.
The [enrolled import candidate map](enrolled-lineage-import-candidate.md) and
[mobile originals candidate](mobile-lineage-originals-candidate.md) describe
originally isolated work now integrated for affected checks, not released features.
The old activation/refusal expectations and rollback precondition are now
[reconciled with accepted v0.5 behavior](lineage-contract-reconciliation.md);
a new complete gate is still required.

The [native import review map](package-review-scenarios.md) explains explicit
destination/paper choice, queued delivery and final-publication cancellation.

The [native version-comparison map](lineage-import-comparison-scenarios.md) covers
explicit keep/replace, preserved peer history and actual backup/restore.

The [older-beta history repair map](lineage-history-repair-scenarios.md) covers
actual bounded reindex, resume/cancel, offline UI, backup isolation and automatic
scheduling, separate from installed-device/full gates.

The current full check has not passed. Selected checks prove their named actions,
not the whole application, scientific quality or installed-device readiness.

Current native-origin evidence: **6 new cases pass in79.09s** over
the unchanged product/old-test inputs of the preceding130-case gate. Actual
recovered/remote native entries preserve private words, A/B and complete remote
groups; decided conflicts cannot Apply again. Held original close and competing
decision delivery are covered. [Actions and limits](highlight-native-continuation-scenarios.md) ·
[6 case explanations](../../build/highlight-origins-explanations.html).

Previous native highlight candidate: **130 related cases (24 new)** pass in706.7s.
This covers actual quote/reason/role fields, save/reopen, later typing, correct A,
confirmation/restoration, keyboard/layout, cancellation/close and safe native
retirement together with directly affected existing claim/review/original flows.
Privacy/Ruff pass; no failures/errors/skips/input drift. Complete recovered/remote
native journeys, highlight tools, full audit and release/device gates remain open.
[Actions and screenshots](highlight-native-editor-scenarios.md) ·
[24 case explanations](../../build/highlight-ui-explanations.html).

<details>
<summary>Historical selected checks — different snapshots, overlapping counts</summary>

Previous atomic highlight candidate: **269 related cases (38 new)** pass in614.83s,
privacy/Ruff green, zero failures/errors/skips/input drift. Confirmed complete
groups preserve manual/hidden choices; private words/source/research/outbox/receipts
share rollback/retry. Actual recovery, remote conflict, offline peer and second
backup journeys are included. Native highlight controls/tools and complete audit
remain pending. [Actions/results](highlight-application-scenarios.md) ·
[38 new case explanations](../../build/highlight-apply-explanations.html).

Previous highlight-original candidate: **121 related cases (17 new)** pass in809.14s,
privacy/Ruff green and zero failures/errors/skips/input drift. Backend A/B verification,
independent read/recovered bytes and nontransferable results are covered together
with existing claim Qt/CLI/official MCP and text/note original paths. Highlight
Apply/native controls/tools remain pending. [Actions/results](highlight-verification-scenarios.md) ·
[17 new case explanations](../../build/highlight-verification-explanations.html).

Previous private-highlight candidate: **196 related cases (45 new)** pass in544.69s,
privacy/Ruff green with zero failures/errors/skips/input drift. Actual retained inputs,
private variants/restart, independent recovery and offline reference-service conflicts
are covered. The backend has no original verification/Apply UI or CLI/MCP for this type.
[Actions/results](highlight-private-scenarios.md) ·
[45 new case explanations](../../build/highlight-private-explanations.html).

Previous highlight/navigation candidate: **318 related cases (43 new)** pass in535.09s,
privacy/Ruff green with zero failures/errors/skips/input drift. Browse waits for its
actual collection and cancels its jump after later navigation. Manual highlight
revision is a content core only; durable drafts, complete recovery and Apply UI
are still pending. [Actions/results](highlight-revision-scenarios.md) ·
[43 new case explanations](../../build/highlight-revision-explanations.html).

Previous parent-review candidate: **114 related cases (25 new)** pass in482.22s,
privacy/Ruff green, zero failures/errors/skips/input drift. Saved typed decisions
appear on their original inventory rows; actual Qt close/navigation/failure/retry,
native replacement and pending metadata writes preserve current unsaved work.
[Actions, screenshot and group times](parent-review-scenarios.md) ·
[25 new case explanations](../../build/parent-review-explanations.html).
Isolated fixtures only; full app, installed devices and production remain gated.

Previous original-reading candidate: **151 related cases (22 new)** pass in887.11s,
privacy/Ruff green and zero input drift/failures/errors/skips. Decided/stale drafts
can read independently owned originals without obtaining another Apply permission.
Includes actual Qt retry/unsaved/edit/close paths and restarted CLI/official MCP.
[Human actions and executed results](claim-original-reading-scenarios.md) ·
[22 new case explanations](../../build/claim-original-read-explanations.html).
These are isolated integration results, not a full application or installed-device pass.

Previous mobile candidate: **535 mobile unit cases, all 13 HTTP scenario programs,
8 real browser startup groups and the actual offline PWA note journey pass**.
This includes the library-paper resume and navigation-refresh fixes; the prior two
new regressions now pass. No new whole-application pass or installed-device acceptance.
See [the dated result summary](latest-results.json) for scope and stage times.

Previous native-origin candidate: **58 related cases (8 new)** pass in256.09s,
privacy/Ruff green and zero failures/errors/skips/input drift. Dedicated bilingual
remote/cancelled-result entry, source viewer, confirmation, close/cancel/stale work,
private preservation and legacy reselection are covered. [Actions/screenshots](claim-continuity-scenarios.md).
Backend/mobile and old tests remain unchanged; no complete app/device acceptance.

Previous claim continuity candidate: **111 related cases (10 new)** pass in524.53s,
with privacy/Ruff green, zero drift/failures/errors/skips and unchanged old tests.
Real local peer conflict, offline edit/restart/return, conflict closure, cancelled
result editing and independent recovery are covered. [User actions/results](claim-continuity-scenarios.md).
Native remote/cancelled-result button journeys and installed devices remain separate.

Previous shared claim operation candidate: the initial maintained focused run had
**101 passed/one failed**, then a corrected inventory follow-up passed **49 related/
unreached cases** in30.69s. Both have privacy/Ruff green and zero input drift.
Product source did not change between runs; earlier claim/note/native cases were
not all rerun. Counts overlap and are not added into one pass.
[Actual actions, saved results and each matching test](claim-review-operation-scenarios.md).
This includes real CLI/MCP and directly affected existing note/desktop integrations,
not the complete app or installed-device acceptance.

Previous native editor: **60 selected cases, 20 new**, covering actual bilingual
fields, autosave while typing, source inspection, confirmation, recovery and lifecycle
boundaries with existing text/note/original views. [Actions and screenshots](claim-draft-application-scenarios.md).
This is the isolated candidate, not installed-device or full-application acceptance.

Preceding backend:231 cases,22new, atomic application and local peer/rebackup;
historical scope is retained in the same action guide and is not added to current counts.

Earlier private backend: 93 selected cases, 22 new; [private actions and limits](claim-draft-private-state-scenarios.md).

Earlier content core: **113 selected cases, 22 new**; [Actions and limits](claim-draft-revision-scenarios.md).


</details>

| What you want to understand | Actions, saved outcomes and limits |
| --- | --- |
| Edit an actual claim conflict offline, return, close it and recover again | [Claim continuity data journeys](claim-continuity-scenarios.md) |
| An external agent edits claims, inspects original text, restarts and retries | [Claim CLI/MCP action map](claim-review-operation-scenarios.md) |
| Verify and confirm claim revisions, reject changed targets, recover and continue offline | [Claim application actions/results](claim-draft-application-scenarios.md) |
| Save structured claim drafts, restart and recover in another workspace | [Private claim actions/results](claim-draft-private-state-scenarios.md) |
| Edit claim proposals and recheck exact original quotes (internal core only) | [Claim revision actions/results](claim-draft-revision-scenarios.md) |
| Reopen offline without re-entering scope and use whole header labels | [Startup and header actions/results](workspace-resume-scenarios.md) |
| Edit text on desktop and offline PWA without false conflicts | [Actual controls, results and screenshots](plain-note-editing-scenarios.md) |
| Continue private work after recovery, or bring an offline peer edit back | [Two actual data journeys](note-continuity-scenarios.md) |
| A local agent saves, reconnects and applies a recovered note | [Actual CLI/MCP actions and saved results](local-note-review-scenarios.md) |
| Map an unknown/invalid note source, select a passage or remove the position | [Actual mapping results and screenshots](note-source-mapping-scenarios.md) |
| Recover and continue a note, then transfer and back it up again | [Note scenarios and actual windows](note-resumption-scenarios.md) |
| Inspect actual source-boundary pass results and elapsed times | [Executed results](note-source-check-results.md) / [Actions and limits](note-source-boundary-scenarios.md) |
| Inspect the exact original while editing a recovered draft | [Draft original viewer](draft-original-scenarios.md) |
| Recover a draft, edit, verify its original and apply | [Current resumption scenarios](resumed-draft-scenarios.md) |
| Read/copy/export drafts after independent recovery | [Recovered draft reader](detached-draft-reader-scenarios.md) |
| Preserve two human variants without merging them | [Saved drafts](saved-draft-scenarios.md) |
| AI reply failure, duplicates and stale output | [Citation result](citation-result-scenarios.md) |
| Preserve reviewed decisions and required PDFs | [Decision history](initial-enrollment-decision-scenarios.md) |
| Preserve reviewed Q&A and peer notes | [Reviewed Q&A](initial-enrollment-review-scenarios.md) |
| Refresh materials, open old originals or leave during work | [Material reader](material-ui-scenarios.md) |
| Prepare an editable research copy and recover it | [Manual recovery](manual-enrollment-scenarios.md) |
| Inspect retained sources without changing current PDF | [Original reading](retained-original-scenarios.md) |

較早各輪數字與結果見[歷史紀錄](acceptance-map.md)，不與本次相加。

盤點 8,230 個案例／4,600 個函式／577 個檔案，只收集名稱；人工說明涵蓋 隔離整合候選的 292 個函式／537 個案例，其餘尚未整理。

The maintained bilingual explanations live in `catalog.json`; generated local HTML,
logs, exact collection IDs and input receipts live in ignored `build/`. The earlier
selection map is `build/test-explanations-workspace-selection.html`; the earlier
22-case focused map is linked above; the current25-case map is linked first. The canonical
repository's product/tests/catalog are not yet replaced; its ignored report is a
mirror of this separately identified integration snapshot.

During implementation, run affected scenarios; at integration, run interacting
groups; before completion, commit or release, run the complete `scripts/check.py`.
Its phases are privacy scan, Ruff, Python/desktop, frontend and mobile integration.
Case percentages are phase progress, not remaining time or release completion.
Known discrepancies are resolved without weakening older tests.

Older receipts belong in the [historical ledger](acceptance-map.md), not the
current summary. Different dates, source snapshots and overlapping selections must
not be added or described as one current application pass.

The generated explanation map now starts with reviewed prose selected. Uncheck
that filter to inspect the full undocumented inventory; collection is never
an execution result. New note/source scenarios use synthetic research only.

- [Authority backup behavior map](authority-backup-scenarios.md): exact snapshots, committed attachments, cancellation and publication boundaries.

- [Authority fresh-identity recovery](authority-restore-scenarios.md): exact replay, old-session rejection, native deck/Lineage rejoin and source-proof journeys.

- [Exact-content Lineage adoption](lineage-matching-adoption-scenarios.md): explicit matching package approval, rollback, parent lifetimes and pending desktop actions.

- [GCS backup publication](gcs-backup-scenarios.md): real snapshots/SDK interface, simulated cloud, isolated operator setup, immutable retry and shared content.

- [GCS backup retrieval](gcs-fetch-scenarios.md): exact snapshot, untrusted manifests, bounded SDK ranged bytes and fresh-workspace recovery; no live cloud.

- [Old-device recovery review](device-recovery-review-scenarios.md): uncertain acknowledgments, exact backup prefix, no mutation, worker cancellation/close and GUI binding changes.

- [Direct saved Lineage adoption](lineage-direct-adoption-scenarios.md): selected PDFs, unchanged science/model, atomic sources/history/outbox, native peer recovery and real verification/confirmation controls.


## Equal-byte source-owner regression (2026-11-15)

The release gate adds one real three-paper Lineage case where all original PDFs
have identical bytes. It protects the independent owner-identity boundary; the
14-case daily critical default does not change. It does not select the 184-case
audit module regression used while changing the shared closed schema.

Six new collected cases protect distinct outcomes: quote/quantity owner refusal,
actual saved multi-paper attribution, no borrowed retrieval/AI route/exact fact
binding, native/local alias normalization, and English/Traditional Chinese GUI
findings with navigation refusal. Existing cases/assertions remain unchanged.
A matching quotation is still not semantic support or a full multi-source audit.


## Explicit Lineage corpus audit (2026-11-15)

Five focused cases in `test_audit_lineage_corpus.py` cover independently owned
same-byte originals, immutable/stale delivery, cancellation, actual retained
original corruption (no download/peer substitution), and explicit unavailable
coverage/resource limits. Existing imported and bound-source representatives also
call the new corpus operation; no additional parameter matrix is collected.
Existing CLI/MCP cases retain default behavior and exercise the optional schema.
Daily critical remains 14; no release selector is added for this incremental
adapter. The desktop control is covered by the next checkpoint; installed-device acceptance remains pending.


## Desktop whole-Lineage action (2026-11-15)

Seven focused actual-Qt cases in `test_lineage_corpus_desktop.py` cover the new
button in English and Traditional Chinese: no-selection refusal, source-count
progress, per-quotation findings and independent original navigation; unchanged
research through failure/retry and an unavailable original; and late delivery
after cancellation, history selection, another paper, or close/drain. A loaded
context change hides prior snapshot findings. Fixture publication uses simulated
model output; the check itself refuses any model call. Existing Lineage dialog
cases protect the shared worker, generation, saved reads and original viewers.
No daily/release selector matrix is added. Native packaged layout/device checks
remain separate acceptance gates.


## Source-complete acceptance material (2026-11-15)

Four new cases in `test_acceptance_research_package.py`: actual generated ZIP,
production import twice, public JSON CLI corpus audit (3 originals/5 quotations),
byte-identical re-export of 4 PDF files, and refusal of existing data, existing
outputs or unspecified workspace. Synthetic generation blocks network/model
clients in the test; no AI or credential file is needed. Existing packaged-runner
cases now require the frozen-CLI audit stages and reject incomplete results. Fake
child orchestration is not native package acceptance. No daily/release matrix is
added; M21 remains a real installed Windows/Apple Silicon UI gate.


## Confirmed manual-mark deletion (2026-11-15)

Five new scoped outcomes cover single-mark native retirement and independent peer
delivery, preserving later restores on retry, atomic receipt failure, stale/
untracked/absent target refusal, unrelated note protection and actual Qt No/Yes
confirmation/deduplication. See the manual-highlight section of
[recovery scenarios](device-recovery-review-scenarios.md#confirmed-manual-highlight-removal-2026-11-15).
Existing typed-choice/parent/worker and Chinese copy representatives are reused;
no daily/release selector or cross-product matrix is added.


## Known-deleted manual identity restore (2026-11-15)

Five new outcomes cover native key/peer fidelity and later-deletion-safe retry;
sealed PDF witness/byte changes; receipt rollback, stale target and mid-write PDF
mutation; active/duplicate/unavailable source refusal; and actual Chinese
confirmation plus readable missing-original comparison. The public choice API
uses restore on a known retired mark; it grants no original ownership. See
[the scenario map](device-recovery-review-scenarios.md#original-identity-manual-restore-2026-11-15).
Only affected shared decision/removal representatives rerun. Daily critical stays
14 and the curated release selection is unchanged; no new stress matrix.


### Retained service history before outbound research

`tests/test_sync_history_frontier.py` protects an actual push-before-history bug:
missing/different last-received events prevent attachment preparation, upload and
acknowledgment, while matching history permits normal sync. It also checks the
closed authenticated HTTP error and automatic desktop pause without private error
text or repeated background requests. The release map adds one selector for the
nine short history combinations (received, acknowledged with cursor zero, or both;
missing, different or matching); daily critical stays unchanged.

The matching mobile regression lives in the existing `engine.test.mjs` release
selection and checks both refusal and unchanged offline state. Transport/shell
checks retain auth/blob error separation and preserve research storage when v25
static code replaces v24. These are scoped fixtures, not installed/cloud proof.


### Prepare agent-created research without replaying its requests

`tests/test_enrollment_integration_history.py` has four distinct requirements:
actual imports/copy/backup/detached restore preserve exact private observations,
PDF bytes, research and complete list order; unknown/malformed history never
publishes output; cancellation or changed history preserves source and supports
retry; actual desktop preview labels archive-only records and coalesces clicks.
One representative joins the curated release map, adding no daily critical work.

The fixture uses real `imports.propose`/`imports.commit`, including two receipts,
multiple papers in chosen order and a legacy sparse ordering layout. It also
checks that an old request cannot become committed or executable in the new copy.
This is not server issuance, upload, arbitrary receipt migration or installed-device
acceptance. The existing local operation/input/archive checks remain separate.


### Retire a saved explanation, section reading or context summary

The existing `test_sync_recovery_claim_removal.py` now covers four typed report
slots (`claims/main`, `dive/main`, `close_reading/main`, `context/main`) through one guarded
removal implementation. Native peer/retry, untracked-visible-content refusal and
actual Chinese confirmation are checked per slot; shared receipt-failure,
cancellation and stale-target logic is checked once. This gives thirteen selected
cases, not a full stress cross-product. Other reports, notes, PDFs and historical
records must remain byte/content-identical. See the existing
[report retirement scenarios](device-recovery-review-scenarios.md#confirmed-claim-report-retirement-2026-11-15).
Daily critical and curated release selectors are unchanged. Physical packaged
acceptance remains separate.


### Workspace window isolation across platforms

`tests/test_workspace_focus.py` extends the existing fragmented-frame and handoff
checks with exact destination rejection before window activation. Three platform
policy cases cover native path normalization, physical-directory aliases,
case-distinct roots when the host supports them, no directory creation during
key lookup, and the existing Windows key format. These policies are simulated on
Windows; native Mac/Linux and cross-version handoff are separate acceptance gates.
The existing launch and restore/join UI files protect drafts, retries, credentials
and one-click coalescing. No default/release selector or new test file was added.


### Packaged same-workspace handoff

The existing built-app verifier adds one native requirement, not a new source
suite: wait for the fixture reader's actual expected local endpoint, launch again,
require the second process to exit before its own smoke timeout while the first
remains alive, then require a normal primary exit. Existing script tests check
success, absent endpoint/early exit, secondary error/timeout and primary loss;
those fake-process cases establish orchestration only. The native report must
separately record `instance_handoff` as true before claiming the package passed.
Critical remains 14. The later service-execution requirement adds one release
representative (38 selectors); no historical test matrix.


### Service execution continuity (source, not hosted)

A real HTTP listener restart at the same address must reject an existing session
without acknowledging or altering its queued research, while a fresh connection
can retry normally. Identity is checked before private requests; absent, malformed
or duplicated offers send no research. Headerless wire requests return 428.
Existing HTTP/blob/device/browser requirements retain their assertions with a
real identity preflight in raw fixture callers. One restart representative is
added to release; daily critical remains 14. No broad historical suite is required.

Mobile transport checks changed/missing offers, explicit reconnect and late-response
cancellation; cookie and bearer paths share the guard. The actual JS/Python service
journey and isolated headless Chromium cookie pairing/reload/reconnect/forget
journey are distinct from mocked tests. The browser proxy preserves the header
both directions. New native packages, live TLS/proxy and physical phone/Mac
acceptance remain separate gates; a process nonce is not an authority-history proof.


### Prepare a real existing profile without copying its authority

`test_normal_local_controls_do_not_block_or_follow_a_prepared_copy` uses the actual
schedule, update-cache and HTTP cache writers with simulated network responses,
local sharing/failure controls, retained
queue/list metadata and representative account/consent/usage files. It requires:

- Coverage succeeds, source research/settings stay unchanged, private values/files
  appear in neither candidate nor independent backup.
- Protected account/diagnostic directories are pruned: a guarded scanner fails if
  any private descendants are visited, so a large CLI home is not traversed.
  The reserved HTTP cache is likewise pruned: cached bytes never enter the backup,
  and changing a response after coverage does not cancel a coherent research copy.
  A similarly named `httpcache-notes` research directory still blocks.
- A valid legacy adoption marker survives backup/restore as data; repeated list
  refresh with and without that marker preserves the complete prepared SQL dump.
- Unknown analysis/update/drive scopes and malformed legacy markers remain blocked;
  unbound one-time adoption and ordinary read-only refresh retain their behavior.

The existing release agent-import representative now includes a real update-cache
write, with its exclusion asserted. Daily critical remains 14 and release remains
38 selectors; no new test file or broad legacy stress matrix. Source/Qt-fixture
results do not establish installed/hosted/device acceptance.

The native verifier's `sync-protocol` stage runs the built CLI twice against one
synthetic authority: authenticated read, listener restart, stale-execution refusal
and explicit reconnection. The existing built-app verification test file also
checks rejected/missing execution contracts and child cleanup after failure.
Source CLI evidence is separate from the actual frozen result on each OS; neither
substitutes for the installed Windows/Mac offline-edit journey or hosted HTTPS.


### List-overview evidence status

The existing `test_survey_dialog.py` checks one additional user requirement:
recorded roadmap/saved-research/unknown workflows and manual-edit status are
explained in English and Traditional Chinese, without AI/network or SQL changes.
Deleting a survey or changing workspace clears stale evidence text. Existing
running-rewrite and explicit replacement protections remain. This is three cases
in that focused file, not coverage of claim-level survey source verification.
The [remaining source contract](../analysis-audit.md#list-overviews-current-status-and-remaining-source-contract)
is still planned. Local offscreen rendering uses the current source and the app's
bundled fonts/style; installed cross-platform visual acceptance stays separate.


### Citation-neighbour graphs across devices

The existing capture/content/citegraph files protect exact paper mapping, private
KV isolation, initial-copy/backup/restore, no-echo retry and deletion. Two independent
native edits retain both graph versions. A provider response arriving after a newer
graph produces a retained candidate. The package-import case checks owner mapping,
receiver-preserving default, explicit replacement and exact retry. Other legacy KV
still refuses. No new test file or gate selector was introduced.

`tests/fixtures/citation-graphs.json` is shared by Python and the mobile content
validator: shape, Unicode, duplicate/escaped keys, integer/exponent counts and source
ownership. The actual JS/Python HTTP program now transfers a graph alongside its
existing draft/analysis/PDF/deck checks. The earlier position-ingress stub now
provides the existing mandatory execution header and real after/limit pagination;
its float/exponent rejection and atomic store/cursor assertions remain intact.
These are local scoped checks, not native installed graph/hosted/phone acceptance.
The existing release-selected agent-import enrollment scenario now also carries
a graph through capture, independent backup and detached restore. Release stays
at 38 selectors; the daily critical gate stays at 14.

Candidate cb6ca66 also proves exact citation-graph content, idempotent retry and
persistence after packaged service restart on all three desktop platforms. This
does not establish a frozen GUI-client or hosted/physical-device sync journey.

The existing first-sync representative now also retains exact legacy text input
through copy and detached restore. Native candidate CI runs this one focused
representative per desktop OS unless the Windows tag release selection already
ran it; its own three-minute cap preserves the overall candidate budget.
No critical or release selector was added.


The pinned old-source probe adds one explicit native stage: real0.4.3 writers
create synthetic notes/Q&A/highlights/PDF/deck; the candidate reads and exports
before/after schema initialization. Exact old values and file bytes are compared.
Deliberate note/PDF/layout/export corruption must fail. This is not an old-binary
installer/GUI-upgrade check; see the [contract](../toolchain.md#pinned-old-source-upgrade-preservation).


### Source-aware survey development slice

Focused contract/corpus selection:15 cases in4.95s (9.0s stages). They check the
exact retained prompt/input hashes and paper lifetimes; strict report/prose pairing;
wrong owner/version/unknown source/private-field/JSON refusal; and real owned PDF
quotes. Managed source materialization must win over a different legacy alias.
Equal bytes from separate paper owners remain distinct; replaced originals leave
old inspectable snapshots without current publication readiness. Missing sources,
selection, cancellation and byte budgets cannot mutate research. These are internal
read-only engine checks, not source-ledger saving, peer/package, UI or hosted passes.
Critical14/release38 selections are unchanged; no historical suite is required to
iterate on this slice. The exact checkpoint is in the continuation ledger.


### Survey original retention and independent backup

The5 final cases (9.04s;12.3s stages) check actual durable original/receipt pairs,
current-PDF replacement, cancellation between two originals, exact retry without
duplicate history, receipt/byte corruption and managed-original ownership. They
also create a real detached backup, restore into another directory, compare exact
original bytes and confirm no active sync identity or source grant is revived.
The shared receipt/Lineage/claim regression selection13 passes22.50s/26.8s stages.
These cover archive storage and isolation, not a canonical survey report or its
list-package/peer transport. Critical14/release38 selections remain unchanged.


### Native list-owned survey artifact checks

`tests/test_sync_survey_files.py` groups five requirements: actual independent-peer
transfer of a report larger than the operation limit; closed owner/workspace and
source-version rejection; retired-original conflict preservation; correctly scoped
retirement and corrupt-byte refusal; and delayed materialization after list removal.
Report availability never means PDF activation or scientific support. The existing
`tests/test_lineage_transfer_readiness.py` guards the shared source-outcome wait.
These use fixture databases, real local PDF/blob bytes and the reference service;
no model/account/cloud calls. They do not certify the pending trusted publisher,
package/mobile/installed-device workflow. Critical14/release38 remain unchanged.


### Trusted survey publisher checks

`tests/test_survey_publication.py` groups seven requirements: read-only staging and
exact idempotent publication through an independent native peer; caught late failure
rolling back originals/report while preserving an observed caller note edit; cancel
and outer rollback without source grants; competing target/retired report refusal;
foreign database/raw proposal/replaced original refusal; interrupted materialization
recovering the same pending intent after reconnecting from disk without a proposal;
and actual same-binding database replacement during completion. These use sealed
real PDF captures and local
fixture services, never account login or model calls. Related source-capture checks
cover missing originals, cancellation without SQL changes and managed-original
precedence. This does not certify UI, mobile, bundle recovery or hosted deployment.


### Mobile saved surveys: requirement map

| Selected check | Protected behavior |
|---|---|
| `mobile/tests/survey-artifacts.test.mjs` (4 groups) | List/workspace/source lifetimes; report/prose/digest/semantic scope; offline report without PDF; corrupt bytes; duplicate download; forged accepted source pins and delayed list retirement |
| `mobile/tests/survey-view.test.mjs` (3 groups) | Empty selection, both languages, literal content, visible progress, duplicate/failure/retry and stale navigation/account/close delivery |
| Existing artifact/original/shell checks | Preserve deck/PDF behavior; replace shell v31 with v32 without touching research caches |
| Existing build/runner checks | Public allowlist includes dependencies and excludes private/test files; explicit full mobile gate propagates survey protocol failure |
| `mobile/survey-service-check.mjs` | Actual trusted Python publication to independent HTTP/mobile receiver: report over256KiB, interrupted/resumed ranges, complete ledger, located vs unlocated excerpts, offline reopening, separate PDF availability and list retirement |

Related52 checks pass15.073s (15.375s governed); native/HTTP journey passes5.094s
before adding Unicode fixture text. These are selected checks, not exhaustive
mobile/release or real-device results. Fixed critical14/release38 selections stay
unchanged. Use `scripts/check_bounded.py.execute` for explicit Node file selections:
the ordinary focused CLI deliberately accepts root `tests/test_*` paths. Do not
widen its selector or run the full suite to work around that limit. One governed
job at a time,2 logical CPUs/25% cap/90s per selected command in this slice.


### Portable survey package contract checks

`tests/test_survey_packages.py` uses seven behavior groups, each beginning with the
actual trusted native publisher and owned original PDF. They cover exact report/
PDF ZIP roundtrip without sender writer fields or SQL changes; missing/wrong-owner/
path/case-aliased/extra members; a rehashed false located quotation; stale final
export publication; cancel/PDF budgets/missing managed original without fallback;
and admitted metadata/private-field refusal. Validation returns data, never native
import authority. These are internal contract checks, not completed bundle-button,
receiver mapping, bound/unbound import or device acceptance. Initial6 pass14.00s
(21.7s stages) under the300s/2-core/25% governor. Fixed critical14/release38 remain
unchanged. No existing assertion or user behavior was weakened.

The seventh group runs an actual complete backup and independent detached restore:
report/original objects and historical paper mappings survive, no live device or
source grant is installed, and unreviewed detached re-export keeps its original
safety refusal. It reproduces/fixes the old applied-artifact paper-owner assumption.
Final package/recovery7 plus existing editable-deck recovery1 pass12.65s (16.9s
stages). This is inactive archive preservation, not reviewed report reattachment
or completed public list-package import/export.


### Existing-owner survey receiver checks

`tests/test_survey_package_import.py` has eight behavior groups. All use actual
native publication and isolated ZIP/receiver fixtures, without models or accounts:

| Group | Observable requirement |
|---|---|
| Import/retry/re-export | Explicit receiver identities, exact historical report, no preparation research writes, one publication on retry, independently valid re-export |
| Independent peer | Receiver-owned originals/report reach a fresh receiver device; sender identity grants are not copied |
| Failure/cancel/rollback | Failure after an actual source grant and caller rollback leave no partial report/source publication; retry succeeds |
| Stale selection | A changed receiver list or replaced selected archive refuses publication without writes |
| Mapping/proof | Missing/absent receiver selections and an unsealed dictionary cannot grant ownership |
| Preserve/replace | Default keeps current report without research writes; explicit replacement keeps version history and preview states agree |
| Request/context | Changed content cannot reuse a prior request; another database cannot apply the sealed receiver preparation |
| Missing originals | All-unavailable report and omitted optional source inventory import without invented PDF grants or mappings |

Final affected check passes in31.922s governed (28.476s selected tests). The
300s/2-core/25% ceiling remains enabled; fixed critical14/release38 are unchanged.
This is internal existing-owner acceptance, not new-root/unbound public bundle
integration, installed-device testing or a completed sharing workflow.


### Compound survey import checks

`tests/test_survey_package_compound.py` uses real ZIP/native-publisher fixtures and
the shared enrolled importer. It protects prospective list/paper/membership roots,
exact source/report activation, no research writes during preparation, one action
receipt on retry, and re-export collection. Injected failure and cancellation occur
after actual report application: roots, ownership, outbox and receipt all roll
back, then retry succeeds. Other cases reject archive/frame substitution, distinguish
list-owned report files from paper originals, refuse malformed capabilities before
writes, and preserve an existing report until explicit replacement while retaining
history. Unsupported local-only import is checked for zero research/file changes
and original-archive preservation. Existing package and bundle cases are selected
together for regression evidence; historical selectors remain unchanged.


### Local-only survey package journeys

`tests/test_survey_package_local.py` exercises real public bundle entries and
independent local SQLite receivers. Cases cover exact report/PDF import, idempotent
retry, re-export and second-receiver ownership; post-publication failure with no
partial roots/source/report; tampered originals and recreated list lifetimes;
default preserve/explicit replace with retained history; full backup and inactive
detached restore; actual native public export to local-only import; and complete
paper-context/metadata-only export bounds. The earlier compound-import case now
expects the newly supported local-only behavior rather than its temporary refusal.
No historical assertion is dropped. Source-aware desktop display and first-enrollment
mapping remain separate gates; a data roundtrip is not installed UI acceptance.


### Saved-report desktop reading checks

`tests/test_survey_reader.py` has seven cases across native/local ownership. It
checks exact reports without AI/PDF parsing or SQL changes, sealed content, original
page/quote PNG inspection, invalid selections/pages/cancel, actual metadata edits
and native database replacement, plus an older applied report during a pending
update. The normal native read reproduced absent-to-zero-byte WAL creation; only
that empty observation is normalized, while real writes/replacement still refuse
stale work. Seven pass9.09s (13.0s stages).

`tests/test_survey_evidence_ui.py` has ten cases and runs with the three existing
survey-dialog cases. Actual Qt widgets verify EN/ZH native/local report and PDF
pages, separate legacy editing controls, literal HTML/no external-link dispatch,
held-read deduplication, workspace/list switches, failed read/inspection retry,
explicit cancel then retry, close/cancel/drain and reopening after legacy jobs.
The active-overview job case also prevents a late saved report from stealing its
tab. Final13 pass30.03s (35.4s stages). Synthetic EN/ZH screenshots are visually inspected;
the first bare fixture's missing-font squares were corrected by using the app's
actual Fusion/font initialization. This is not an installed Mac or real-provider
journey. Fixed critical14/release38 selections are unchanged.


### Saved surveys at first enrollment

`tests/test_survey_enrollment.py` contains nine selected cases:

| Cases | Protected user outcome |
|---|---|
| Current report and independent peer | Source stays byte-identical; copied report is native/readable; source/list/paper lifetimes are fresh; old local rows are archived; credentials stay out of operations; exact report/PDF reaches another device |
| Multiple local versions | Two versions retain distinct archive identities; only the current report becomes a native publication |
| Late failure/cancel (2) | Failure after actual private report publication exposes neither candidate nor backup; retry succeeds and source stays unchanged |
| Changed original | Damaged required bytes cannot be granted or published; repaired bytes allow planning |
| Foreign context/raw export | Another workspace/request and unsealed or mutable source captures cannot authorize native publication |
| Preview (2 languages) | Actual desktop coverage includes saved reports and retained-original counts |
| Explicit missing originals | A newer report stays unavailable with no original grant even when an old version's PDF survives privately |

Final affected selection uses those9 plus six named existing enrollment journeys:
normal research/credential exclusion, verified primary PDF/backup, empty workspace,
imported claim originals, Lineage and actual desktop preview/prepare/open. All15
pass79.96s (81.171s governed). No historical selector is broadened, skipped or
weakened. This is not a full-suite, hosted-service or installed-device result.

### Generated local survey publication

The internal generation/publisher is not yet the desktop default. The focused
file `tests/test_survey_local_generated.py` has eight behavior cases:

| Scenario | What the assertions inspect |
|---|---|
| Save/read/export and retry | Same generated report, located original page, exact export closure, and unchanged SQL on retry |
| New result arrives while work is pending | No new AI call after target changes; a staged stale result cannot overwrite the newer report |
| Preserve or explicitly replace | Default preserves content; explicit replacement retains two versions with exactly one current; old retry cannot reactivate itself |
| Interrupted SQL publication | Separate failure/cancel cases run actual writes, then verify complete rollback and a single successful retry |
| Bad source or cancelled preparation | No canonical report is created after corrupt staged bytes or cancellation |
| No selected originals | Explicit missing selection, empty source grants, and export containing report only |
| Switch global workspace | Pending publication writes only its captured database; the other database remains byte-identical |

These tests use synthetic PDFs and model responses. They cover this internal
boundary, not installed UI buttons or live provider/hosting behavior. Related
`test_survey_jobs.py` covers generation/account capture; existing
`test_survey_package_local.py` covers package sharing and inactive backup.
Run the affected selection with the focused profile; these files were not added
to the curated critical/release selectors.

### Research goal captured for a survey

`test_survey_goals.py` adds six cases protecting: the exact goal supplied to
plain/structured prompts and retained in an exported/saved report; absent/cleared
goal and version changes before inference; changed goals during local/native
inference without overwriting today's goal; bounded/Unicode inputs; and strict
old/new report compatibility. Literal EN/ZH rendering is checked in these cases.

The existing managed-original observation case is stronger: it still proves that
the registered PDF wins over a conflicting legacy alias, and now proves that
neither publisher nor AI-generation preflight acquires write authority merely
because the native writer is not loaded. Source reading remains possible.

Mobile's related ten codec/view/shell cases include two new goal cases. A real
Python native publisher/HTTP/mobile fixture verifies Unicode goal preservation,
interrupted range resume and offline restart. These are local fixture checks;
they do not replace physical iOS/Android or installed Mac acceptance.

### Desktop-to-CLI source-aware reports

The new worker cases check actual CLI save/read, cache reuse, retained JSON and
original references, stale goals, duplicate/expected-target refusal and completed
cancellation with explicit-PDF enrollment. Native/local widget cases check
confirmation cancel, one captured private handoff, close, actual publication and
result reopening. Only child IPC completion and model responses are simulated.

A deterministic database mutation checks one fresh read; continuous changes stop
after two attempts. The existing physical replacement case waits for Windows'
read lease before replacement and keeps its original no-job/no-write assertions.
No new case enters the curated critical/release selectors.


## Saved-report interruption recovery

The [pending-report scenarios](../../tests/test_survey_pending_ui.py) use real
SQLite report/source intents and synthetic originals. Both first publication and
an update over an existing applied version are covered. They do not call a model,
request account login, download files or use a real research workspace.

| Journey | Observable requirement |
|---|---|
| Close/reopen, then finish | The selected saved report becomes applied; no new source/report operation versions appear |
| Failure and retry | A local activation error preserves the prior applied state and pending intent; retry completes that same intent |
| Repeated activation | One worker starts; repeated clicks and direct reactivation cannot create duplicate work |
| Close while running | Cancellation before write preserves pending state; a fresh dialog can finish later |
| Newer report arrives | An old read cannot activate the newer intent or rewrite it as the old selection |
| Workspace changes | Accepted work stays bound to the original database; stale UI delivery is dropped and no other database is created |
| Storage/database changes | Rebinding during materialization or replacing the database refuses activation |

These are source/widget scenarios. Dialog reopen is not an installed OS-process
restart, a physical Mac/iPhone check, a hosted deployment or proof that every
original PDF has downloaded. The completion action concerns accepted local report
files; original availability remains independently verified when opened.

### Packaged report action, beyond startup

The new `source-aware-report` frozen stage exercises an actual CLI import -> one
loopback synthetic completion -> saved report/PDF export -> retained-result read
-> cached retry. It checks quote location and requested/returned model identity,
not semantic scientific support. The endpoint rejects unexpected/repeated calls.
`tests/test_source_report_acceptance.py` runs this whole journey against the source
CLI; the verifier contract test also requires the named stage and its result.
Affected verifier/helper43 pass44.9s stages locally. All three actual frozen CLIs
now pass this stage at e5eb093/run43776461463; downloaded provenance confirms its
named outcomes for the original CLI stage.

Source after 4cdca19 extends the same journey with the production desktop
`JobHandoff`, a real QProcess and private stdin to the selected CLI. Disabled
child disk settings prove the captured synthetic route is used without modifying
those settings. Failure-before-handshake and timeout are checked separately.
The existing e5eb093 artifacts do not contain this extended acceptance evidence.
The host component remains source code; full frozen desktop dialogs and physical
devices remain separate from this CLI/private-transport evidence.


### Offline pilot configuration preparation

`tests/test_gcp_pilot_prepare.py` has a small, named behavior selection: consistent
same-origin service/proxy/backup rendering; unchanged source templates; no overwrite
on retry; retained partial output; bounded invalid/duplicate/oversized JSON refusal;
and the actual standalone Python CLI. Test IDs describe failure classes instead
of printing long input blobs. It creates only isolated review files, never calls
GCP, installs a service or establishes hosted/device/security acceptance.


### Readable mobile report translations

The focused `mobile/tests/survey-view.test.mjs` selection now checks that each
Traditional Chinese report label contains actual translated characters, then
exercises the localized offline-failure/retry action. Comparing a rendered label
only to the same damaged translation constant had missed literal question marks.
Adjacent survey/artifact tests retain literal research rendering, stale-source
refusal, cache integrity and absence of private/test files. Physical layout,
HTTPS deployment and installed-phone updates remain separate acceptance.
