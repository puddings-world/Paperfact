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


### Device-local startup consent, 2026-11-14 (validated-local)

- Trigger: process-local continuous sync required reconnection after every restart;
  merely remembering a token did not authorize future background research uploads.
- Invariant: opt-in stays outside research and is scoped to a physical local DB,
  binding and exact credential fingerprint. Read the native store only after that
  marker exists; verify the server, then recheck context/permission at GUI delivery.
- Implementation: existing `connection_vault.py`, `desktop/continuous_sync.py`,
  sync dialog and MainWindow startup; no new service, plaintext token store or
  automatic enrollment. Native-store failure pauses; offline authentication backs off.
- Evidence: 10 focused boundary/UI/fixture-delivery cases passed in 20.2s total;
  actual MainWindow delivery plus bilingual rendering passed 3 cases in 15.2s.
  Tests include copied DB, changed credential, cancelled save, failed forget,
  queued handshake after permission/binding change, owner close and offline retry.
- Limits: injected native store and isolated reference authority; native prompts,
  installed upgrades and physical Mac/phone journey unverified. Not cross-project
  reuse, not global installation, and not authorization to deploy or upload research.
- Privacy: synthetic records only; no owner identifiers, tokens or research captured.


### Recovered-paper note copy, 2026-11-14 (validated-local)

The recorded-parent resolver is also used by note copy after explicit recovery of
a post-backup paper. An equality-only parent check wrongly refused valid mapped
lifetimes and could treat guessed old incarnations as sufficient authority.
The same source/native receipt proof now gates both metadata and copied notes;
no new journal format or broad replay capability. Focused proof/retry checks:
3 passed, 22.8s total. Both native peer variants passed; after correcting the new
fixture's review-scoped ID, both real desktop cases passed in 15.2s total.
Paper deletion remains unsupported and original-bound notes are not flattened.
This is another local adapter, not cross-project reuse or installed-device proof.


### Read-only SQLite source leases, 2026-11-14 (validated-local)

- Trigger: first native Lineage review failed despite an unchanged source DB.
  Native version observations proved that read-only opening created a zero-byte
  WAL. Settling fixture garbage collection did not change it. A connection-pinning
  attempt then broke the unchanged concurrent-write regression in rollback mode
  and did not survive empty-WAL cleanup; that approach was removed.
- Invariant: nonexistent and zero-byte WAL mean no transaction pages; main-file
  and every nonempty-WAL version, including native mutation tokens, stay strict.
  No long-lived connection, retry loop or DML/DDL is introduced by the version read.
- Evidence: two real WAL first-read review/index cases preserve research/paging
  and reject real later writes. All existing source-review/concurrent-write cases
  remain unchanged. The 63-case source/Lineage/peer/Qt/docs/critical gate passed
  in 129.2s total under the existing Windows CPU/time cap.
- Limits: local synthetic SQLite fixtures; no global promotion, native Mac/Linux
  resource-governor proof, hosted deployment, paid accounts or owner research.


### Import history in a fresh workspace, 2026-11-15 (validated-local)

- Trigger: actual local agent imports blocked first enrollment on three control
  tables; admitting them then exposed one-based versus native dense ordering.
- Invariant: preserve research, PDFs, complete order and validated private history,
  while the fresh workspace has no live source preview/idempotency authority.
  Unknown records fail closed; archived IDs/URLs never confer execution/file rights.
- Evidence: tests/test_enrollment_integration_history.py covers actual propose/
  commit, two receipts and previews, sparse prior positions, candidate/backup/
  detached restore, refusal, cancellation/source changes, retry and real Qt controls.
  Old preview execution refuses in the candidate. Existing input/order/archive
  rollback cases pass. Shared input class remains a pure legacy-compatible alias.
- Limits: known imports only, one project and local fixtures; no global promotion,
  provider calls, owner data, full in-place adoption or installed/hosted/device proof.


## 2026-11-15: acknowledged history after an interrupted pull

