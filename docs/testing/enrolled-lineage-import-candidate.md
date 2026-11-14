# Enrolled Lineage package import candidate

Status: locally tested isolated candidate, 2026-11-14. Its production code and
16 new behavior cases are now integrated into the unreleased canonical checkout;
the old blanket-refusal test transition remains pending agreement. **Not released
or fully validated.** Earlier isolated receipts below retain their original scope.
Source/test copy: `build/lineage-import-next-20261114/`. Its manifest records four
base/candidate hashes; its patch is for review. Recheck hashes before integration
and preserve canonical per-line EOL and concurrent edits. No owner research,
account, paid model call, cloud resource or release was changed.

## Observable behavior

A source-complete list research package can import its Lineage report and exact
original PDFs into an already enrolled workspace through the existing package
entry point. It prepares ordinary paper/source operations and a typed scientific
operation, then commits the source proofs, report, journal and action receipt in
one owned transaction. Scientific metadata alone does not grant file bytes.
Only receiver paper bindings change; scientific statements and source hashes stay
intact. A different existing native report requires explicit reviewed adoption,
even when generic replace is selected. That adoption UI is not implemented here.

## Scenario map

`tests/test_lineage_enrolled_import.py` collects **16 cases**:

| Cases | User/caller outcome guarded |
|---|---|
| Complete import and exact retry | Report and all three originals preserved; one scientific action; no model call |
| Cancel before apply | Research and outbox unchanged |
| Late scientific writer failure | Schema, sources, report and receipt roll back; reprepare can retry |
| Workspace change | Neither the old nor new database receives the stale result |
| Missing/corrupt PDF (two cases) | Refused before research writes |
| Cancel after report write | Final publication rolls back |
| Public bundle entry | Actual enrolled path creates native science, not unbound byte grants |
| Report arrives after preview | Prepared absence cannot overwrite newly saved research |
| Real peer receive and download | Report reaches peer without bytes; explicit downloads open all three exact PDFs |
| Concurrent repeated activation | One import owns the job and one scientific operation is published |
| Different report with replace off/on (two cases) | Reviewed-adoption requirement cannot be bypassed |
| Reused report changes after preview | Saved SQL target must still match the observed report |
| Re-export, backup and detached restore | Third researcher opens all originals; old active identity is not restored |
| Collapsed source mapping | Two source owners cannot alias one receiver; no mutation |

The existing bundle journey test for an invalid-date fixture now expects its
specific timezone-validation error instead of a blanket unsupported-Lineage
error. Its nonmutation assertions remain. This behavior transition is isolated;
the canonical assertion has not been edited. Valid public import is tested
separately. No test was skipped or marked expected-failure.

## Evidence and limits

- Affected package/import/bundle scope: **63 passed in 348.60 s**,
  `build/lineage-enrolled-import-focused-20261114.log`.
- Final strengthened preservation, mapping and malformed-date scope:
  **3 passed in 19.93 s**,
  `build/lineage-enrolled-import-final-preservation-20261114.log`.
- Collection: **16 new cases**, `build/lineage-enrolled-import-cases-20261114.log`.
- Ruff passed on the four candidate files. Tests use the canonical interpreter
  with explicit candidate source paths and assert module provenance. Selections
  overlap and must not be summed into a total.

The first peer experiment correctly rejected a fixture client without its native
projector. The corrected test uses the actual importer client; the production
guard remains. Fixture-only dates and workspace directories were corrected after
separate failing experiments. Logs preserve these failures.

No whole-candidate full gate, maximum-size performance benchmark, friendly mapping
UI, reviewed replacement/adoption, installed Mac journey or hosted GCP acceptance
is claimed. Metadata compilation currently revalidates the selected packet per
scientific operation; large-packet scaling is not measured. Coherent integration
must include source-proof, cancellation, receive, backup and mobile checks before
a new full gate. The independent canonical full run stopped at an old address-
stage invariant after 3,349 passes; it does not validate this isolated candidate.


## Canonical integration checkpoint (2026-11-14)

The production adapter and all sixteen new cases were integrated after verifying
the four-file review manifest; the old bundle blanket-refusal expectation remains
unchanged pending agreement. The actual canonical import/package scope passed
**50 cases in 241.08 s**, lineage-import-integrated-20261114.log. This includes
all sixteen new behaviors and the existing package importer cases. Ruff and the
committable-file privacy scan passed. These are affected checks, not the complete
release gate. The canonical source and owner research are separate from the
original isolated candidate; no real model/cloud/device acceptance is claimed.
