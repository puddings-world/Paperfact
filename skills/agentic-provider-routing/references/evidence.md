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
