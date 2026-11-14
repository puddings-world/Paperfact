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


## Recorded parent lifetimes (2026-11-14)

| Requirement | Test / result boundary |
|---|---|
| New list retains membership, reading time and both order scopes | `test_receipt_proven_new_list_preserves_membership_reading_and_both_orders`: five new native operations; old source unchanged; reference authority accepts them; a fresh native peer retains saved content |
| IDs do not grant recovery | `test_parent_mapping_requires_valid_receipt_and_current_exact_lifetime`: unrecorded matching entity, corrupt receipt and unapproved recreation refuse without writes |
| Old incarnation cannot be reused as an implicit grant | `test_reusing_old_incarnation_without_a_recovery_receipt_does_not_prove_parent` |
| Explicit parent and child restore | `test_explicit_root_restore_preserves_historical_proofs_for_child_restore`: list/member/reading/order restore in sequence; prior native history remains usable |
| Later parent edits survive | `test_parent_proof_is_rechecked_at_apply_and_refresh_preserves_later_root_edit`: stale apply refuses; refreshed child recovery retains the newer parent name |
| Actual desktop actions | `test_desktop_recovers_new_list_and_membership_then_restores_changed_parent`: add then restore via the contextual selector and native worker |

Two regressions initially failed: guessed lifetime reuse was accepted, and valid
child restore was refused by conflating historical proofs with current parents.
The resolver now checks historical native/source relationships separately from
current active lifetimes. The eligibility guard follows the native client's
explicit restore contract for changed parents, even when the child's own active
flag remains true. Prefix lifetimes are checked against the actual backup graph.
Ordering proof includes historical item links and a recomputed complete-set digest.
Receipt bytes/counts and SQL work are bounded; a changed target invalidates apply.

Initial affected checks passed 9 cases in 45.19s (48.9s total). Refined proof checks
passed 7 in 34.74s (38.1s total). Critical, desktop and affected regressions passed
32 in 61.66s (65.4s total). The expanded authority/peer journey plus the unchanged
note-copy peer journey passed 2 in 13.96s (18.0s total). Counts overlap; this is not
a historical full-suite, installed-device, cloud, phone or semantic-original pass.
The two peer journeys now share their existing fixture-service capture helper.
No owner research, real credentials or paid calls were used.

Final saved peer-order, receipt-budget, skill-synchronization and usage checks
passed 25 cases in 17.54s, 23.3s total. The peer stores the exact three-list order
and new root incarnation. An over-budget receipt fails without writes. These
are overlapping focused checks, not a rerun of the expanded release profile.


## Notes on papers missing from the backup

The paper-deletion protocol remains intentionally unavailable. The real recovery
journey is a new paper and note saved after the authority backup: explicitly add
that paper in the fresh workspace, then copy its unanchored note.

| Requirement | Existing/new selector and observable result |
|---|---|
| Recovered paper proof | `test_note_copy_uses_proven_recovered_paper_and_retry_preserves_later_metadata`: the copied note uses the recorded new paper lifetime; retry leaves a later paper title and both source/history unchanged |
| No guessed parent authority | `test_same_paper_identity_without_recovery_proof_cannot_authorize_a_note_copy`: even deliberately reused old IDs/incarnations cannot authorize a copy |
| Desktop can still compare | `test_new_paper_note_review_requires_proven_parent_and_keeps_comparison_visible`: proven parent enables one copy; missing proof keeps both panes readable and produces no write |
| Actual peer delivery | `test_copy_syncs_through_recovered_authority_to_another_native_client[True]`: accepted new paper and note reach a fresh native client with the exact mapped parents/payload, and retry creates no extra operation |

The valid mapped-parent case initially failed with `target_parent_lifetime_changed`.
Note copying now uses the same bounded native/source receipt resolver as metadata;
parent equality alone is insufficient. Three focused copy/proof/retry cases passed
in 22.8s including checks. Both native peer variants passed in the next selection;
that selection then exposed a new UI fixture using a nonce-scoped change ID from
another review. The fixture now locates the current change by immutable operation
identity and checks the existing explicit absent-content label. Both UI cases
passed in 15.2s including checks. No existing behavior assertion was weakened.

The curated release selection replaces the old copy-retry representative with
this actual recovered-paper peer journey (which also asserts retry). Historical
retry, cancellation, stale-source and rollback cases remain available and are
selected when affected; the release case count is not expanded by this change.
Exact-original, compound file ownership and physical installed-device/cloud gates
remain open. Fixtures never access native credentials, owner research or paid AI.

Final critical/affected lifecycle, real UI, documentation, release-selection and
skill checks passed **41 cases in 95.29s**, **99.2s total** including privacy/Ruff.
The Windows job was capped at two logical processors and 25% CPU; no historical
full suite was run. Earlier peer/UI selections overlap this evidence. Native
Mac/phone prompts and a deployed recovery authority remain unverified.


## Exact-original positioned-note recovery (2026-11-14)

The existing copy action now preserves a v2 rich note's body, kind, timestamp,
page and complete anchor/selection. Preparation verifies native parent mapping,
current target ownership, exact PDF SHA-256, geometry and recorded selected words.
It reads either an immutable retained original or the desired primary PDF without
creating reader projections or changing the active PDF. Private note commentary
is never treated as a source quotation. Verification runs on the existing worker.

Confirmation verifies the source inside the native transaction, then checks file
mutation identity before committing research, receipt and outbox. A committed
retry returns the original receipt, including after later PDF removal; it never
re-creates or overwrites the copied note. Existing lifecycle guards are reused.

