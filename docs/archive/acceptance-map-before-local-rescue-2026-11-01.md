# v0.5 acceptance map

Updated 2026-11-01. **Unreleased; latest full check still outstanding.**
Use the [Traditional Chinese overview](acceptance-overview.html) for feature status
and expandable examples. [Current implementation status](../status-0.5.0.md)
separates implemented behavior, integration gaps and physical-device gates.

## What the current tests actually do

| Situation | Test action | Required result |
| --- | --- | --- |
| Completed AI result cannot save | Fail image staging, fallback receipt and metadata writes with fixed valid output. | Actual result survives in the app; saved research is unchanged; UI says unsaved. |
| Retry or export | Restore storage or choose a new rescue file; also cancel/fail/repeat the action. | No new model call; all captured bytes and supported scientific metadata survive; failure keeps the result. |
| Leave, restart or update | Use an actual MainWindow and normal preparation controls. | Pending research prevents normal exit/update until explicit disposition. |
| Another view/workspace becomes current | Destroy the pane or change native DB/path before delivery. | No wrong-view application; another pane can find the original pending result. |
| Two DBs share one folder | Use equal request names with different scientific data; damage the foreign receipt. | Each backup retains only its own exact content and keeps its own limits. |
| Source/file faults | Back up before repair, restore separately, then retry with original captured bytes. | Every used/unused image and explanation survives; no active deck or duplicate operation is created. |

The matching current gate passed **187 cases, zero skipped,635.81s**, with no drift
in its867 recorded source inputs. Whole-tree Ruff passed. These16 selected files
are not the whole application. Exact paths/assertions and earlier reproduced
failures are in [the preservation scenario map](pending-generation-scenarios.md).

Other important existing tests cover concurrent offline note edits, three-original
source transfer, historical PDF A versus current B, rollback after a second write,
and fresh editable recovery. Their earlier totals use other snapshots and must
not be added to187 or treated as installed multi-device acceptance.

## Rescue import and lifecycle scenarios

The [reviewed rescue map](rescue-import-scenarios.md) links all 36 new test
functions / 56 cases to explicit actions and assertions. It distinguishes actual
native/backend journeys from controlled timing shells and their different limits.

- Preview all slides, notes and images before selecting an explicit receiver.
- Retain without replacing; verify, cancel, then explicitly Apply once.
- Refuse changed files, missing/foreign originals, cancelled work and reused IDs.
- Do not reauthorize an old candidate after the parent was deleted/recreated.
- Preserve the stale-save caller contract while reporting metadata-only retention
  as incomplete and retaining the actual result.

A separate new portability regression is RED: public list export/import succeeds
without carrying the retained rescue draft, its three images or its historical
original. Current NEW2 retention also requires an enrolled receiver. Neither gap
is covered up by the passing selected gate or a claim of local-only acceptance.

## How to interpret the numbers

- One function can expand into many cases: two workspaces times four context
  changes gives eight executions, not eight features.
- Terminal percentages count completed cases in that invocation. They are not
  product completion or estimated time remaining.
- Collection lists test IDs but runs zero test bodies.
- The separate [reviewed bilingual catalog](README.md) explains only its stated
  subset. This map does not pretend every remaining test has reviewed prose.
- New preservation tests use synthetic provider responses and disposable SQL/files;
  selected native Qt controls are real. This does not validate scientific quality,
  billing, actual vendor login or physical Mac/phone operation.

## Test timing and development policy

Run affected behavior tests during iteration, interacting groups at integration,
and the full check before completion/commit/release. The187-case gate's actual
runtime is635.81s; it includes file/SQL/Qt setup and recovery. Do not turn that into
an estimate for an AI job. Keep per-case timings and exact source receipts.

Complete local-only rescue receivers, portable proposals and remaining data/research flows, then the current
full gate and the actual installed desktop/offline/mobile journey. External
service identity/hosting/operator decisions remain recorded release gates.
