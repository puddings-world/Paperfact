# AI-job routing: human regression map

This map describes the new bootstrap/desktop integration in the isolated 0.5
candidate. It is intended to be tracked with source, not generated from English
function names. The five-function checkpoint catalog in `testing/catalog.json`
remains a separate, deliberately limited catalog; this map does not claim to
explain all project tests. Exact test counts/results belong to the corresponding
local gate receipt, not a product-completion percentage.

## Route resolution and child entry

Source: `tests/test_private_job_bootstrap.py`.

| Function | Actions and observable outcome | Boundary |
|---|---|---|
| `test_resolved_factory_pins_only_declared_tasks_and_profiles` | Capture the survey route, then edit its model/key. The captured model/key remain unchanged, an unrelated broken task does not block the survey, and undeclared task/profile lookups fail. | Isolated JSON settings; no account login. |
| `test_job_default_reaches_fresh_pool_threads_and_nested_capture` | Enter one validated child scope and create fresh pool workers with nested captures. Every worker gets the original model, key, budget and home; undeclared tasks fail, and the process default clears afterward. | No provider calls; not vendor credential-file isolation. |
| `test_bootstrap_validates_frame_before_cli_and_preserves_trailing_stdin` | Supply a valid frame followed by ordinary input. The simulated CLI gets exact confirmed argv and original route; trailing input remains available, dotenv is not read, and output contains hello/ready only. | Actual entry code, simulated CLI body. |
| `test_invalid_bootstrap_never_invokes_cli_or_changes_route` | Try truncated, wrong-request, wrong-command and oversized frames. All four return a fixed failure, never execute CLI, never install a route, and disclose no synthetic key. | Four parameter cases; no deployment identity/auth test. |
| `test_ordinary_cli_does_not_touch_stdin_or_private_scope` | Run ordinary `lists` through a simulated CLI body with no binary stdin API. It receives unchanged arguments and no private route/default is installed. | Ordinary integration/MCP behavior also remains covered by its existing tests. |

## QProcess startup

Source: `tests/test_cli_job_qprocess.py`.

| Function | Actions and observable outcome | Boundary |
|---|---|---|
| `test_partial_write_and_split_control_lines_keep_frame_private` | Split the hello and accept the frame 13 bytes at a time. The exact route arrives, stdin closes after queued data, ready/control lines stay hidden, and only subsequent progress is returned. | Fake bounded pipe; actual local process tested separately below. |
| `test_unverified_child_never_receives_private_frame` | Send old-CLI output, wrong ID, wrong version, ready-before-hello or oversized startup text. No private bytes are written; the process is killed, the frame clears and a zero exit is still failure. | Five parameter cases, not all legacy executable versions. |
| `test_startup_failures_clear_private_payload_and_cannot_report_success` | Trigger the startup deadline, failed start, early zero exit or broken pipe. The buffer/deadline clears and successful completion is refused. | Four deterministic cases; does not wait 30 seconds or contact a service. |
| `test_actual_qprocess_retains_route_and_keeps_gui_alive` | Prepare a real local child, change saved model/key before start, then run actual handshake/bootstrap and a fresh child pool worker. The worker verifies the original key/budget and reports original model; GUI timer events continue and protocol/private data stay out of user output. | Real local process; final CLI body is simulated and makes no AI request. |
| `test_oversized_startup_output_is_discarded_without_retained_payload` | Feed a one-megabyte invalid first line. Only one fixed failure is returned; no private bytes are sent or retained in parser/frame state. | Bounded parsing, not a general child-output memory benchmark. |

## Survey user action

Source: `tests/test_survey_private_job.py`.

| Function | Actions and observable outcome | Boundary |
|---|---|---|
| `test_confirmation_changes_cannot_retarget_the_original_survey` | Hold the admitted route, change settings during replacement confirmation, then activate repeatedly. Exactly one forced survey is launched using the original model/key; the original roadmap remains unchanged while pending. | Actual dialog/activity/SQLite, process start simulated. |
| `test_zero_exit_before_handshake_is_failure_and_retry_remains_possible` | Emit zero exit before hello/ready. The existing ActivityHub error state is shown, the roadmap remains intact, buffers clear, and a new request can launch. | Exact existing `error` state, not an invented `failed` enum. |

The integration changes the physical child argv to include the nonsecret private
prefix/request ID. Existing survey transport assertions now check that prefix **and
retain the exact original logical `survey <list> --force` command**. Their stored
content, cancellation, changed-workspace, repetition and stale-process assertions
remain. No existing behavior expectation is skipped or loosened.

Pure values/framing have separate cases in `test_ai_job_intent.py` and
`test_cli_job_protocol.py`: defensive copies, exact `model=None`, task/profile
allowlists, bounds, malformed types/versions/duplicates, partial binary I/O, exact
request/argv binding, safe repr/errors and ordinary trailing-input preservation.
These tests do not establish live-provider reliability, model quality, production
sync identity, scientific correctness or physical-device release acceptance.

## Add-paper and list-analysis actions

