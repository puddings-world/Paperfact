# Evidence: shared offline operations and retry identity

- Pattern ID: local-integration-v1
- Status: validated-local
- Date / project: 2026-10-24 / Paperfact
- Trigger: external projects needed to save already researched papers without
  model parsing, duplicate retries, workspace confusion or reader reloads.
- Invariant: one process-bound workspace; shared operation semantics; atomic
  list/member/receipt/revision persistence. Existing research is preserved.
- Trade-off: explicit identifier matching is conservative; uncertain title
  matches require caller review. Staged previews expire, commit receipts persist.
- Implementation: `src/paper_daily/local_operations.py`, `integration_entry.py`,
  `mcp_server.py`, `desktop/integration_dialog.py`, `desktop/workspace_changes.py`.
- Verification: `python -m pytest tests/test_local_integration.py
  tests/test_integration_desktop.py -q`; 32 passed locally on 2026-10-24.
  Coverage includes concurrent retries, rollback, recovery after helper restart,
  identifier conflicts, CLI workspace isolation, actual SDK stdio discovery/calls,
  UI selection/cancellation/repeated clicks and worker-close guarding.
- Limits: fixture research and SDK client only. Real external agent UI settings,
  paid analysis, remote MCP authorization and production contention were not tested.
  Packaged transport acceptance is enforced separately by release verification.
- Privacy review: synthetic records and repository-relative implementation paths;
  no credentials, raw user research, identifying paths or telemetry upload.
- Promotion: repository-local evidence only; not installed as a global rule.


## Integration checkpoint: thread completion and result delivery

The full-suite run exposed a pre-existing AskRunner shutdown race: the GUI joined
the worker while its queued quit request still needed the GUI event loop.
`tests/test_runner_shutdown.py` reproduced both success and failure paths before
the fix (2 failed). Direct delivery is used only for the documented thread-safe
`QThread.quit`; UI result callbacks remain queued. Busy state includes pending UI
delivery so a fast-exiting thread cannot enable a second request before the first
result is applied. The existing click-flood test caught that second boundary.

`tests/test_runner_shutdown.py`, `test_runner_thread.py`, `test_activity.py`,
`test_local_integration.py`, and `test_integration_desktop.py`: 74 passed locally
after both fixes on 2026-10-24. The original tests were not weakened.
The frozen candidate also passed the JSON/MCP acceptance contract, including
retry and helper restart. Final release artifacts are verified separately.

