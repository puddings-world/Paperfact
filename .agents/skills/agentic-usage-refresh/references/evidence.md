# Paperfact quota evidence

- Status: validated-local; captured 2026-10-20; cross-project reuse not yet tested.
- Implementation: `src/paper_daily/usage_cache.py`,
  `src/paper_daily/desktop/usage_monitor.py`, `src/paper_daily/desktop/ai_picker.py`.
- `tests/test_usage_cache.py`:
  `test_parallel_refresh_shares_one_query_and_closure_cannot_destroy_worker`,
  `test_call_during_fetch_is_not_swallowed_and_failure_can_retry`,
  `test_cache_is_account_scoped_and_only_completed_account_is_invalidated`,
  `test_monitor_prefetches_unsaved_terminal_accounts_once_per_identity`.
- `tests/test_ai_picker.py`: `test_stale_usage_cannot_appear_under_another_account`.
- Baseline full check on 2026-10-20: Ruff, 656 Python and 18 JavaScript tests passed.
- Manual integration: Claude and Codex returned quota windows; Gemini account
  lookup returned `UNSUPPORTED_CLIENT` without usable current-tier/project data.
  Gemini successful per-model rendering was fixture-tested only.
- Boundary: adapter protocols and API availability change. Inspect the active
  installed package/official docs rather than globbing a stale bundled chunk or
  guessing response fields. Do not generalize one rejected account to all users.
- No account identifiers or OAuth data are included.

## Closeable metadata views follow-up

- Status: validated-local for the normal picker and task table. Read-only queries
  use daemon workers with queues and GUI-thread polling; canceling a view increments
  its request generation and disconnects delivery. Login/logout still use their
  separate operation runner and cannot be mistaken for a metadata cancellation.
- `tests/test_metadata_runner.py` verifies deduplication, main-thread delivery,
  close/destroy while pending, stale results after a new selection, and failure/retry.
- `tests/test_ui_stress.py` retains repeated-click coverage and now distinguishes
  closeable inline metadata queries from an active authentication operation.
- Picker tests verify that unconfirmed login does not display cached quota as a
  current authenticated snapshot. Account-management tests cover logout isolation.
- The legacy standalone usage dialog still waits for its worker. Cancellation here
  detaches presentation, not a promise to terminate vendor subprocesses immediately;
  existing provider timeouts remain the bound. No live logout or paid call tested.