`tests/test_sync_recovery_positioned_note.py` contains six behavior cases:

| Requirement | Observable assertion |
|---|---|
| Exact passage and independent peer | Full payload reaches a separately joined native peer and its downloaded original; old source unchanged; retry creates one copy |
| Changed/missing bytes and repair | Refuse without writes, repair exact bytes and retry once; already-committed retry needs no PDF |
| Invented quotation | Mismatched selected words refuse without changing research |
| Real desktop controls | Compare enables the positioned-note copy; rapid repeated clicks save one operation |
| Primary PDF route | Copy works without a retained-original manifest and creates no reader projection |
| Mutation during write | Research written inside the transaction rolls back with outbox/receipt when source bytes change |

The initial six cases plus 17 existing note-copy cases passed: **23 in 121.82s
pytest / 125.0s including privacy and Ruff**, Windows 25% CPU/two-core governor.
The changed/missing case was subsequently extended with explicit pre-commit
missing-file refusal; its follow-up result is recorded with the integration gate.
No old assertion was deleted or weakened. Initial fixture failures reused an
enrolled device name and attempted to mutate unencoded PDF text; corrected to
actual independent enrollment and changed bytes.

Limits: page-only/hashless legacy notes still require explicit source mapping;
missing/unowned originals stay pending until available. This action does not
recover an absent original artifact, silently switch a primary PDF, replay old
operations or recover compound scientific groups. Physical devices, installed
applications, hosted deployment and release acceptance remain separate gates.


Final integration selection passed **26 cases in 19.15s pytest / 22.4s including
privacy and Ruff**: all 14 curated critical journeys, explicit missing-original
refusal/repair/retry, actual positioned-note desktop copy, the existing plain-note
copy UI journey and nine usage-document cases. Same 25% CPU/two-core/300-second
budget. Counts overlap the earlier 23-case selection and must not be summed.
No exhaustive historical, release or physical-device pass is claimed. The change
reuses the existing exact-source and native-transaction skill boundaries; no new
global rule or duplicate skill was introduced.


## Atomic note plus post-backup original (2026-11-14)

The note-copy API now accepts explicit `with_original=True`. It validates the
source note's current native paper lifetime and owned exact-original bytes; the
source does not need the desktop capture adapter merely to prove its projection.
The destination still requires its actual native writer and registered file store.
Comparison only reads and plans. Confirmation stages verified bytes using the
existing `prepare_source`, then calls `publish_source_in` inside the note's write
transaction. No new replay format, model call, primary-PDF switch or cloud service.

`tests/test_sync_recovery_note_original_group.py` covers five executed cases:

| Requirement | Observable assertion |
|---|---|
| Post-backup PDF plus note | Two typed native operations commit together; exact note/PDF reach an independently joined native client; old database stays unchanged |
| Failure after the original write | Simulated failure during the second child leaves neither ownership nor note/outbox; exact retry creates one group |
| Cancellation after the original write | Both children and journal records roll back; retry creates one group |
| Source mutation and sealed choice | Changed old PDF or forged include-original flag cannot publish research; exact-byte repair permits retry |
| Desktop review/confirmation | Clear note-plus-original label, read-only comparison, cancelled confirmation preserves cache/research, repeated confirmation saves one group |

The first case also edits the copied note and explicitly deletes the original:
committed retry preserves both later decisions; a new copy request cannot restore
the retired original. Byte staging may leave an unowned cache after a cancelled
write; it cannot grant graph ownership or change the active PDF.

Initial five-case selection passed **5 in 28.61s pytest / 31.7s including privacy
and Ruff**, under the Windows 25% CPU/two-core/300-second governor. The desktop
case was then strengthened to compare cache/research before comparison as well
as before cancellation; its final result is recorded with integration evidence.
Initial failures corrected source-side capture assumptions, an import location
and a fixture using another review's scoped change ID. Existing assertions remain.

This closes the original-plus-positioned-note dependency group only. Deep
analysis/claim/highlight/Lineage/deck groups, unavailable historical sources,
explicit original restoration, hosted deployment and installed/physical-device
acceptance remain separate required work. No historical full or release run.


Integration passed **33 cases in 74.58s pytest / 78.1s including checks**:
14 curated critical journeys, all six owned-original note cases, the strengthened
compound UI case, two plain-note retry/parent-proof cases, the existing plain-copy
UI journey and nine usage-document cases. No exhaustive suite was started.

Source inspection also exposed the missing-primary boundary: a desired primary
manifest can exist before PDF bytes arrive. Its filesystem failure now offers the
same verified note-plus-original action. The strengthened actual UI fixture uses
that state, confirms comparison/cancel leave both cache and research unchanged,
and saves exactly the pre-existing document operation plus two recovery children.
Final three plain/positioned/compound desktop journeys passed **3 in 22.07s pytest /
25.6s including checks**. The last source-input fences explicitly recheck target
identity/binding after old-source inspection and before byte staging.

This is an application of the existing typed-composition/byte-proof skill, not a
new portable rule. No duplicated skill, global installation, account access,
research upload or external deployment was introduced.


The final destination-fence change and pending-primary UI fixture passed **14 cases
in 42.26s pytest / 45.7s including checks**: all five original-plus-note cases and
nine usage-document cases. Earlier unaffected critical/owned-original/plain-copy
evidence is reused, not rerun by habit or summed. No production, OS-store or
physical-device acceptance is inferred from the fixture service.
