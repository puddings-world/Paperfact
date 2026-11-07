# Survey replacement and process ownership

This isolated 0.5 integration keeps topic roadmaps separate from ordinary survey
regeneration intent. A topic roadmap stores paper-selection reasons and its
search log; it must not be replaced merely because it has not been edited by hand.

The backend checks the captured survey target before calling a model. The dialog
asks for explicit replacement, then rechecks its native workspace and the exact
stored target after the confirmation event loop. Cancellation or intervening
changes start no child process. Accepted generation still uses the existing
observed publication and retained-candidate path.

A reopened dialog uses its workspace-owned activity hub to recognize the same
list's running job. Closing the dialog leaves the existing window-owned process
running. Each output, error and completion callback identifies its original
process; a failed attempt's late signal cannot finish a newer retry.

## Regression map

All cases below are in `tests/test_survey_maintenance_merge.py`.

| Test function | Operation and observable outcome |
|---|---|
| `test_cancel_keeps_roadmap_and_starts_no_job` | Decline replacement; one prompt, no process, original roadmap unchanged, run remains available. |
| `test_explicit_replacement_starts_one_forced_job` | Confirm and activate five times; one child request with `--force`, run disabled, content unchanged before result acceptance. |
| `test_changed_roadmap_during_confirmation_is_not_replaced` | Edit the saved roadmap during confirmation; no child, newer text preserved. |
| `test_workspace_switch_during_confirmation_starts_no_job` | Change the active workspace during confirmation; no child targets the old context. |
| `test_reopening_tracks_existing_job_and_completion` | Close and reopen while work runs; duplicate launch disabled, completion enables the new view without modifying the roadmap fixture. |
| `test_native_database_replacement_rejects_old_dialog` | Replace the database at the same path using real filesystem replacement; the old dialog starts no job. |
| `test_failed_launch_retry_ignores_old_process_signals` | Fail a launch, retry, then emit old completion/error signals; the newer job remains active and content is preserved. |

These use actual Qt signals/widgets and disposable SQLite files. Only process
start is replaced, so no external process, account login or model request runs.
Connections are explicitly closed before native replacement; no GC, native
identity mock or retry loop substitutes for this operation.

The new cancellation case failed on the prior dialog because no confirmation
was shown. The new failed-launch/retry case failed because an old completion
cleared the newer process. Original stored-data and visible-state assertions
remain in the regression cases. Full integration/release acceptance is separate.

## Remaining boundaries

- Full project checks and the remaining maintenance-test reconciliation still
  precede a merge commit or completion claim.
- Real child-process/provider and packaged-device acceptance are not established
  by the fake-start fixtures.
- The isolated survey launcher now carries an immutable resolved route through a
  private verified stdin handshake. A confirmation-time model change cannot retarget
  the admitted request. An actual local QProcess test covers startup and a fresh
  child thread pool; live providers and packaged cross-platform twins remain open.
  See [private CLI jobs](private-cli-job-protocol.md) and
  [their test map](ai-job-test-map.md). Other AI child launchers remain unwired.
