# v0.5.0 implementation status

Updated 2026-11-01. **0.5.0.dev; unreleased.** Current production work remains in
an isolated integration tree based on checkpoint3843894 with maintenance
reconciliation. It has not replaced the daily release or owner's research data.
No commit, push, deployment or release is claimed for this integration.

Start with the [readable acceptance overview](testing/acceptance-overview.html).
Each example explains actions, required saved/visible outcomes and limits.

## User outcomes

| Outcome | Implemented local evidence | Still required |
| --- | --- | --- |
| Continue across desktops | Shared operations/outbox, retries, conflicts and device controls have local coverage. | Complete writer/history enrollment and propagation, production identity/hosting, installed desktop round trip. |
| Read offline or on a phone | Verified originals, reading position and mobile PWA reading/text notes have local coverage. | Installed Apple Silicon Mac and actual iPhone/Android offline/reconnect acceptance. |
| Move research packages | Closed portable proposal codec, exact originals, full scientific metadata and union PNGs. Public local-only package import/reimport, metadata preserve/replace, rollback, Review/Apply are integrated. | Enrolled evidence-only union adapter, complete initial enrollment, history, backup/recovery and source/material continuity. |
| Recover a completed unsaved result | App-owned pending results, retry/export/discard and exit/update barriers. Complete ZIP rescue now has actual local-only preview/retention/review and app-owned failure/close handling. Existing enrolled JSON rescue remains. | Complete enrolled ZIP path and all original/owner-refusal carriers; no forced-process-death guarantee for memory-only results. |
| Preserve editable presentations | Explicit confirmation, saved-base/parent checks, all captured science, atomic active files/history/receipt, exact retry after own rollback, duplicate activation controls. | Complete synchronized history, recovered receiver adoption, active source/evidence resolver. |
| Ground research explanations | Per-list goals, source-bound claims and bounded audit/appraisal/consistency slices have local coverage. | Complete grounded lineage producer/review/UI and durable complete-output audit/consistency provenance. |
| Install a public beta | Existing maintenance packaging/update/support foundations remain. | Current full check, matching installers, physical-device journey and operator decisions. |

## Matching integration gate

The first joint selection completed300 cases:299 passed,1 failed,0 skipped
(652.13s pytest /654.16s wrapper,885 unchanged recorded inputs). The maintained
legacy exact-candidate review test exposed an incompatible constructor argument.
It was repaired without modifying the old test. Only the rescue dialog and new
UI test file then changed; all other recorded source/test/script inputs match.

The directly affected final selection passed21 cases,0 failures/errors/skips,
54.66s pytest /56.67s wrapper,885 unchanged recorded inputs. It includes10 controlled
legacy UI cases,7 actual local rescue cases and4 actual enrolled native cases.
The300 selection was deliberately not rerun for the bounded UI repair; this is
not a complete current-source integration/full-app pass. Whole-tree Ruff passed.
Receipts: build/local-rescue-joint-result.json, local-rescue-fix-scope.json,
and local-rescue-affected-final-result.json with matching XML/log/input manifests.
Earlier187/55/64 and individual gates are historical and must not be summed.
See the [acceptance map](testing/acceptance-map.md) and
[local proposal scenarios](testing/local-proposal-scenarios.md).

The prior omission regression (list export/import dropped the retained rescue
draft, its three PNGs and historical original A) is now GREEN in actual public
package journeys. A distinct independent regression remains RED: a valid local
proposal with an evidence-only fourth PNG exports completely, but enrolled import
safely refuses unsupported raw-v1 content before receiver writes. Do not remove
its guard, mutate science or count unreachable Review/re-export assertions as run.

## Full-check boundary

There is **no complete passing check for the latest tree**. Historical Full7 at
checkpoint3843894 passed6469 Python/desktop,24 frontend and476 mobile, zero skipped;
it does not certify current source. Iteration uses affected tests and integration
checks interacting features. The complete scripts/check.py remains mandatory
before completion, commit or push. No old assertions were skipped or weakened.

## Next implementation

1. Complete the general enrolled proposal adapter while preserving actual native,
   journal/research/CAS binding, parent lifetime, exact target-owned originals and
   caller-owned package transaction. Keep raw-v1 and null-binding guards strict.
2. Connect the same complete proposal content to explicit enrollment, independent
   backups/detached restore/fresh editable adoption, live history/mobile and active
   source/material navigation. Preserving archive bytes alone is insufficient.
3. Finish grounded lineage and persistent complete-output research checks.
4. Resolve remaining maintenance integration/performance and Q&A retry identity
   issues from evidence; preserve user/Claude changes and existing research.
5. Pass the matching full gate, then create and accept matching installers.

## External gates

Record Windows -> offline Apple Silicon Mac -> phone -> desktop convergence,
interruption/conflicts/revocation and independent recovery. Decide production
identity/pairing/recovery, hosting/operator, storage/cost/retention, encryption/key
recovery and offline policies. AI-provider login is not sync identity. Real
provider auth/quota and expert research-quality checks are separate live checks.
No subscriptions, credentials or telemetry consent travel with research.

The [roadmap](roadmap-0.5.0.md) remains authoritative. No required scope was
removed; earlier observations and unsuccessful probes are preserved in docs/archive.
