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
