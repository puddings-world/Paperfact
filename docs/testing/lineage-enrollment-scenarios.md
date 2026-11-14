# Fresh Lineage enrollment and recovery scenarios

Development integration, 2026-11-13. These tests use synthetic PDF bytes and
isolated workspaces, never the owner's research, account login or paid model.
They exercise the public prepare/backup/restore boundaries rather than claiming
that a helper alone establishes a working synchronized workspace.

| Test module | Observable behavior |
|---|---|
| `test_lineage_enrollment.py` | Exact current reports, verified original files and new scientific/source operations survive enrollment; removed reports remain archive-only; identical baseline retry does not duplicate; late failure and cancellation preserve source and remove partial output; two corpora share verified source pins. |
| `test_lineage_recovery_enrollment.py` | Generated/imported/native pending and accepted reports produce editable independent copies and inspectable backups; normal caller and worker entry points work; displaced native versions remain readable without old grants. |
| `test_lineage_recovery_enrollment_guards.py` | Retired/recreated original or paper lifetimes refuse adoption; a request seed cannot recreate current or ancestor workspace/device identity; a genuinely new seed still succeeds. |
| `test_lineage_enrollment_peer.py` | Actual enrollment, desktop attachment publication, public join and selected offline download retain the same report and all three exact PDFs; originals are unavailable before transfer and verifiable afterward; ordinary reader works and repeated sync creates no duplicate analysis. |
| `test_lineage_enrollment_archive_integrity.py` | Missing archived publication or its exact candidate refuses a new backup; current report and source database stay unchanged. |
| `test_lineage_recovery_sources.py` | Exact verified staged originals, retry, caller-owned rollback, cancellation and changed-source rejection remain enforced. |
| `test_lineage_recovery.py` | Forensic inspection, detached restore, history closure and real fresh editable preparation preserve source data. |

## Recorded evidence

Latest maintained affected gate: **52 passed in 417.87 s**, 421.7 s overall,
privacy/Ruff passing, no failures/errors/skips. It covers the enrollment, editable
recovery, stale-source, source staging and generated/imported/native version
modules. The separate two archive-integrity cases below were added after that
gate began and are not included in its count. No product changes followed it.

- Initial integrated enrollment/recovery/source scope: **38 passed, 276.37 s**.
  This predates the fresh-identity and nested version-catalog additions.
- New stale-source guards: **3 passed** in the first guard run. Its fourth
  case exceeded the imported helper's fixed ten-second timeout while preparing
  a second complete backup; no preservation/identity assertion failed.
- The second-generation case through the real supported public entry point:
  **1 passed, 28.76 s**; all identity and preservation assertions retained.
- Displaced native version recovered through a real editable copy:
  **1 passed, 19.62 s**.

- Archived generation evidence removal: **2 passed, 21.96 s**.

- Actual enrollment-to-peer journey and adjacent attachment/archive checks:
  **5 passed in 49.12 s**, 52.3 s overall, privacy/Ruff passing.
- Unchanged previous schema-contract checks: **1 passed, 1 failed in 11.34 s**.
  Native schema upgrade rollback passed; candidate-only enrollment still failed
  at that checkpoint. The later schema/enrollment/receive/workflow gate passes
  **21 cases in 145.67 s**, including that unchanged absence assertion. See the
  [schema lifecycle map](lineage-schema-scenarios.md). No whole-suite pass is claimed.

The receipts overlap, are partial, and are not a release total. See the
[continuation ledger](continuation-20261112.md) for the latest affected gate.

The later schema/cancellation/enrollment/peer-download/editable-recovery gate
passed **38 cases in 349.57 s**, 354.1 s overall, privacy/Ruff passing. This
revalidates the recovery paths after metadata-only generic schema setup; it
includes six new schema lifecycle cases. It overlaps the earlier receipts.

## Remaining gates

- Validate the accumulated artifact with the coherent full application gate;
  the previous optional-schema absence regression now passes locally without
  removing or weakening its assertion.
- Exercise the now locally verified public join/offline-download journey on
  the hosted endpoint and actual installed devices.
- Extend negative archive closure coverage to imported quote-integrity cases.
- Complete arbitrary enrolled live package import and reviewed old-result adoption.
- Perform hosted recovery and installed Windows/Apple Silicon/device acceptance.

No cloud service, installer, release or original research migration is implied.
