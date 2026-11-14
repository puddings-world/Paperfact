# Direct saved Lineage adoption scenarios

All cases use synthetic research, actual PDFs and isolated native workspaces.
The model is patched to fail if called. No real login, AI, cloud or research DB.

Source cases: [backend/native recovery](../../tests/test_lineage_direct_adoption.py) and [actual reader actions](../../tests/test_lineage_adoption_action.py).

| Cases | Observable proof |
|---|---|
| Selected originals, no ZIP | Inspection/preparation leave SQL unchanged; monkeypatched ZIP access fails if used; final science/model/timestamp preserved |
| Explicit confirmation and retry | Only final apply adds native history/outbox/receipt; repeated apply has one scientific operation |
| Missing/extra/wrong PDF, early cancellation | No source/science/outbox mutation; private saved row remains |
| Aggregate PDF page bound and cancellation during verification | Refusal rather than partial/truncated proof |
| Changed saved report or forged/foreign-service plan | No native write or redirect into another target |
| Late scientific failure, reused sources | Original saved row, source authority/history/outbox/receipt roll back |
| Late scientific failure, all new source versions | Exact same SQL rollback even after new original grants; explicit retry succeeds |
| Consistent PDF hash with a falsely located quotation | Page/quote verification independently rejects the saved claim; no adoption |
| Real native sync and fresh recovery | Adopted new originals upload to a real local authority, survive backup/restore and rejoin; new peer reads unchanged report/model and three exact original PDFs |
| Actual Qt picker and separate confirmation | Cancelled picker starts nothing; verified preview is still non-mutating; duplicate clicks do not create workers |
| Bad selection and choose again | Failure is retryable; prepared choice can be discarded without changes |
| Held verification/apply with cancel, close or paper switch | Worker drains; cancelled action adds no native authority |
| Completed worker, changed row before GUI delivery | Stale confirmation is refused and refresh requested |

The fresh-source fixture initially changed PDF hashes without updating derived
source identities and was correctly rejected by the existing validator. The final
fixture recomputes source, statement, passage and report IDs and validates the full
saved row before exercising the production adoption boundary. No production
validation was weakened to accommodate it.

The initial backend scope passed 8 cases in 44.16s. Expanded scope had 9 pass/1
invalid-fixture failure in 58.03s. Corrected backend/recovery scope passed 11 in
79.92s. Initial actual UI scope passed 5 in 36.62s. These scopes overlap and are
superseded for current affected inputs by the final integrated receipt below.

Not proven by these fixtures: installed migration, all arbitrary legacy/corrupt
schemas, semantic source support, current-primary/offline completeness, hosted
availability or a full release gate. Native history repair/restoration remains
separate; direct adoption cannot bypass existing ownership or replace different
science. Complete per-change disaster-recovery reconciliation remains open.

## Final affected evidence

The integrated gate passed **103 in 609.06s**:
`build/lineage-direct-adoption-integrated-20261114.log`. This covered the initial
20 new cases and 83 adjacent native/compiler/reader/import/lifecycle/history cases.
During its silent output interval the specific handle was confirmed live and its
real child had CPU activity; it was never restarted on an observation timeout.
Case percentages describe its 103 cases, not elapsed time or release readiness.

Visual review then changed only action hierarchy: confirmed source inclusion uses
the existing primary style, while new AI generation is secondary during review.
The eight UI cases passed in 67.20s; immediate Choose-again restyling and the two
affected UI paths passed in 19.74s. Final service binding additionally uses a random
per-instance scope instead of a recyclable object address. A new negative case
models address aliases at the signature seam: another service rejects the plan,
while its owning service can still apply it. It does not fake PDF/row/native checks.
Final changed-core plus UI delivery gate: **15 passed in 138.95s**, including all
13 current backend cases and two actual reader flows. The current new-case inventory
is 21 (13 backend, eight UI); these receipts overlap and must not be summed.

Final docs gate: **52 passed in 1.72s**. Privacy, all-repository Ruff and scoped
whitespace passed. The actual Qt verification state was captured and viewed;
final capture gate passed one in 9.93s. Its explicit installed font was registered
before widget creation, correcting test-process late-font missing-glyph/overdraw
artifacts; it is not installed-app font or Mac acceptance.
`build/lineage-direct-adoption-integration-20261114.json` preserves the integrated
input hashes, three subsequent affected-file changes and seven final source/test
hashes with their exact layered receipts. No whole-worktree full pass is implied.