Status: validated-local in Paperfact; not hosted or multi-project evidence.
A received-only pre-upload guard missed accepted pushes when the following pull
failed. The local cursor could remain zero while its journal already knew a
remote sequence. A regression first failed with no SyncHistoryUnavailable raised.
Desktop now verifies both received frontier and a newer acknowledged operation;
mobile compares its complete retained acknowledgment. Missing/changed history
preserves exact local state and suppresses preparation/push on repeated attempts;
matching history resumes normally. Python's existing receipt stores only sequence
and operation, not the old outcome/head: no stronger proof is claimed.
The existing regression selector covers three checkpoint states and three remote
outcomes, with mobile engine/shell checks. No authority generation negotiation,
hosted rollback or physical-device guarantee follows from these fixtures.


## 2026-11-15: remote execution continuity across a bounded job

Status: validated-local in Paperfact; not a deployed/physical-device guarantee.
A frontier check at job start cannot fence a listener replaced before a later
push/blob request. The existing HTTP adapter now authenticates and advertises a
per-listener nonce; transports pin it and the receiver requires it for subsequent
research requests. A same-address real listener restart leaves local queued work
unchanged; explicit fresh connection can continue. Missing/changed response offers
and header stripping do not silently downgrade the job. Mobile bearer/cookie
transport shares the guard; reconnect generations reject old identity responses.
Actual JS/Python and isolated headless Chromium pairing/reload/reconnect/forget
journeys pass. Old unsupported blob/pairing capabilities remain typed errors.
No new account, persistent journal identity, automatic research replay or global
installation. This does not cover split-brain, unsupported live DB overwrite,
TLS/proxy deployment or persistent authority/history generation negotiation.
Python pin delivery is also rechecked atomically after parsing the identity:
a controlled delayed-body regression failed before that check, then passed.
This prevents a concurrent older identity response from replacing a newer pin;
it does not make transport history a persistent authority-generation proof.


## 2026-11-15: local controls versus migrated research

Status: validated-local in Paperfact, not arbitrary profile/OS coverage.
Actual update-cache and schedule writers plus private sharing/retry metadata made
otherwise valid first enrollment fail as unsupported KV. Registered controls are
now excluded alongside account/consent/usage files; unknown research still blocks.
Protected root account/cache/diagnostic trees are pruned before traversal, with a
scanner guard proving descendants are not visited. Root links remain invalid.
A bounded legacy queue adoption marker is retained in copy/backup/restore as data.
A synchronized workspace never reruns legacy queue-to-list construction, even
without that marker; repeated refresh preserves its entire SQL dump. Unbound
conversion still behaves normally. No old job, schedule or account authority is
installed. This is an explicit registry, not permission to ignore unknown files,
all JSON or every future setting prefix; declared originals remain verified.


## 2026-11-15: a research key family inside a mixed KV table

Status: validated-local in Paperfact; not arbitrary KV permission or installed acceptance.
Citation-neighbour graphs were research stored alongside private controls. Native
capture and snapshots now select only the closed citegraph paper namespace, validate
its bounded body and reconstruct the receiver-local key from the exact paper map.
Initial copies retain raw JSON and independent backups; package import uses the
same owner mapping, default preservation, explicit replacement and retry identity.
Two native clients retain concurrent versions, no-echo/delete behavior and private
settings; late provider results retain a candidate. Python/mobile share closed JSON
fixtures; the actual JS/Python service transfers the graph without changing drafts.
The v27 static artifact is verified locally, not deployed; no schema/credential
migration, global installation or paid call. Other KV/legacy and physical gates stay.


## 2026-11-15: a checksum-only input is not a complete private backup

Status: validated-local in Paperfact with Windows synthetic workspaces; native
cross-platform and installed-device acceptance remain separate.
Legacy compound jobs retained an extracted-text checksum/path without the actual
input. Reviewed first copies now retain a self-contained private request/text
record, verify exact UTF-8 bytes and hash, and reject changed or unknown layouts.
Only canonical workspace cache names are read; the observation never authorizes an
external path. File versions around the bounded read catch source replacement.
Private archives do not grant PDF ownership, revive a job or enter the live outbox.
Raw backups refuse declared text they cannot retain rather than claim completeness.
Evidence: tests/test_enrollment_history.py covers unchanged source, exact CRLF and
Unicode preservation, copy/detached restore, corrupted proof, no PDF grant and
external-path nonaccess. The existing release-selected agent-import enrollment
representative now retains citation, text and PDF beside its original assertions.
Two affected three-case slices passed in 13.2s and 14.4s (overlapping); no real
account/model call, global installation, cloud upload or broad temporary cleanup.