Source: `tests/test_child_ai_launchers.py`. These are real Qt widgets/activity state
and isolated SQLite data; the child command peer is simulated. The separate real
QProcess case above tests actual framing/bootstrap. No model, login, metadata
service or user's research is invoked.

| Function | Actions and observable outcome |
|---|---|
| `test_old_process_signals_cannot_finish_new_attempt` | Fail startup, retry, then deliver the old process's success/error. The new process remains current, its controls/activity remain running, and add-paper draft/temp input remain intact. Both launchers are tested. |
| `test_ai_child_keeps_original_route_and_exact_workspace` | Change settings after admission and activate twenty times. Exactly one child retains the original model/key and exact database directory; confirmed logical argv is unchanged and private values are absent from argv. Both launchers are tested. |
| `test_non_ai_pdf_job_keeps_ordinary_command_and_needs_no_ai_config` | Start PDF replacement while route capture would fail. Its ordinary command starts without a private handshake, in the original workspace. |
| `test_replaced_workspace_starts_no_child_and_keeps_draft` | Change the active database before launch. Neither launcher starts a child or creates the other database; the add draft remains intact. |
| `test_empty_input_starts_no_job_or_private_handoff` | Submit empty add text or empty queue argv. No child/temp file starts and the add controls remain available with an explanation. |
| `test_rejecting_pending_add_clears_temp_and_ignores_late_success` | Reject an active add dialog, then emit late success. The temp file/private startup buffer/deadline clear, the draft remains, no success is reported and activity is no longer running. |
| `test_successful_child_preserves_saved_result_and_completes_once` | Acknowledge the exact request/command, run a simulated CLI body against the real isolated research store, then deliver success twice. Membership remains one record, saved title/explanation remain exact and acceptance/continuation occurs once. Both launchers are tested. |

The stale-process case failed against the previous AddToListDialog because its old
completion cleared the new process. Native workspace and source guards are not
replaced by the route frame. Broad activity selection also exposed an unresolved
maintenance presentation fixture dependency on the old global thumbnail cache;
that error is retained, not hidden by a passing focused route selection. Complete
native-thumbnail parity and the merged full gate remain required.


## Preflight admission and delayed dispatch

Source: `tests/test_ai_dispatch_snapshot.py`. These cases use isolated settings,
synthetic keys and simulated login checks. They make no provider request.

| Function | Actions and observable outcome | Boundary |
|---|---|---|
| `test_gate_callback_and_nested_worker_keep_original_task_route` | Route survey to B, admit the action, then change B's model/budget before delivery. The nested worker still sees B's original profile/model/key/budget/home; independent later reads see the edit. | Actual scope propagation; worker invoked synchronously in this fixture. |
| `test_queued_requests_capture_before_wait_and_repeated_clicks_coalesce` | Queue two owners, activate the second 100 more times, then edit the default model. Only two checks and callbacks execute; both retain their original configuration. | Simulated check runner, not 100 AI requests. |
| `test_nested_recapture_keeps_scope_after_config_and_key_change` | Capture a scope, edit settings and its environment-key value, then recapture inside the job. Nested reads retain original values; later independent reads see the edits. | No credential-file or vendor-session snapshot. |
| `test_scope_detaches_mutable_caller_snapshot` | Mutate the caller's captured settings and key dictionary after entering its scope. The admitted scope remains unchanged. | Defensive in-memory copies. |
| `test_two_worker_scopes_do_not_borrow_each_others_latest_profile` | Start two pool workers under different captured profiles and synchronize their reads with a barrier. Each receives its own original profile and options. | Two synthetic workers, no provider concurrency benchmark. |
| `test_explicit_retry_after_failed_login_uses_new_selection` | Refuse profile A, confirm no callback ran, select B and explicitly request again. Only the new request launches, using B. | Failed-login handling is simulated. |
| `test_closed_pending_owner_never_launches_generation` | Queue a visible owner's request behind another check, close it, then deliver both checks. Only the first callback launches. | Visibility check, not a complete installed-app shutdown journey. |
| `test_new_reentrant_ui_request_reads_config_not_previous_request_scope` | While delivering A's callback, submit a new independent UI request after selecting B. The new request uses B rather than inheriting A's callback scope. | Deliberate new action differs from a nested worker of an existing job. |
| `test_queued_task_list_is_detached_from_the_callers_mutable_list` | Queue a survey, then change the caller's task list to slides. The queued request still checks and runs survey once. | Task-list ownership; not document-target validation. |
| `test_ready_auto_route_cannot_switch_provider_before_launch` | Simulate Claude discovery during successful preflight, then remove it while a synthetic Anthropic fallback key is present. Both the nested worker and child-frame route remain Claude; a later independent request resolves Anthropic. | Two parameter cases. The initial implementation failed both; actual vendor login/CLI execution is not exercised here. |

Local receipts for this follow-on: `auto-route-before.xml` (two reproduced
failures), `auto-route-after.xml` (117 selected passes), and
`auto-route-launchers.xml` (65 selected launcher/drain passes), all under ignored
`build/merge-resolutions/`. The selections overlap earlier runs and are not a
full gate or a completion percentage. Two older fake resolvers were adapted to
accept a default-task lookup; every existing assertion AST remains identical.
