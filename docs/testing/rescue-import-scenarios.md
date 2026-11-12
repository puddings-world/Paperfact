# Rescue presentation import: reviewed behavior

Updated 2026-11-01. Unreleased, isolated integration source. This is a human-reviewed
scenario map, not a generated interpretation of test names. The new five test files
contain 36 functions expanding to 56 cases; neighboring regression selections are
separate and overlapping. The complete application check is still outstanding.

## User journey

1. Open **Research data -> Import rescued presentation**.
2. Choose a `.paperfact-draft.json` rescue copy. Read slides and speaker notes,
   captured images (including unused figures and captions), and source evidence.
3. Search for and explicitly select a local paper. No paper is guessed from a title.
4. Retain the imported content as a private review draft. The current deck stays intact.
5. Open its review, verify the slides and original sources, compare versions, then
   explicitly confirm replacement. Cancel keeps the current version.

Current retention requires an already enrolled receiver workspace; preview itself
requires no enrollment or PDF. This is a remaining implementation boundary, not
a reason to enable sync automatically. Unenrolled local-only import/review and
complete list-package/fresh recovery preservation still need their own adapters.

The file contains research data, not the sender's account, writer identity or
permission to alter a receiver. Imported model-input provenance remains incomplete;
it does not claim that the receiver's current notes produced the imported slides.
Rescue copies are distinct from list research packages, presentation PDFs and Google Slides.

## Exact scenario map

All paths below are under `tests/`. Each row describes actual fixture actions and
assertions. The network, model and account-process denial fixtures remain active.

| Test file / function suffix | Actions and observable assertions |
| --- | --- |
| `test_rescue_deck_import.py` / `readonly_preview_needs_no_receiver_or_sql_and_defensive_content` | Deny SQL/account access while decoding; preview all three images; mutate a returned copy and prove the retained preview unchanged. |
| same / `explicit_target_retains_complete_proposal_then_separate_review_applies` | Import into a deliberately differently named receiver; verify every image and scientific metadata, unknown producer inputs, one stable draft across retries, unchanged saved deck/outbox until confirmed review, then one operation. |
| same / `declared_sources_require_exact_receiver_ownership_and_never_substitute_primary` | Exercise current original A, retained A/current B, missing A, and A owned only by another paper. Only exact owned originals pass; current B is not substituted. |
| same / `explicit_envelope_hash_is_preserved_when_source_rows_are_unreported` | Preserve a declared original hash present only in the validated export envelope. |
| same / `unknown_source_stays_unknown_despite_current_primary_b` | Import with unknown original identity while B is current; the retained original hash and producer documents remain unknown/empty. |
| same / `preparation_never_silently_reopens_a_newer_displayed_file` | Replace with identical bytes at a new native file, truncate, or corrupt the already displayed file; refuse without a proposal or file rewrite. |
| same / `file_change_or_cancellation_during_validation_creates_no_proposal` | Change actual bytes or cancel during validation; do not create a proposal. |
| same / `pre_call_receiver_changes_refuse_without_retention` | Change binding, save a newer deck, delete the parent, or delete/recreate it before run; refuse without an import or extra outbox write. |
| same / `in_core_parent_recreation_keeps_only_history_and_review_refuses_old_parent` | Delete/recreate the actual parent during blob staging. An inactive original-scope draft may remain; its context is stale and review must refuse attachment to the recreated parent. |
| same / `failed_storage_preserves_actual_import_and_exact_no_model_retry` | Fail primary storage, then both primary/receipt storage. Preserve all captured images; retry retains the same candidate without replacing the saved deck or calling a model. |
| same / `rapid_repeat_is_single_flight_and_changed_target_request_reuse_refuses` | Hold a real retention call, attempt another run, then reuse the request against another target; reject both duplicates and changed-target reuse. |
| same / `parser_rejects_actual_reparse_parent_and_oversize_file` | Read through a real Windows junction/POSIX link and an oversized sparse export; reject both without an import. |
| same / `actual_cache_only_original_a_is_usable_while_primary_b_stays_unchanged` | Use an actual reading-position source cache for A while B is primary, without a published original-source operation. Verify exact current-parent ownership and leave B, cache receipt and outbox unchanged. |
| same / `cache_only_receipt_never_grants_foreign_old_or_tampered_source` | Exercise a foreign owner, old parent, changed PDF and missing binding; none grants source ownership. |
| same / `present_optional_binding_is_never_ignored` | Empty or alter an installed capture binding; refuse instead of ignoring it. |
| same / `original_native_owner_and_cancelled_admission_create_no_proposal` | Use the other native DB identity; cancel capture, preparation and run separately. No proposal is created. |
| same / `selected_original_budget_refuses_before_pdf_verification` | Lower the fixture byte budget below its actual selected original; refuse before expensive PDF verification. |
| same / `initial_corrupt_or_truncated_export_refuses_without_sql` | Try truncated bytes, unsupported JSON and a genuinely changed format key; refusal needs no database access. |
| same / `cancellation_during_actual_final_source_check_prevents_retention` | Cancel during the real final source check; no proposal, saved deck change or outbox write. |
| same / `seventeen_distinct_declared_sources_refuse_without_partial_retention` | Declare 17 originals, exceeding the 16-source bound; refuse without partial retention. |
| same / `prepared_cache_source_change_refuses_before_any_retention` | Alter cached PDF bytes or delete its ownership receipt after preparation; invalidate the request and leave saved research unchanged. |
| `test_rescue_import_dialog.py` / `preview_then_explicit_receiver_retention_preserves_saved_research` | Controlled backend, actual native UI: display notes/evidence/three images, activate 25 times, retain once; DB bytes stay unchanged by the shell. |
| same / `cancelled_chooser_and_failed_replacement_keep_displayed_preview` | Cancel a chooser, then fail a replacement preview; keep the old displayed content. |
| same / `literal_search_and_empty_selection_never_import` | Search literal `%_`; no selected paper or empty results cannot start import. |
| same / `fast_repeat_is_single_flight_and_target_change_does_not_relabel_result` | Hold import, activate repeatedly and change the selected paper; one call occurs and its result is not relabeled. |
| same / `held_preview_handles_context_end_and_native_view_teardown` | Hold preview while switching DB, closing, or destroying the actual native view; drain work and suppress stale delivery. |
| same / `failed_storage_keeps_actual_result_and_retry_does_not_restart_import` | Hold the actual incomplete result in the app and retry its storage, without another import or model call. |
| same / `review_opens_exact_receiver_candidate_without_reimport` | The review opener receives the exact native receiver DB and retained candidate. This test controls the review shell. |
| same / `global_menu_singleton_and_hidden_worker_blocks_main_close_restart_update` | Activate the actual MainWindow menu 25 times; one dialog opens. Hide/delete it while work is held; normal close/restart/update remain blocked until the app-owned worker drains. |
| `test_rescue_import_native.py` / `actual_native_rescue_retains_then_cancel_or_explicit_apply_once` | Real codec, SQLite, retention and ReviewDialog in English and Traditional Chinese: preview -> explicit receiver -> retain -> verify -> cancel -> confirm. Verify saved notes, editable geometry/default styles, used image bytes, one operation and an unchanged rescue file. |
| same / `actual_native_refusal_preserves_preview_saved_deck_and_outbox` | Change the displayed rescue file or omit its declared original. Native import fails while keeping preview, saved deck, source file and outbox intact; retry remains available. |
| `test_retained_deck_parent_epoch.py` / `recreation_before_first_review_cannot_reauthorize_an_old_candidate` | Delete/recreate the actual local parent before the first review; refuse the original lifecycle, preserving the deck, candidate and outbox without a decision receipt. |
| same / `same_parent_rename_still_allows_explicit_review_without_replacing_saved_deck` | Rename the existing parent through its operation interface; review remains possible without saving over the current deck. |
| same / `legacy_graph_observation_remains_explicitly_reviewable_without_inventing_old_token` | Remove an old observation's local lifecycle field. Preserve the existing explicit graph-bound confirmation path, reject unconfirmed Apply, and never rewrite the old observation to invent continuity. |
| same / `save_after_parent_recreation_retains_old_result_without_automatic_publication` | Recreate the parent after a deck was opened; saving retains a file candidate instead of publishing. Review refuses its old lifecycle; the saved deck/outbox remain unchanged. |
| `test_retention_error_compat.py` / `incomplete_workspace_refusal_is_compatible_but_remains_visibly_unsaved` | Switch to another enrolled or unbound DB with output lacking captured image ownership. Preserve the stale-save exception contract and actual result, explicitly report incomplete retention, and refuse lossy retry/export without clearing the held result. |