Native follow-up: the same first-sync representative passed on Windows, Mac arm64
and Linux in run 43677890610 at clean f7616ae. These are source/native fixtures;
physical-device and frozen GUI-adoption evidence remains separate.


Follow-up source evidence: first-copy coverage also retains canonical unreferenced
reading caches under existing unambiguous paper owners, without original grants,
active cache installation or outbox text. Sanitized-name collisions, invalid UTF-8,
oversize, concurrent replacement and aggregate bounds refuse the copy. Unknown
filenames remain blockers. The normal private-copy/detached-restore and existing
release-selected agent-import journey passed with exact bytes; the existing Qt
preview/prepare/open test displays the history-only snapshot count. Affected
checks: five in 18.5s total, then two in 8.8s after the bound/UI changes (overlap).
This is Windows source/Qt evidence after f7616ae, not native packaging or physical
acceptance. No new global rule or skill installation is inferred.


## 2026-11-15: selected offline reading includes its owned original dependencies

Status: validated-local, Windows synthetic workspaces only. A focal-only request
previously downloaded its own files while omitting related Lineage originals.
The existing metadata plan now validates current annotation/Lineage rows and
retains native source/parent lifetime pins. Download, pending status and late-result
checks consume that same exact bounded scope. Equal bytes do not substitute for
a different owner/lifetime, and missing manifests cannot hide behind zero pending
transfers. Unrelated primary PDFs/decks stay outside the selected action.
Evidence: existing test_lineage_enrollment_peer representative fails before the
fix, then covers focal-only transfer, actual original inspection, ordinary/resumable
verification, corruption, missing manifests and source-lifetime mismatch. Existing
claim and reading-link source plus selection/cancellation/download regressions:
61 passed in 263.5s total; strengthened native-pin representative 1 in 36.6s
(overlap, not distinct requirements). CPU bounded, no real account/model/research.
This reuses existing ownership/pin/guarded-plan patterns; it adds no wire protocol,
new module, global rule or installed/cloud/mobile acceptance claim.

## 2026-11-15: desktop received and unreceived acknowledgment prefixes

Status: validated-local native/HTTP/Qt only; mobile/fencing not yet established.
The actual desktop entry now saves bounded prefix proofs with receiver cursor and
acknowledgments, hashes exact wire records rather than reformatted numbers, and
checks research-write prefix/tip inside the authority transaction. A next-event
acknowledgment is independently recomputed; a valid concurrent advance retries.
A prefetch must reconcile a matching own intent in the same receive transaction:
otherwise a lost acknowledgment remains pending and incorrectly needs an old proof.
Legacy inboxes compare retained records before initializing proof; unreceived old
acks without proof need explicit review. Recovery retains proof observations as
inactive records instead of dropping them or granting a cloned device connection.
Evidence: existing sync_history_frontier verified representatives cover real HTTP,
restart/lost receive, forged acknowledgments, atomic rollback, same-tail forks,
concurrent advance, malformed pages, no downgrade and conflicts. Actual desktop/
Qt representatives show bounded preparation, retained last-success and visible
remaining counts. Limits: no malicious-authority proof, durable fencing, mobile,
other mutation guards, real host or installed device acceptance. This extends the
existing transaction/ownership pattern; no new global rule or installation.

## 2026-11-15: mobile proof reception and inactive recovery observations

Status: validated-local mobile/Python/Windows Chromium; no physical-device or
hosted acceptance. The same exact-record prefix contract now reaches the actual
mobile Engine.sync entry and existing bearer/cookie transports. Compute hashes
outside IndexedDB's synchronous update callback; recheck scope, generation and
retained anchor at the actual content/cursor/proof commit. Keep an initial seed
virtual until a verified transaction commits, so cancelling an initial held read
cannot mutate even protocol state. Receive before pushing; a lost reply can settle
from the contiguous stream without another upload or rebase of pending content.

Private recovery must preserve an unreceived commitment even though the content
cursor cannot reconstruct it. An explicit version/capability distinguishes the
archive extension; imports retain proofs and old receipts only as inactive history,
never a live cursor, connection or queued command. Legacy numeric receipts are
compared semantically; new commitments retain exact wire float/Unicode spelling.

