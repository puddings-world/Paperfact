# Paperfact event evidence

- Status: validated-local for local recording and reviewed export; cloud receiver
  remains design-only. Captured 2026-10-20.
- Implementation: `src/paper_daily/feedback.py`,
  `src/paper_daily/desktop/feedback_dialog.py`, `src/paper_daily/desktop/ask.py`.
- `tests/test_feedback.py`:
  `test_opt_in_is_required_and_repeated_choice_preserves_identity`,
  `test_unknown_names_are_redacted_and_raw_text_properties_rejected`,
  `test_background_worker_keeps_parent_flow_and_failed_result`,
  `test_feedback_dialog_cancel_export_failure_retry_and_withdrawal`,
  `test_retention_caps_size_and_observation_failure_does_not_break_ai`.
- Baseline full check on 2026-10-20: Ruff, 656 Python and 18 JavaScript tests passed.
- Manual UI check: consent unchecked, no events, export disabled; browsing settings
  did not enable collection. No cloud upload was performed.
- `docs/collection-architecture.md` proposes Cloud Run -> GCS -> local DuckDB.
  It is not a deployed service or a completed deletion/consent implementation.
- Boundary: current thread context propagation does not unify independent processes.
  Event coverage is not exhaustive for every app action.
- This record contains no research content or participant identifiers.

## Consent lifecycle follow-up (2026-10-21)

- Status: validated-local; independent cross-product reuse remains unverified.
- `tests/test_feedback_consent.py` covers first-use explicit acceptance, decline,
  reminder suppression without consent, 30-day deferral, policy renewal,
  repeated callbacks, failed persistence and withdrawal during the export chooser.
- `tests/test_colleague_journey.py` confirms an independent recipient imports
  research without sender credentials or product consent and can continue with
  their separately selected fixture AI account.
- Local recorder, UI and simulated-provider paths were tested. No automatic
  uploader, cloud deletion service or legal-compliance certification is implied.

## Local aggregation and separate acknowledgement (2026-10-21)

- Status: validated-local; Ruff, 788 Python tests and 18 JavaScript tests passed.
- `feedback_report.py` produces schema v2 totals from the private local ledger;
  shared exports contain no participant/session/event/node IDs or event timelines.
- `tests/test_feedback_report.py` covers closed categories, malformed extra fields,
  duration boundaries, unknown outcomes, observed workflow edges and exact reviewed
  export. Existing local-ledger/context/retention assertions remain in place.
- `tests/test_onboarding.py` checks separate usage/analytics choices, unchecked
  defaults, atomic persistence, retry, cancellation and independent withdrawal.
- Rendered synthetic UI verified readable summary and unchecked first-use controls.
- Limits: individual shared totals may be linkable to their sender; overlapping
  snapshots cannot be summed, no unique-user/cohort analysis is supported, and no
  receiver/upload or legal anonymity guarantee was implemented.
