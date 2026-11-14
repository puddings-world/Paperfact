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