Evidence: engine/recovery cases exercise same-tail forks, forged acknowledgments,
transaction failures, held delivery/local reads, migration and old-service refusal.
The actual Python HTTP fixture and Chromium IndexedDB reopen, source-position,
private recovery and cookie-pairing workflows pass. The position fixture proxy
initially blocked new routes; actual source/view assertions were retained while
adding only the required routes and moving lost-response injection to the real
push. Stale cache names and primary-button assumptions were fixed in the fixture,
without changing product authentication or relaxing source/recovery checks.
Limits: no malicious-authority defense, durable fencing, attachment/device write
proofs, native legacy-ack review UI, live host or installed/physical device result.
This extends the existing local transaction/recovery lesson, not a new global rule.


## 2026-11-15: attachment prefix guards at physical and ownership boundaries

Status: validated-local desktop/mobile/HTTP; device controls and durable fencing
remain open. The actual desktop upload wrapper and mobile original-source uploader
now pass their retained history point on explicit verified attachment routes.
Check it in every authority mutation transaction, not only the earlier handshake.
When verification runs outside a write transaction, check again before ownership
publication: private physical bytes and authenticated ownership are separate facts.
A failed final guard must leave ownership unavailable and permit a valid retry.
A valid concurrent suffix alone need not invalidate an immutable-byte upload.

Evidence: real HTTP test refuses begin/append/commit/cancel without database or
physical-byte changes on a wrong prefix, changes history during verification,
refuses ownership/read, repairs on valid retry and refuses old-route fallback.
The actual desktop PDF/deck journeys and Chromium source-position/recovery journey
pass with retained checkpoints on the upload routes. Existing digest, quota,
authentication and source-lifetime assertions remain. No live host/device result,
no retraction of sent bytes, and no new global rule, hook or installation.


## 2026-11-15: read-only device controls and issuer-bound grants

Status: validated-local native Qt/bearer/cookie; durable control history and
physical/hosted acceptance remain open. Device actions read the fully prepared
received/acknowledged prefix without silently synchronizing or changing research.
Absent legacy proof schema is initialized only by the authorized sync path; an
existing damaged/missing row is never reset. The suggested sync/retry path must
actually prepare old retained inbox records before another guarded action.

Bind an issued invitation to its original verified prefix and expiry. A valid
suffix/retry cannot refresh that grant's knowledge; admission checks the issued
prefix inside its enrollment transaction before claiming the code or storing a
credential. Existing admitted-device resume semantics remain separate. Recovery
accepts old/current schema but never restores live device grants into a new identity.
Evidence: actual device/pairing HTTP and Qt, changed-prefix browser refusal plus
same-code retry, real legacy acknowledgment/inbox preparation and exact local
preservation. Static shell v31 upgrades old shells while keeping research caches.
Limits: a research-prefix proof does not version every device-control change or
fence a restored service. No malicious-authority/physical-host guarantee, new
universal rule, global skill installation or telemetry collection.


## 2026-11-15: local authority listener ownership and worker drain

Status: validated-local on Windows; installed Mac/Linux and distributed authority
fencing remain unverified. Reuse the existing OS-backed process claim around the
listener lifetime, not only socket creation. Acquire before bind, release after
failed bind or admitted backend drain, and leave lock sidecars in place after exit.
A stale file is not a live OS claim. Interrupt incomplete protocol reads during
shutdown while retaining ownership until a held write finishes. Retry a lost reply
using its original operation ID, preserving exactly one accepted result.

Observed database lifetime uses native positive file identity and single-link
regular files; initialized connections refuse implicit empty-file recreation.
Evidence: duplicate/start-failure/repeated-close, held push and lost-reply retry,
actual child termination, incomplete-header shutdown, actual replacement/removal,
transaction rollback after identity change, hard-link/unknown-ID refusal, and online
backup excluding process locks. Affected HTTP/device/browser/admin tests: 122 pass
in20.11s (23.2s governed total). Selected mobile transport/session17 pass in3.281s;
actual JS/Python protocol passes in2.047s. All synthetic, isolated and CPU-bounded.

Initial shutdown-only failed to interrupt a Windows makefile header reader; the
bounded failure stack identified the actual socket read. Documented detach plus
socket.close prevents later buffered cleanup from closing a recycled descriptor;
the actual incomplete-header test then passes. This observed file lifetime is not
content authenticity, same-inode restore/ABA detection, a durable authority epoch,
a distributed lease, or proof of every control change. No new global rule or hook.


