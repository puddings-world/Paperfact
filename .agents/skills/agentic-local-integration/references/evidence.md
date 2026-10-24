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
