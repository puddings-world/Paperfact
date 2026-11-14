# Device recovery review scenarios

All fixtures are synthetic and isolated; no owner research, account, GCP, model
or real device is accessed. No older test/expectation was weakened or skipped.

| Cases | What the researcher/caller observes |
|---|---|
| Caught-up review, repeated invocation | Exact counts, no bodies/credentials in receipt, unchanged source and authority/backup |
| Newer received, acknowledged and unconfirmed operations | Distinct overlapping categories; old pending journal remains intact |
| Successful send with lost acknowledgment | Exact backup fingerprint identifies already-preserved work without modifying the local acknowledgment |
| Foreign/damaged prefix, cursor gap, journal fingerprint or acknowledgment | Fail closed without source mutation |
| Cancellation and record/time budgets | No truncated/success result or persistence |
| Concurrent local save | Changed file/WAL invalidates the observation; new saved work remains |
| Actual CLI | JSON receipt or bounded failure; no login/network |
| Actual Qt picker/disclosure | Default collapsed advanced action, cancelled picker starts no job, visible readable counts |
| Repeated click and failed-job retry | One worker; retry remains available after failure |
| Held cancellation/close/switch/rebind | Worker drains, stale counts never populate the wrong view |
| Completed worker, queued GUI delivery, same-file rebind | Actual GUI thread/timing assertion; binding is checked at delivery |
| Chinese/local-only UI | Exact UTF-8 text; action disabled for unenrolled data |

New cases: 13 backend and 8 Qt cases. The original path guard rejected independent
sibling inputs; corrected it to reject a device database inside the selected
backup. Initial UI fixture had not selected the actual Advanced task page; the
final tests navigate it before testing visibility. UTF-8 pipe loss was corrected
in source and guarded by the exact Chinese assertion.

Initial native runs aborted during garbage collection after the close/next-worker
sequence, not a passing run. Isolated groups and a verbose reproduction were
recorded. The new panel now holds its owner weakly and background closures retain
only the service, not widgets. The final original eight-case sequence completed;
the exact teardown root cause is not established as a universal Qt issue. A
separate delayed-delivery/thread assertion was added; no existing assertion was
removed. Do not infer production/platform stability from one focused scope.

Pending: explicit per-change fresh-identity reconciliation, complete research/file
preservation and guided restore journey, coherent full suite, real hosted disaster
recovery, installed Windows/Apple Silicon/phone acceptance. The UI is a point-in-time
review, not automatic migration or background sync setup.

Final affected gate: `build/device-recovery-integrated-20261114.log`, **144 passed
in 92.84s**. This includes 21 new cases plus 123 existing workspace, sync,
administration and authority recovery cases. The eight-case UI receipt in
`build/device-recovery-ui-thread-diagnostic-20261114.log` (2.61s) overlaps that gate.
Docs: `build/device-recovery-review-docs-20261114.log`, 52 passed in 1.41s.
Privacy, all-repository Ruff and scoped whitespace passed. Final synthetic UI
capture: one passed in 1.26s; viewed with an explicit installed font and generic
displayed location. It is not installed-app visual acceptance. Seven exact
source/test hashes are recorded in `build/device-recovery-review-integration-20261114.json`.
The old failed full report is retained; no full gate or release is claimed.


## Guided comparison and note-copy integration (2026-11-14)

The existing candidate is now in normal desktop source paths. This extends the
read-only count review; it does not claim all-domain recovery.

| Requirement | Selected test / observed outcome |
|---|---|
| Compare and copy explicitly | `test_visible_native_review_copy_and_refresh_preserve_old_and_existing_notes`: visible old/current bodies, one native write, existing/source notes unchanged |
| Cancel, close, switch, rebind | `test_held_apply_refuses_after_cancel_close_workspace_or_binding_change`: each held action drains without a wrong-target write |
| Queued stale target | `test_changed_target_at_queued_comparison_delivery_cannot_enable_copy`: no stale capability becomes usable |
| Failed source review | `test_failed_backup_review_still_rechecks_binding_before_gui_delivery`: delivery checks binding even after worker failure |
| Durable repeated review | `test_reopening_review_cannot_copy_same_recorded_change_twice`: one target note/outbox operation across refresh/reopen |
| Unsupported content | `test_unsupported_change_has_clear_pending_state_without_enabling_copy`: list and PDF-positioned note remain readable/pending |
| Bilingual compact controls | `test_bilingual_compact_review_renders_and_enter_compares`: English/Traditional Chinese row labels, Enter navigation, source/current panes; glyph precondition prevents tofu screenshots |
| Stable fixture identity | `test_fixture_initialization_connection_is_closed_before_observation`: garbage collection cannot close a forgotten SQLite connection after a version lease |