## 2026-11-15: explicit legacy acknowledgment proof adoption

Status: validated-local Windows core/session/Qt. Old accepted-but-unreceived
operations may lack a retained linked proof. Preserve the old journal/cursor and
queued work; compare bounded remote history with exact retained receipts/inbox in
an explicit read-only action. Carry immutable local evidence through resumable
in-memory pages. Acceptance rechecks authenticated service history and local
binding/evidence, writes only proof metadata atomically, and does not start sync.
A missing old proof table may be created only at explicit adoption; a damaged
existing row is refused. Core retry must use current transaction schema, not only
the pre-adoption observation (the first missing-table retry test exposed this bug).

Evidence: full affected63 in44.15s/47.2s total; strengthened retained-inbox/missing-
schema and all-SQL-except-proof preservation4 in2.35s/5.4s total. Normal/partial/
confirm-No/Yes, wrong remote receipt, changed local evidence, held read with
repeated activation/disconnect, Stop/retry and Close are covered. In-memory
progress is counts, not authority or diagnostic data. The delivered355382c native
candidate is unchanged; no installed Mac/hosted/device or durable control-history
claim, global skill installation, telemetry or new background service.

Final compact-fingerprint/budget core/session/Qt acceptance:12 pass in6.35s/9.4s
total, including over-budget refusal without writes. Earlier affected63 evidence
precedes the compact-witness refinement; no false exhaustive pass is claimed.


## 2026-11-15: official verified-only service and test-child provenance

Status: validated-local bearer/cookie/CLI/Chromium; no native rebuild or host.
Keep low-level trusted prototype APIs separate from the official service entry.
Official serve rejects old unverified research/blob/device mutation routes after
identity/execution checks; browser aliases normalize through the same policy.
Fresh grant redemption must check issuer-bound proof in the enrollment transaction;
unbound old invitations are refused without creating credentials. Existing reads
and authenticated-device resume remain usable, with no client downgrade.

Actual package-protocol testing exposed a source identity mismatch: isolated_env
properly stripped inherited PYTHONPATH, so a shared editable venv loaded the
integration checkout instead. A read-only subprocess printed its actual module
path/signature; source-only test children now pin the intended src explicitly.
Frozen acceptance remains source-isolated and asserts the actual packaged service.
A negative verifier injection for prototype-write success must fail.

Evidence: affected HTTP/browser/key/device/admin/verifier145 pass30.07s/33.3s;
actual delivered v31-artifact Chromium pairing/offline-note/reload/reconnect/forget
four journeys pass9.031s against strict Python service. Exact native355382c
candidate remains unchanged. Supported restore's fresh identity is distinct from
external anti-rollback/control history, which is still unimplemented. No new
universal rule, account/resource access, deployment, hook or global installation.


## 2026-11-15: authentic old-source data preservation

Status: validated-local source-format probe; native/installed/GUI gates separate.
Generate old data with pinned old writers rather than current schema helpers.
Verify source closure against the actual Git object, then isolate old/new imports:
only the old source child gets its path; the new candidate receives no override.
Compare exact old columns, exported content and file bytes before/after current
schema initialization. Additional new columns do not prove old values survived.
A missing known extension may mean no old data; a present malformed/view extension
must not silently disappear. The new probe exposed a real missing-table export
failure (reading goals/annotation metadata) and drove the bundle fix.

Evidence: initial7 upgrade/schema cases pass16.86s/20.0s after actual init;
notes/PDF/canvas/export damage and changed baseline must fail. Earlier affected41
pass27.08s/30.3s before adding the init stage. Latest published preview metadata
was0.4.3, while0.4.6 remained drafts; master was fully integrated. Native355382c
candidate evidence was retained, not relabeled. No real data, old installer,
provider account, paid call, global install, public release or deployment.

Final upgrade guard verifies actual new tables after init (a zero exit alone is
insufficient) and requires every old exported field to remain present. The no-op
negative fixture initially fell through to its deck-damage branch; corrected only
that fixture dispatch while retaining the specific schema-initialization refusal.
Final affected verifier/bundle/workflow42 pass34.05s/37.3s total. Remote tagv0.4.3
independently resolves to the same3abdf434555583ca4a6827892d54b487e9e40671.
