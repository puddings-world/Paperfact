# v0.5 acceptance map

Updated 2026-11-01. **Unreleased; latest full check outstanding.** Start with the
[Traditional Chinese overview](acceptance-overview.html), then the
[local proposal scenario map](local-proposal-scenarios.md) for exact behavior.

## Current integration selection

The300-case local-rescue-joint gate completed299 passed/1 failed/0 skipped in
652.13s pytest (654.16s wrapper), with885 recorded inputs unchanged. The unchanged
legacy exact-candidate review test found an incompatible constructor argument.
After fixing it, only the rescue dialog and new UI controls changed; the exact
two-file delta is recorded in build/local-rescue-fix-scope.json. No old test changed.

The final directly affected selection passed21/21,0 skips,54.66s pytest
(56.67s wrapper),885 unchanged inputs:10 controlled legacy UI cases,7 actual
local-only rescue cases and4 actual enrolled native cases. Receipts are
build/local-rescue-affected-final-result.json and matching XML/log/inputs.
This repairs the known failure; it is not a rerun/pass of the whole300 or the app.
Whole-tree Ruff passed. Avoid repeatedly running the unaffected ten-minute group
for a bounded two-file repair; run the complete check before commit/release.

The first selection exercises complete local proposals, public package import,
explicit metadata replacement, active review rollback/history, native local-only
ZIP rescue, app-owned pending recovery and existing enrolled/ordinary review.
An independent report/UI check and docs profile are recorded separately.

## Actions and assertions

| Situation | Actual action | Required result |
| --- | --- | --- |
| A colleague imports a package | Public export/import, Review/Apply and repeat import into an empty local-only DB. | All supported science/PNGs/original A survive beside primary B; no auto-Apply or duplicate proposal. |
| Existing metadata changes | Preserve by default or explicitly replace metadata, then fail after proposal adoption and retry. | Manual notes/slides remain, metadata and proposal ownership are atomic; no fake refreshed producer capture. |
| Review replaces slides | Cancel then confirm; deny SQL receipt after file install; retry. | Byte-exact prior history, atomic active assets/receipt, one applied decision; own rollback can retry. |
| Local-only rescue | Actual bilingual Qt file preview, explicit paper selection, retain, verify, confirm. | No sync enrollment; complete saved science and editable slides after explicit Apply. |
| Work completes after close | Hold actual worker, close view, release worker; repair storage. | Complete unsaved result reaches app owner before GUI guard and can retry/export without AI. |
| Source/workspace disappears | Remove synthetic original archive/database after the actual failed save; export memory copy. | Full originals/images/evidence survive; export failure keeps pending result and existing user destination. |
| Parent ID is reused | Delete/recreate during staging or after capture. | Old work cannot adopt the new lifetime; complete content remains available for explicit rescue. |
| Evidence uses another image | Preview/retain a fourth evidence-only PNG with a separate PDF. | Preserve exact scientific catalogs, all images and originals; do not invent deck entries. |

The separate enrolled evidence-only fourth-image audit is genuinely RED at an
explicit compatibility refusal. It is not included or skipped in the selected
passing controls; original sender/receiver data remain unchanged. See
[portability design](../portable-proposals-design.md).

## Read numbers honestly

- Cases multiply parameterized functions; 2 workspaces x4 context changes =8 cases,
  not8 features. A 25-click test does not make25 real AI calls.
- Pytest percentage counts completed cases within that invocation, not product
  completion, overall stage progress or estimated time remaining.
- Collection lists identities but executes no test bodies. The structured bilingual
  catalog remains partial:19 functions/27 cases; other tests are undocumented there.
- Fixed provider responses exercise actual disposable SQL/files/Qt. Real provider
  auth/quota, semantic research support and physical devices require separate checks.
- Old overlapping gates use other source snapshots. Do not sum them or infer a
  full pass from a historical result. The latest complete check is outstanding.

Run affected behavior tests during iteration, interacting groups at integration,
and the full scripts/check.py before completion/commit/release. Source, exact
assertions, fixture setup and terminal receipts define what was actually verified.
