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
| Offline synchronization | Restart/retry, lost acknowledgments, concurrent edits, deletion conflicts and atomic receive | `tests/test_sync_client.py` |
| Device pairing | Explicit copy/pair/join, independent credentials, lost-reply resume and native-store/context refusal | [Pairing behavior map](../sync-device-management.md#desktop-pairing-and-retry) |
| Backup and recovery | Preview/restore without changing the source; reject corrupt or stale recovery decisions; cancel safely | `tests/test_workspace_dialog.py`, recovery scenario maps below |
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
representative to the release gate (35 Python selectors after the owner-identity representative below, not collected cases).
Its regular focused checks use a metadata-only fixture instead of downloading an
unrelated original first. The source-lifetime transition is distinct from deck
transfer or corpus-key validation; no historical assertion was removed to add it.

### Cross-platform split

The release workflow runs the common `release` selection once, on the Windows
tag build. Every shipped OS runs `critical` plus the existing frozen-app verifier.
Manual candidate builds use `critical`, not the larger release selection. All
build jobs have a 30-minute deadline; the source-check step has a 10-minute cap.
This wiring is not evidence that Actions or installed Mac/Linux acceptance passed.

| Platform boundary | Additional observation required |
|---|---|
| Windows | Installer/reinstall/upgrade, working data preserved, launch and shortcuts |
| Apple Silicon Mac | Native arm64 app activates, Chinese input/focus/shortcuts work, install/update preserves data |
| Linux | AppImage permissions/dependencies, launch and update preserve data |
| Windows + Mac | Real offline edits, reconnect/conflict, interrupted attachment retry and independent restore |
| iOS / Android PWA | Physical browser install, offline launch/save/reopen and foreground reconnect; record each OS separately |

Use [Mac and multi-device acceptance](mac-acceptance-0.5.md) for actual expected
results. Fixture success must not fill a physical-device result.

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