API evidence: [Qt QThread.quit is thread-safe](https://doc.qt.io/qt-6/qthread.html#quit).
This does not authorize direct connections for arbitrary UI methods.


## Workspace-wide refresh (2026-10-24)

The initial integration receipt counter observed only structured commits. Legacy
CLI and ordinary SQLite mutations could change lists without a notification.
`tests/test_workspace_refresh.py` reproduced 12 failures before the change.
A bounded revision row maintained by database triggers now invalidates list views
after committed membership, naming, metadata or analysis-state changes. Rollback
does not publish a change; unrelated account/UI polling does not invalidate lists.
Refresh failures retain a pending retry, and modal/popup/drag interaction defers it.
The first targeted run passed 51 tests across workspace refresh and integration.

A separate live diagnostic found two databases with different list memberships:
the app was already displaying its own database accurately. Database invalidation
cannot reconcile a different workspace. Check workspace identity first; merging
research is a separate operation with its own destination and preservation rules.
Only synthetic records are used in tests. No real research identifiers are retained
in this evidence record. Migration and full-suite checks accompany the final change.


## Replication extension: acknowledgment is not materialization

- Pattern ID: local-integration-replication-receipts-v1
- Status: validated-local
- Date / project: 2026-10-26 / Paperfact
- Trigger: review of the first two-workspace client found that upload acknowledgment
  cleared the local predecessor before pull. A following edit falsely conflicted
  with its own accepted predecessor; an older pull page could replace newer local text.
- Invariant: acknowledged-but-unreceived operations remain outstanding for causal
  chaining and materialization. Event history, research application and cursor are
  one local transaction; deferred content does not imply a lost remote event.
- Preconditions: replication with separate upload acknowledgments and ordered receive.
  Ordinary local CLI/MCP receipts do not require this additional remote state machine.
- Trade-off: retained receipts/history and an explicit awaiting-receipt state add
  storage and lifecycle work; they avoid deriving causality from wall-clock time.
- Implementation: `src/paper_daily/sync_client.py` and `sync_service.py`.
- Regression evidence: five added cases failed before the fixes; the client suite
  then passed 19 cases (82 combined client/service/journal cases). These cover failed
  pull + restart + subsequent edit, older pull pages, unobserved conflict heads, and
  canonical absence preserving the rejected version in history.
- Named tests: `test_acknowledged_edit_remains_causal_parent_after_failed_pull_and_restart`,
  `test_older_pull_page_never_replaces_newer_acknowledged_local_content` in
  `tests/test_sync_client.py`. Run `python -m pytest tests/test_sync_client.py -q`.
- Limits: isolated SQLite and simulated services; not physical power-loss, hosted
  security, live mobile/browser storage, or complete application writer coverage.
  Later explicit-resolution changes and full-suite counts are tracked in the
  repository implementation ledger rather than substituted for this initial evidence.
- Privacy: synthetic records only; no account secrets, private research or machine paths.
- Promotion: repository-local refinement only; no global installation or cross-project
  reuse claim. Production retention, protocol evolution and enrollment remain separate.


## Compound graph intake and transaction ownership — 2026-10-26

- Status: `validated-local`; repository-local refinement, not cross-project reuse.
- Trigger: a list intake creates paper metadata, membership and notes and must survive
  retries; an empty peer must reconstruct those dependencies even after a later rename.
- Invariant: one caller-owned transaction covers research, outbox and action receipt.
  Ordinary failed inner writes roll back to a savepoint; propagating failure aborts
  the complete action. Whole-transaction SQLite aborts preserve their original error
  and cannot be swallowed into a successful partial action (three reproduced failures). No helper commits another connection while the action is incomplete.
- Recovery: exact retries return the committed action result; changed payloads under
  the same retry identity fail. Dependency-first projection keeps parent lifecycle
  distinct from content revisions so a rename does not invalidate existing children.
- Evidence: `tests/test_sync_transactions.py` (17 cases) and
  `tests/test_sync_operations.py` (17 cases), including a late-peer creation-time regression;
  targeted and full-check results are recorded in the implementation ledger. Tests assert complete stored research, concurrent retry
  outcomes, writer/receipt failure rollback, caller rollback, wrong database rejection,
  an attached-database boundary, and actual paged HTTP into an empty fixture peer.
- Trade-offs: explicit operation/schema adapters and retained history require more
  integration work than row copying. The connection seam accepts trusted application
  writers, temporarily owns SQLite authorization, and is not an untrusted-code sandbox.
- Limits: no production writer enrollment, hosted identity, arbitrary file atomicity,
  physical power-loss, real mobile storage or full-workspace synchronization claim.
  No private content, accounts, local absolute paths or global installation recorded.


## Observed-set protection for complete ordering intents — 2026-10-26

- Status: `validated-local`; not a universal replacement for revision checks.
- Trigger: a complete list reorder must detect removed/restored/new members without
  conflicting merely because a paper's citation or reading status changed.
- Invariant: compare a versioned, domain/scope-separated digest of effective-active
  identity/incarnation pairs, alongside the order entity's own revision. Reject an
  invalid permutation; preserve a stale-set intent as a conflict. An empty matching
  digest cannot authorize a deleted scope. Recreated members have new incarnations.
- Recovery: keep the accepted payload/history unchanged. Project exact surviving
  incarnations and append later creations by accepted creation-receipt sequence;
  latest metadata revision is not creation order. Pending local work stays protected.
- Trade-off: an intervening add/remove returning to the identical active set may
  accept the old complete permutation. This is valid ordering intent, not a guarantee
  that membership history never changed. Generic child/parent delete guards remain.
- Evidence: `tests/test_sync_ordering_contract.py` pins literal cross-language bytes
  and digest; contract/service suites passed 55 cases. Shared action suite passed
  21 cases using isolated actual-schema databases, including late-citation/default
  order, retries and receipt rollback. Full-check results belong in the work ledger.
- Limits: bounded private protocol and trusted projection adapter; no production
  writer enrollment, general CRDT, hosted authentication or mobile acceptance claim.
  Synthetic research only; no credentials, real user content or global installation.


## Authenticated document intents and late file completion — 2026-10-26

- Status: `validated-local`; repository-local evidence, not cross-project reuse.
- Trigger: research metadata must converge while a PDF is missing or interrupted;
  switching accounts or document versions must not activate late, unrelated bytes.
- Invariant: authenticate expected workspace/device before sending bytes. Commit
  received metadata and cursor without waiting for a file. Verify hash/size/readability
  separately, then atomically recheck current target/session before applying its binding.
  Server ownership follows durable verified bytes, not merely a matching client claim.
- Recovery: retain the previous binding when replacement fails. Retry unfinished
  corrupt partials explicitly; never delete a finalized object as partial cleanup.
  Source read offsets and acknowledged durable EOF are different during overlap retries.
- Evidence: `tests/test_sync_transfers.py` passed 32 fixture cases, including real
  loopback HTTP, wrong-account upload denial, restart/resume, rollback, duplicate
  activation and late completion. The combined transport/client/service boundary set
  passed 137 cases before the final two session-publication cases were added. The
  implementation ledger records the subsequent full-check result.
- Limits: trusted owned filesystem, explicit private library APIs and local fixtures.
  No production authentication/hosting, reader activation, real research, installer
  or phone acceptance is established. Server chunk-read efficiency remains a gate;
  a metadata-only cache must not silently weaken content verification.
- Privacy/promotion: no tokens, personal content or absolute local paths recorded;
  no global skill installation or automatic promotion.


## Activate current content, retain exact open content — 2026-10-26

- Status: `validated-local`; a repository-local refinement for document editors.
- Trigger: a replacement PDF arrives while a reader has selected text and an unsaved
  note; positional figure/page IDs would otherwise reuse an older deck asset.
- Invariant: strict current-target checks gate new activation, while an already-open
  version remains navigable only with unchanged verified bytes and its original
  workspace context. Invalid contexts disable coordinates without deleting drafts.
  Native replacement must stage before swapping; unload must release native handles.
- Recovery: show the pending version, allow explicit retry, retain old assets and
  version their citations rather than silently relabeling old coordinates.
- Evidence: 29 actual reader/context fixture cases passed, including a reproduced
  Windows Qt handle leak fixed by view detachment/document disposal; 26 resolver
  tests passed. Versioned derivatives/intake are covered by a 92-test regression
  set. Full-check results are recorded in the implementation ledger.
- Limits: offscreen Windows/isolated fixtures; no Mac/phone/installed-app or hosted
  service claim. This does not establish full research-writer capture or turn file
  metadata into permanent cryptographic proof. No real content or credentials used.


## Actual writer capture and observed note edits (2026-10-26)

Status: validated-local; enrollment and producer coverage remain incomplete.

Existing store callers included explicit inner commits, so a context-exit-only
outbox hook would miss already durable changes. The opt-in connection now captures
typed dirty scopes before each real commit; remote projectors suppress echo but
still maintain lifecycle markers. Tests cover raw SQL/cursor transaction bypass,
savepoints, REPLACE identity, statement-cache policy, atomic receipts and rollback.

The desktop editor captures the note's observed base on load. A stale save rolls
back research/outbox and retains a deterministic candidate; repeated Retry returns
one retained version. The dialog preserves its draft and selection on failure.
Actual notes/list/intake fixtures passed 130 combined checks plus four final boundary
regressions. Source: `sync_capture.py`, `tests/test_sync_capture.py`,
`tests/test_note_observation.py`, and ADR0007. Full-project evidence is recorded in
the implementation ledger after integration.

Limits: SQLite-specific guard details are not a universal ORM recipe. Capture alone
does not infer AI input provenance, atomically publish legacy files, enroll a real
workspace, provide candidate review/publication, or authorize remote uploads. The
remaining producers must supply their start-time graph and document observations.


## Delayed output bound to original inputs and storage (2026-10-26)

Status: validated-local; first producer/editor slice, not complete writer coverage.

The actual close-reading and list-survey producers now capture absent/existing
outputs and the SQL inputs used in their prompts. A changed target, membership,
analysis or PDF preserves generated content as a candidate. Publication uses the
original database binding rather than whichever workspace is selected at completion.
An actual replaced/rebound database exposed a second failure mode: saving even a
rejected candidate there contaminates the replacement. An owned recovery sidecar
now retains that result without changing the replacement's tables.

Windows replacement fixtures also exposed SQLite read helpers whose connection
contexts ended transactions without closing handles. Explicit closing fixed the
real file-replacement assertions; no test was weakened. Generation/reader/adapter
fixtures passed 124 combined cases. The parent survey/note/activity/stress set
passed 105 cases, including original-workspace subprocess binding, duplicate job
exclusion, stale editor drafts, candidate retry identity and legacy timestamps.
These counts overlap; do not add them to infer unique full-suite coverage.

Evidence: `research_generation.py`, `document_reader.py`,
`tests/test_research_generation.py`, `tests/test_survey_observations.py`,
`tests/test_research_job_lock.py`, and `docs/research-generation.md`. The integration
ledger records the full-project check after the coordinated batch freezes.

Limits: isolated Windows databases and simulated model calls; no real account,
production enrollment, Mac/phone or hosted service claim. Sidecar retention is not
automatic candidate application or backup restoration. File-backed producers and
other AI phases require their own observed inputs and verified publication paths.
No global skill installation or private content is included.


## Offline parent continuity for delayed output (2026-10-27)

Status: validated-local; full integrated check recorded in the implementation ledger.

An unenrolled workspace could delete and recreate a paper with identical metadata
while generated work was pending. Comparing ID, target content and creation time
did not detect the new parent. Twenty initial regressions exposed the missing epoch
or legacy-record policy. The shared helper now installs persistent local epochs
before observation; replacement/deletion/ID changes invalidate them, while ordinary
metadata changes preserve them. A caller-owned rollback remains uncommitted and
cannot authorize later output through an epoch that never became durable.

Generation receipts accept legacy contexts for reading and backup, but automatic
publication of epoch-less work retains a candidate. Explicit review selects and
observes a new target. Twenty-two lifecycle cases passed, including identical
recreated lists and malformed recovery tokens; the earlier combined generation,
review and lifecycle group passed 80 overlapping cases.

Evidence: `research_lifecycle.py`, `research_generation.py`,
`tests/test_generation_lifecycle.py`, `tests/test_research_lifecycle.py`.
Limits: synthetic SQLite workspaces and fake model calls; local epochs are not
portable sync incarnations, account authorization or proof of historical identity.
No global installation or deployment was performed.

## Source-pinned cache lookup and deletion knowledge (2026-10-30)

Status: validated-local focused fixtures; combined full gate pending in the
implementation ledger. This is project evidence, not a global installation.

The annotation pipeline's existing-source cache returned PDF A before checking
an explicit expected PDF B. Moving identity checks before the fast path makes
bad displayed hashes fail before a model call, permits explicit regeneration for
verified B, and preserves known canonical deletion instead of resurrecting an
old compatibility cache. Analysis and automatic dive producers carry their
original source identity through completion rather than recapturing a newer PDF.

Evidence: six parameterized source-cache cases in
`tests/test_reading_annotation_source_cache.py`; actual pipeline cases in
`tests/test_analyze_annotations.py` and `tests/test_dive_annotations.py`.
The source/workflow/UI selection passed 42 cases. Selections overlap and are not
a unique full-suite count. The combined integration ledger records subsequent
project checks.

Limits: real synthetic PDFs with simulated providers; no actual account, paid
call, hosted sync, or Mac/phone acceptance. A located source quote does not prove
that its associated claim is supported. Standalone legacy compatibility helpers
have a separate API and are not a substitute for source-pinned production calls.

## Native file revisions for cached proof reuse (2026-10-30)

Status: validated-local focused Windows filesystem fixtures; whole-project
integration gate remains required. No global skill installation.

An actual managed PDF retained offline-ready status after a same-size mutation
and restored mtime. Adding Windows ChangeTime initially passed 132 affected cases,
but a later combined run exposed a same-clock-tick collision. The failing assertion
was preserved. The final local observation supplements timestamps with the per-file
USN revision; unavailable/unknown records fail closed. Initial byte hashing,
bounded reads and path/handle checks remain. Thirty-two rapid restored-mtime
writes and closed native-record parsing are covered.

Evidence: file_change.py, test_file_change.py and
test_offline_proof_file_change.py; 44 affected cases passed in 65.79 seconds.
The subsequent source/claims/offline/controller selection passed 144 Python cases
and 198 mobile cases, with four actual authenticated HTTP runners. Selections
overlap; do not sum them.

Limits: native observations were tested on the development Windows filesystem,
not every Windows/removable/network filesystem or native Mac/phone. Metadata
and USN observations do not defend against a hostile filesystem/kernel that can
forge all version data. No credentials, private papers or real provider calls.

## Delayed credential delivery (2026-10-30)

Status: validated-local focused fixtures; complete candidate gate remains required.

A background native-vault load verified its original workspace, but SQL binding
changed after worker completion and before its queued GUI callback. The old dialog
filled the former token. The regression failed against that dialog; three boundary
cases then passed with bounded local binding checks, followed by 99 merged
connection/session/packaging cases. These are overlapping selections.

Evidence: `connection_vault.ConnectionVault.current`, the connection dialog's
scope guards, and `tests/test_connection_vault_ui.py`. The later device-management
vertical also exercises queued old results and confirmation-time connection changes.
No native credential API, real account, paid model, hosted service or daily database
was accessed. A cheap metadata guard at delivery does not replace worker-side
source validation or per-request authorization, and must not hash PDFs on Qt.


## Read-only verification and sealed audit views (2026-10-30)

Status: validated-local focused fixtures; the complete integrated gate is pending.

An actual appraisal passage had an unchanged owned original and successful byte
verification, but its source jump was refused. The existing verifier opened a
write-capable SQLite connection; its close checkpointed WAL, invalidating the
view's native database observation. The regression recorded current/verified/
current as true/true/false. A dedicated read-only CaptureConnection retains the
real owner/binding and source-byte checks without causing that checkpoint.

Evidence: `audit_inputs.verify_loaded_source` and source-navigation cases in
`tests/test_appraisal_dialog.py`, with unbound and enrolled fixture workspaces,
real PDF bytes, duplicate activation, late paper changes and preserved drafts.
The affected audit/appraisal/cache/runtime selection passed 85 cases; a later
provider/model selection passed 69 overlapping cases. These are partial checks,
not independent totals or whole-project acceptance.

Limits: native fixture workspaces and fake model replies. No daily data, real
account, native vault, remote service or physical Mac/phone was used. Read-only
connections still require explicit lifetime management; the separate full-suite
Windows replacement failure is not explained or fixed by this finding. A located
quotation still does not establish semantic support.

## Scoped observer lifetime and SDK test provenance (2026-10-30)

Status: validated-local; maintenance commit `987c365` passed its complete gate.
The feature-branch contextual backport and its independent full gate are pending.

A warm run observed an older window's background poll reading a newly selected
fixture database through a mutable global path. The maintained observer now
captures the original path/native identity, stops admission on explicit close or
QObject destruction, drains admitted work and rejects stale GUI delivery. Native
fixtures hold A's read while switching to B and replace B without waiting for A.
Missing initial files do not grant authority to later replacements. This does
not establish the cause of the separate v0.5 Windows replacement failure.

The first isolated maintenance gate also discovered a seventh tool from a
foreign editable checkout instead of the maintenance catalog. The installed MCP
SDK deliberately filters inherited PYTHONPATH. Explicit stdio-child test env
pins the intended source; current and foreign outer-source variants both retain
exact catalog, idempotent persistence, error and helper-restart assertions.
Packaged acceptance retains its independent executable path.

Evidence: `desktop/workspace_changes.py`,
`tests/test_workspace_changes_lifecycle.py`,
`tests/test_workspace_changes_window_close.py`, and
`tests/test_local_integration.py`. The unchanged complete maintenance gate passed
1,471 Python/desktop cases with one existing conditional skip and 18 frontend
cases. Source and pinned public font hashes were verified before and after.

Limits: fixture SQLite/native Qt and real local SDK processes on Windows. No
real account, paid model, user database, cloud deployment, native vault or
physical Mac/phone was used. These are project-local patterns, not global
installation or provider authorization. The v0.5 integration remains unreleased.


## 2026-10-31 ? Worker admission before installer launch

Status: validated-local for the observed UI boundaries; complete feature gate
and installed-device acceptance remain separate.

A source-bound reading-position worker exposed a restart/update path that could
launch its installer before closeEvent refused to close. Three real Qt fixtures
failed before the launch boundary consulted the position controller. The existing
worker tuple now includes that optional controller; thin legacy readers remain
supported. The affected selection passed 99 Python cases.

A selected-deck audit exercised the same boundary through its owning presentation
pane. The pane retains weakly tracked audit workers until drain even if the review
dialog is hidden or destroyed. Its producer-only state stays separate from this
external lifecycle check, so a result does not invalidate itself. The canonical
deck/audit selection passed 101 Python cases, including actual configured update
actions with a fake installer. The integrated positions/Inbox selection also
passed 248 Python cases; counts overlap and must not be added.

Evidence: desktop/main.py, desktop/reading_position_controller.py,
desktop/presentation_pane.py, desktop/deck_audit.py;
tests/test_position_update_guard.py and tests/test_deck_audit_ui.py.
No real installer, account, model call or owner workspace was used. This
project-local lesson does not authorize deployment or prove every worker has
been audited. It is not a global skill installation.

## Window callers beyond a scoped observer (2026-10-31)

- Pattern ID / revision: local-integration-window-ownership-v1
- Status: validated-local on maintenance; contextual 0.5 focused integration passed.
- Trigger: a full feature gate still observed the next global workspace after the
  watcher had been bound correctly. Controlled queued Qt callbacks reproduced
  seven MainWindow/update failures and two notification seen-write failures;
  two current-workspace controls remained valid. The earlier file-lock failure's
  cause is not established by these observations.
- Decision: capture the original database path/native identity before deferred
  reads, guard the caller and owned banners, and use explicit-path connections.
  Accepted close stops observers; a stale window with unsaved drafts remains open
  with a local notice rather than saving into another workspace. Busy/close-veto
  paths retain their original ownership and continue to drain.
- Preconditions and limits: this is an outer window admission lease, not a
  document hash, research row revision, sync binding or authorization capability.
  Retain stronger source and writer checks. Tests cover switches at admission,
  queued delivery and modal/preparation hooks; arbitrary foreign-thread rebinding
  halfway through a synchronous legacy helper is not certified.
- Evidence: maintenance commit e926be9; desktop/window_workspace.py, main.py,
  update_banner.py, analysis_settings.py; test_main_window_workspace_scope.py
  and the unchanged workspace_changes lifecycle, update and close tests.
- Validation: complete scripts/check.py passed 1,527 Python tests, one existing
  conditional skip and 24 frontend tests; Privacy/Ruff passed. All 470 source
  inputs and two runtime fonts stayed unchanged. The focused 145-case selection
  overlaps this gate and is not an additional total.
- Live limits: actual isolated SQLite, native replacement and offscreen Qt
  callbacks; remote update fetch and installer launch simulated. No physical Mac,
  real account/model/vault, owner database, cloud deployment or release action.
- Privacy/promotion: repository-relative paths and synthetic observations only;
  no raw research, identifiers or credentials. No global installation; feature
  integration and its complete gate remain separate.

## Projection ownership independent of rendering (2026-10-31)

Status: validated-local on maintenance commit 8bc4a3b; feature adaptation has a
separate gate. This adds evidence for the existing delayed-delivery/window rules,
not a new global installation.

A native citation map retained callbacks after paper/list/workspace changes.
Its projection lease now includes its actual map, paper, list and outer window;
HTML nonce rotation alone does not retire the map. Per-projection submission
identity survives rebuilding the widget, while failed admission permits retry.
A rejected old callback must not stop a newer projection's timer, and an old
layout must not trigger fresh SQL into the current workspace.

Evidence: desktop/cites_pane.py and tests/test_cites_map_scope.py. Original
controls recorded 13 failures/two valid cases; a rebuild duplicate and two stale
timer/layout failures were recorded separately. The final full gate passed 1,549
Python and 24 frontend tests with no skips; 471 source files and 87 existing public
runtime dependencies stayed unchanged. Counts from focused selections overlap.

Limits: native Qt and isolated SQLite on Windows; external process/network
boundaries simulated. No user research, real account/model, service deployment,
release, or installed Mac/phone acceptance. These are project-local observations;
source ownership, research revisions and authentication remain separate checks.


## Explicit native scientific workflow (2026-11-13)

- Pattern revision: existing one-owner compound transaction and captured-context
  boundaries; additional project evidence, no new global rule.
- Status: validated-local. Project: Paperfact v0.5 development.
- Trigger: wiring the actual application coordinator first attempted DDL through
  a protected native connection, then checked a capture-bound loaded owner through
  a plain journal connection. Both were refused before model invocation. Native
  file preparation also recreated a missing blob index in a regression fixture.
- Decision/invariant: use the actual capture-aware owner connection for the whole
  compound action; require trusted existing native schema/store rather than
  relaxing owner/authorizer checks or manufacturing replacement infrastructure.
  Unbound initialization stays a separate explicit branch. Exact original bytes,
  science/history and genuine outboxes commit together; retry verifies the prior
  evidence without another completion. GUI delivery checks its loaded context.
- Preconditions: an app whose native binding is connection-scoped and whose file
  ownership is separate from cached bytes. Ordinary SQLite clients do not need a
  connection subclass simply because this application uses one.
- Alternative/trade-off: copying owner metadata or removing a guard would hide a
  scope mismatch. Explicit capture-aware transactions retain the existing native
  lifecycle and restricted-writer contract at the cost of an adapter seam.
- Implementation: `lineage_workflow.py`, `lineage_shared_publication.py`,
  `desktop/lineage_dialog.py`; existing native journal/source readers unchanged.
- Evidence: `tests/test_lineage_workflow.py`, `test_lineage_workflow_native.py`,
  `test_lineage_desktop.py` and `test_research_tasks.py`: focused check **41 passed
  in 76.24 s**, 79.5 s total, zero skips; privacy/Ruff pass. An earlier related
  original-reader gate passed 76 cases in 154.60 s. Selections overlap.
- Limits: synthetic PDFs and model responses, actual offscreen Qt/SQLite and
  loopback native service; no real account, paid call, owner research, deployment
  or installed Mac/phone acceptance. The broader earlier Lineage diagnostic had
  638 passes and two table-existence expectation failures; the current full
  application gate remains unproven. No release claim follows from these tests.
- Privacy review: no credentials, identifying paths, raw user prompts or research
  content included. No telemetry upload, global installation or rule promotion.


### Recorded parent recovery, 2026-11-14 (validated-local)

- Trigger: new recovery roots broke old child/order lifetimes; guessed old IDs
  were accepted, while legitimate child restore failed after parent restoration.
- Invariant: verify immutable source/native receipt chains, then independently
  check the current writable parent. Never replay the old envelope or infer a
  recovery grant from ID equality. Recompute order scope/set digests natively.
- Evidence: `sync_recovery_choices.py`; native chain/refusal/restore cases in
  `test_sync_recovery_choices.py`; actual Qt sequence in `test_recovery_changes_ui.py`.
  Focused proof 7 passed/38.1s total; affected critical/desktop 32 passed/65.4s;
  actual reference-authority and native peer journeys 2 passed/18.0s total.
- Limits: synthetic isolated local fixtures, supported v2 typed content only;
  original/file/compound ownership, arbitrary parent migration, installed devices
  and hosted acceptance remain open. Not a rule for ordinary single-DB CRUD.
- Privacy: synthetic content only, no account tokens, owner paths or raw research.
  No new global installation or cross-project reuse claim.

- Regression selector: `python scripts/check_bounded.py --profile focused --python tests/test_sync_recovery_choices.py::test_explicit_root_restore_preserves_historical_proofs_for_child_restore`. This selector passed in the recorded 7-case gate. Final peer-order/budget/skill/docs gate: 25 passed, 23.3s total.
