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
