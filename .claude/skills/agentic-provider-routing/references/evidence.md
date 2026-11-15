# Paperfact routing evidence

- Status: validated-local; captured 2026-10-20. Not yet validated in another app.
- Problem: a simple account selector needs per-feature overrides without changing
  the global selection or forwarding credentials to another vendor.
- Implementation: `src/paper_daily/ai_profiles.py`, `src/paper_daily/ai_choices.py`,
  `src/paper_daily/llm.py`, `src/paper_daily/desktop/ai_picker.py`.
- Regression evidence in `tests/test_ai_profiles.py`:
  `test_task_routes_do_not_change_default_and_can_follow_it_again`,
  `test_unknown_profile_fails_instead_of_sending_to_a_default`,
  `test_endpoint_switch_does_not_forward_a_stored_key`.
- UI evidence in `tests/test_ai_picker.py`:
  `test_browsing_services_does_not_change_active_account`,
  `test_stale_usage_cannot_appear_under_another_account`.
- Existing full check on 2026-10-20: 656 Python tests and 18 JavaScript tests passed,
  plus Ruff. This is the baseline before the skill-library change, not an
  assurance about future versions or every external provider.
- Limit: provider discovery and OAuth remain integration-specific. Local adapters
  for generation are not a general external tool-agent protocol.
- No account identifiers, keys or original user messages retained in this record.

## Live model catalog follow-up (2026-10-21)

- Status: validated-local. A static Claude family list omitted a model which the
  selected official CLI advertised. A metadata-only initialization of Claude Code
  2.1.304 returned `fable` and `claude-fable-5`; no prompt or inference was sent.
- Implementation: `ai_accounts.models` consumes the initialization catalog using
  the selected account's environment, an empty working directory, disabled hooks
  and tools, strict empty MCP configuration, and no session persistence.
- The simple picker and per-task table load Claude catalogs in workers, preserve
  typed model IDs, and prevent results from crossing account changes. The table
  deduplicates discovery for rows sharing one account. Discovery errors do not
  replace a chosen model or silently use another provider.
- Tests: `tests/test_ai_models.py`, `tests/test_ai_picker.py`,
  `tests/test_ai_tasks.py`; sanitized observed model values are in
  `tests/fixtures/claude_models_2_1_304.json`. Transport fixtures verify that alias
  and full model IDs reach the CLI unchanged.
- Limits: advertised availability is not a successful inference, entitlement,
  billing or cross-account integration test. Model versions are not inferred from
  aliases. No private account metadata is retained in the fixture.

## Human-readable model metadata (2026-10-21)

- Status: validated-local; Ruff, 788 Python and 18 JavaScript tests passed.
- Observed public CLI 2.1.304 metadata maps `fable` to `Fable 5.1` and `opus`
  to `Opus 5.5`. The fixture now retains these public display names; versions are
  read from metadata, not inferred from alias spelling.
- `tests/test_model_catalog.py` covers provider/account/home isolation, missing
  metadata and background toolbar refresh without route changes. Picker behavior
  tests select the friendly label and verify the original routing ID is saved.
- Rendered synthetic model popup verified selected text remains readable. Live
  discovery was metadata-only; it did not verify paid inference or entitlement.

## Task-scoped picker and inherited versions follow-up

- Status: validated-local. Two regressions were reproduced with failing tests:
  a feature login picker read the shared profile model instead of its task override
  and overwrote that shared model on apply; a failed catalog was cached as empty
  and prevented retry on reselecting the account.
- The feature picker now uses atomic task assignment. Model refresh includes the
  global default and inherited rows, including a view constructed while hidden.
- `tests/test_ai_picker.py` pins task isolation and identical-label/different-ID
  selection. `tests/test_ai_tasks.py` covers retry, inherited versions and filters.
- `tests/test_ai_account_management.py` covers identity-preserving nicknames,
  profile deduplication, protected removal, scoped logout and first-login activation
  when the settings file contains only account display metadata.
- Synthetic UI renders checked readable model versions, bounded selectors and the
  filtered task layout. No live logout, credential deletion or paid inference was
  performed. Account authentication/plan entitlement remains provider-dependent.

## Captured budgets and historical model disclosure (2026-10-31)

- Pattern ID / revision: provider-routing-captured-options-v1.
- Status: validated-local in the unreleased Paperfact 0.5 candidate. This extends
  the existing capture/identity rule; it is not a global installation.
- Trigger: an explicit fact-extraction job captured its Audit connection but left
  public scalar budgets mutable. An actual simulated completion received 8,001
  output tokens after the prepared 4,000-token field was reassigned. The recorded
  control failed before the repair. A read-only UI review separately found that
  Claims hid its next route and omitted retained historical model provenance.
- Decision: copy selections into immutable values, freeze public captured options,
  and keep private attempted/result/lock state separate. Pass the captured output
  cap explicitly. Display next-call intent independently of saved requested and
  reported model identity; an absent reported model stays unreported.
- Evidence: audit_fact_extraction.py, desktop/claim_evidence.py;
  test_audit_fact_extraction.py and test_claim_model_disclosure.py. The producer's
  fixed selection passed 252 cases; the canonical combined selection passed 203
  cases, with all 18 integrated afterimage hashes unchanged. Counts overlap and
  must not be added. Privacy/Ruff passed; the matching complete feature gate is
  still required before a commit or release.
- Limits: disposable actual source captures and simulated providers, including
  held cancellation/context changes. No live accounts, paid calls, owner data or
  deployment. The facade request cap does not guarantee a single HTTP transport
  attempt or vendor billing total. Configuration/environment witnesses do not
  certify external CLI reauthentication inside an unchanged credential home.
- Privacy/promotion: synthetic budgets and repository-relative code paths only;
  no prompts, research content, credentials or account identifiers. No new
  provider auth flow, global skill installation or universal scientific claim.

## Source-aware survey generation uses the captured route (2026-11-16)

- Status: validated-local; another use of the existing captured-selection pattern,
  not a new global rule or provider authentication flow.
- Boundary: survey_jobs resolves the survey task route once during capture and
  sends the resulting immutable Settings to complete_result. Changed global
  settings do not retarget the captured request. Credentials remain private;
  requested and reported models are distinct in the checked report.
- Evidence: test_survey_jobs.py, ten behavior cases,15.17s pytest/21.9s governed
  stages. A real sealed native publication and original-page reader use the
  simulated completion's report; later native content refuses old proposals.
  Busy/failed/cancelled calls, unchanged retry, original corruption and invalid
  response contracts are included. These are affected checks, not release proof.
- Limits: original bytes are durably retained, but the checked model response is
  cached only in the live job object. Durable review/recovery, unbound generated
  publication and desktop/CLI/MCP dispatch are still required. No live login,
  entitlement claim, paid inference, original research or global installation.

## Packaged report model provenance (2026-11-16)

- Status: validated-local with CI platform evidence. Clean e5eb093/run43776461463
  runs the actual frozen CLI on Windows, Mac arm64 and Linux through one loopback
  synthetic completion, preserving different requested/returned model IDs.
- Evidence: downloaded/hash-matched provenance on all three platforms confirms
  saved report/originals, quotation location, retained read and cached retry with
  no second completion. Source verifier/helper43 pass44.9s stages.
- Limits: a controlled API profile, not live provider login, desktop private
  handoff, account-switch races or scientific-support validation. No paid call,
  global skill installation or account change is authorized by this evidence.