## Evidence and limits

- Frozen NEW2 backend: 36 passed, no skips/deselections, 91.38s on the approved
  lifecycle dependencies. This is not native UI or full application acceptance.
- Native and controlled UI selection: 14 passed, no skips, 18.54s. The four actual
  import journeys use the real local backend; the other ten deliberately control
  timing/failures and cannot independently certify codec/persistence.
- Four parent-lifecycle cases passed. Two existing workspace-contract tests first
  failed on the unchanged integration baseline; after the compatibility repair,
  those exact unchanged tests and two new unsaved-state controls all passed.
- The current combined root selection passed **187 cases, zero skips,635.81s**
  (wrapper637.84s), with no drift in867 recorded inputs. Its terminal evidence is
  `build/rescue-import-joint-root-result.json`; this is not the full application gate. Source admission is pinned in
  `build/rescue-import-integration-source.json`.
- The parent delete/recreate actor is a controlled external SQL repair; it does
  not establish that protocol-level paper deletion/cascade is supported.
- Offscreen native preview/review renders were inspected with an explicitly
  loaded installed Chinese font. They use synthetic content and do not establish
  installed macOS, physical keyboard, real provider or mobile acceptance.
- A separate new actual list-package regression is RED: export/import succeeds
  while omitting the retained rescue proposal, all three images and its historical
  original A, despite including current primary B. It is not in the passing187.
- Full writer/history enrollment, list package/fresh recovery, live history/mobile
  continuity, grounded lineage, production sync identity and physical device
  journeys remain part of v0.5 acceptance. No release or full-check pass is claimed.

The original newly authored fixture admission failures are retained: supported
format version, actual optional binding shape, SQL repair rather than unsupported
protocol deletion, genuinely changed malformed bytes, absent review-table lookup,
expected default text styles and exact existing context wording. These corrections
never removed or weakened an older maintained assertion. Original RED receipts
remain available alongside the later runs.
