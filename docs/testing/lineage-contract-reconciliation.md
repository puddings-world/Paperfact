# Lineage stage-contract reconciliation

Date: 2026-11-14. This reconciles historical staged tests with the already agreed
v0.5 feature scope. No production feature, authorization policy, test-runner option,
skip marker or safety bypass was changed. It is not a full-suite pass.

## Why the old expectations needed precision

The owner requested independent account/model selection for AI features and full
research/package synchronization. The maintained [task contract](../ai-setup.md#research-lineage-task-v05-development)
already includes Lineage, and the [native package contract](../enrolled-package-import.md#source-complete-lineage-import-v05-development)
already accepts original-complete scientific reports. No additional activation
was performed by the test edits. The earlier optional approval question was based
on an overly broad reading of stage-only assertions; no timeout or missing reply
was treated as consent. Existing accepted behavior is the basis for these repairs.

| Earlier failure | Repair | Safety coverage retained or added |
|---|---|---|
| Helper-import test required Lineage absent from all AI task settings | Assert its already-enabled task contract, separately from generic wire/storage absence | Existing producer/default-schema/raw-wire rejection checks remain; a fresh process captures every registry before/after helper import and forbids even swallowed model/process/network attempts |
| Public native import test expected all Lineage unsupported; its fixture actually contains an invalid membership timestamp | Keep that same invalid input and assert its precise timestamp rejection | Exact original research/outbox equality remains; new valid-timestamp complete-package import verifies unchanged science/model/time, all three actual PDFs and retry identity; missing/corrupt originals with valid metadata fail atomically |
| Rollback test assumed metadata tables absent although native setup created them first | Establish an explicit empty/absent metadata fixture before the attempted creation | Every original post-failure assertion remains; the separate initialized-baseline test asserts complete SQL equality and preservation of preexisting tables |

`--no-pdfs` disables extra network downloads, not extraction of files already
packed in a research archive. The public positive case preserves this documented
contract rather than adding a native-only exception to satisfy an obsolete
refusal. Scientific originals remain separately version-pinned from current
primary-PDF selection.

## Evidence and exact cases

- Before repair, the exact three old nodes failed in **10.77s**:
  `build/staged-contract-audit-20261114.log`.
- Empty-schema rollback setup plus existing initialized-baseline and new import
  boundary: **14 passed in 53.18s**.
- Complete repaired address/bundle/protected-writer modules plus initialized
  baseline, fresh import boundary and new public import cases: **58 passed in
  148.98s**, `build/lineage-contract-reconciliation-20261114.log`.
- Final import-attempt observation plus existing account/model route cases:
  **4 passed in 4.03s**, `build/lineage-route-boundary-final-20261114.log`.
  This stronger boundary records attempted calls as well as raising, so a helper
  cannot swallow an exception and appear side-effect free. The scopes overlap.

Files:
[protected writer](../../tests/test_lineage_projection_writer.py),
[initialized baseline](../../tests/test_lineage_matching_adoption_rollback_baseline.py),
[typed address](../../tests/test_lineage_address_stage.py),
[original bundle journey](../../tests/test_lineage_bundle_journey.py),
[fresh import boundary](../../tests/test_lineage_import_registration_boundary.py),
[public native import](../../tests/test_lineage_public_import_contract.py).

Tests use isolated native workspaces and actual synthetic PDFs. No owner data,
provider login, paid model, real cloud API, deployment or release was exercised.
A standard complete check remains required before committing/publishing; the
previous failed full report remains historical evidence until a new terminal
full result exists. Installed Mac/phone and hosted acceptance are independent.