The unsupported-content test supersedes the draft's non-note-only test ID; its
list behavior is retained and the exact-original note boundary is added. Existing
fixtures now close SQLite handles explicitly; no assertion was weakened.

Selected integration passed 13 cases in 26.70 seconds, 30.1 seconds including
privacy/Ruff. Initial screenshots had missing glyphs because this worktree lacked
the configured ignored font assets. Existing pinned assets were SHA-256 verified
and copied locally; the visual check now asserts actual Latin/CJK glyphs before
rendering. Local fixture results are not installed Windows/Mac/phone acceptance,
real cloud recovery or complete semantic/original-file verification.


Final critical/documentation/release-selection checks passed 26 cases in 12.45s,
17.0s including privacy/Ruff. The two bilingual captures were re-rendered with
actual glyph assertions and a synthetic display location; both were inspected.
The English capture is retained in `docs/images/recovery-changes.png`. These
counts overlap earlier selected checks and must not be summed as unique coverage.

Failure/retry and post-commit cancellation checks additionally passed 2 cases in
6.19s (7.25s bounded invocation). The retry reused the prepared payload and saved
one note; cancellation after commit kept the truthful saved status. No real
account, cloud endpoint or research workspace was used.


## Contextual typed decisions (2026-11-14)

The same desktop panel now exposes keep/add/replace/restore and note copy through
one contextual selector. The source-bound native core decides admissibility;
unsupported originals never acquire a generic write action.

| Requirement | Behavior test |
|---|---|
| Add/replace/restore are explicit and durable | `test_metadata_choice_is_explicit_saved_once_and_recognized_after_reload` (three lifecycle states): one new native operation; completed choice retained after reload |
| Cancel and keep-current | `test_keep_current_records_only_a_decision_and_confirm_cancel_writes_nothing`: confirmation defaults No; reentrant click starts no job; transient keep failure retries the same request; one local receipt and no research/outbox write |
| Stale modal result | `test_confirmation_cannot_apply_after_selection_changed` (selection/target): Yes cannot apply to another selection or overwrite the newer target edit |
| Replace rather than duplicate a note | `test_note_replacement_requires_explicit_choice_and_preserves_note_identity`: explicit selection/confirmation; same note ID, exact chosen body and one pending operation |
| Existing note flow/original boundary | Existing copy, failure/retry, close and PDF-positioned-note refusal remain covered |
| Bilingual visual check | Actual action selector and primary labels rendered with glyph assertions; both metadata screenshots inspected |

The first add/reload regression failed because the UI computed only currently
admissible actions and dropped the completed add. The UI now retains independently
validated saved receipts as well. No existing content or historical assertion was
weakened. A new note assertion initially compared SQLite Row objects with tuples;
normalizing row representation preserved the exact identity/content expectation.

The 10-case contextual/affected cohort passed in 70.98s, 75.9s total with
privacy/Ruff. Critical, modal-change, retry and visual/docs checks passed 28 cases
in 29.52s, 33.3s total. Final note/old-copy/original/refined-release-selection
checks passed 4 cases in 9.41s, 12.6s total. Counts overlap; no full suite or
installed-device/CI/hosted acceptance is claimed. New metadata cases join the
curated release profile; that entire expanded profile was not rerun this iteration.

The existing background-job and source-bound idempotency patterns were applied:
worker-owned I/O, source/target leases, explicit publication, no double jobs and
honest post-commit status. This adds no new global skill or owner-approval queue.

Final portable note-identity, stale-target and usage-contract checks passed 11
cases in 9.81s, 13.6s total. Invalidated observations also disable the action
button, even if an old prepared choice remains in memory. These overlap earlier
checks and do not claim another complete release-profile run.
