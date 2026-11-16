# v0.5.0 current status

Updated 2026-11-16. **Development candidate; v0.5.0 is not release-approved.**
The full target remains the [release scope](roadmap-0.5.0.md), including desktop
and mobile offline research, safe synchronization, recovery and private access.
This page separates current evidence from unfinished implementation and external
acceptance. Historical iterations belong in the
[continuation ledger](testing/continuation-20261112.md#2026-11-16-superseded-status-snapshot-90b13e5).

## Current deliverable

Integration branch: `develop/0.5`. Latest Windows/Mac candidates share clean
**1875db595b7df510a851a2d44ea5157cc994689f**, version `0.5.0.dev`, beta-candidate.
[Mac run43808973671](https://github.com/puddings-world/Paperfact/actions/runs/43808973671)
passes3m54s; [Windows run43808976905](https://github.com/puddings-world/Paperfact/actions/runs/43808976905)
passes7m48s. Both small provenance ZIPs were independently hash-checked and inspected.
Each OS passes critical14, first-sync1 and45 authority/control/recovery/offline source
cases. Actual frozen apps pass15 sync protocol flags and source-report acceptance;
Mac screenshots show readable Chinese, formula and code. Full frozen GUI,
physical-device and hosting gates remain open. [Downloads and isolation steps](testing/mac-acceptance-0.5.md).
Linux remains older88b2497 and is not a compatible official-v4 sync acceptance peer.

Earlier candidates and the failed7a95b31 Mac attempt remain historical in the
[continuation ledger](testing/continuation-20261112.md). Documentation-only commits
do not create another native build. Current Windows/Mac candidates include official
v4 transactional control history, device-retained checkpoints and recovery comparison.
The packaged test client now performs that actual handshake without relaxing guards.
Legacy authority v1/v2/v3 requires explicit backup/fresh restore; retained local
checkpoints are not independent anchoring or fencing.

Actual frozen CLIs pass import/export, original-file preservation, CLI/MCP retry/
restart, verified-history sync and a source-aware report using one synthetic
loopback completion. The production host `JobHandoff` drives a real QProcess to
the frozen CLI while its disk AI route is disabled: captured models are honored,
disk settings remain unchanged and cached retry makes no second completion.
This is not the full frozen GUI dialog journey. Windows also passes isolated
install/reinstall/uninstall with research preserved; Mac passes three reader
launches and foreground; Linux passes AppImage integration.

The [current mobile web artifact](https://github.com/puddings-world/Paperfact/actions/runs/43808976905/artifacts/14199263514)
was independently downloaded, ZIP-hash-matched and verified against all53 assets, proxy map and cache identity in0.453s. It includes small IndexedDB control metadata and source-aware
Traditional Chinese copy with a content-derived shell cache; numeric-cache exports
stay readable. Content ID: `dae60b2ab54a12460d51065b76711d5668647ca26c8eccf601a05c5d55ecd2b3`.
This is built, not deployed HTTPS/PWA or physical-phone acceptance. No IndexedDB
research/connection migration, public release/tag, daily-app migration, cloud
resource or owner research mutation was performed.

Official-v4 control challenge/refusal/restart now also has actual frozen Windows/
Mac evidence. Durable desktop/mobile storage, join/resume and fresh-identity recovery
have scoped fixture/Qt/HTTP evidence, not full frozen-dialog or physical-device proof.
Independent anchoring/fencing, hosted recovery and installed-device acceptance remain open.

Current desktop downloads also guard offline verification at queued delivery:
changed originals, research or storage ownership clear prior readiness and require
retry. This does not certify the whole workspace as available offline.

## Requirements and actual boundaries

| Required outcome | Verified implementation boundary | Still open |
|---|---|---|
| Desktop research synchronization | Shared operations, transactional local writes/outbox, retained history and strict transport have source/packaged protocol evidence | Complete supported writer/runtime adoption, remaining legacy/source mappings, installed two-device convergence |
| Offline work and retry | Local research, durable requests, duplicate/restart checks and cached report generation pass for named journeys | Full installed offline trip/reconnect journey and remaining producer/file lifecycles |
| Conflicts and deletion | Supported edit/delete resolution and reviewed recovery preserve history in fixtures | Remaining scientific deletion/recovery mappings and installed conflict UX. Global paper deletion is explicitly rejected by the current shared codec; supported list retirement preserves paper research. |
| Verified attachments | Exact originals, owned manifests, resumable transfers, offline preparation and wrong-source refusal have scoped evidence | Automatic reference-aware eviction/history lifecycle, complete supported attachment coverage and physical interrupted-transfer acceptance; source legacy cleanup now rechecks offline intent and managed-original owners under a writer reservation at each deletion |
| Mobile reading and notes | PWA source includes durable notes/outbox, private sessions, verified reading and offline preparation; content-addressed1875db5 artifact is built and independently verified | Coordinated HTTPS deployment, Safari/iOS/Android durability, quota and foreground/reconnect journeys |
| Sync visibility and settings | Workspace/device status, explicit pairing and device-local reconnect opt-in have desktop fixtures | Installed location/storage/offline and backup/device controls, native vault prompts, restart/account-switch/focus/input and cross-device UX |
| Backups and recovery | Verified authority/client backups, fresh-identity restore and reviewed editable adoption exist for supported content | Complete lossless migration/runtime adoption, cloud backup/restore rehearsal, scheduling/retention and unsupported-source handling |
| Private access | Credential isolation, revocation, verified-history writes, strict official routes and same-host listener exclusion are tested; source adds restart-persisted file identity and a local device/pairing checkpoint | Installed control-checkpoint acceptance, independent anchoring/cross-host fencing and hosted authorization/recovery; current source retains device-local prefixes across desktop join/restart and browser reconnect |
| UI/CLI/MCP/AI integrations | Existing shared operations and 38 MCP tools pass named package journeys; frozen source-aware report CLI gate now passes on all desktop OSes | Full frozen desktop private report/dialog journey and live provider/account acceptance; source now verifies production QProcess handoff to an actual CLI with disabled child disk settings |
| Grounded research features | Reading goals, exact-source claims/Lineage and bounded audit/recovery/report paths have source evidence; report provenance also has frozen CLI evidence | Complete audit/retained-result adoption and mappings; source after0a64ec7 adds list-report original/location checks in desktop/CLI/MCP. Scientific support needs researcher review beyond quotation location |

A named pass is not certification of every button, writer, document corpus or
platform. Quote location does not prove scientific support. Preserved unsupported
content must remain a visible blocker rather than being dropped to enable sync.
Typed queue pins are implemented; their historical unsupported label is obsolete.
See [queue pin migration](queue-pin-migration.md) and
[recovery UI](recovery-adoption-ui.md) for the supported boundary.

## Work still required before v0.5.0

1. **Authority safety:** source v4 now retains transactional control history;
   device-held knowledge now has desktop/mobile fixture coverage. Complete
   independent anchoring/fencing and installed acceptance. Recovery comparison
   now reports device-held control knowledge, and actual HTTP fresh-identity
   restore/join preserves old knowledge and unsent work in fixtures.
   Local listener exclusion and received history
   proofs do not establish protection against every rollback or cloned host.
2. **Lossless adoption and coverage:** finish remaining supported writer, legacy
   source, detached recovery and retained-result mappings. Keep explicit blockers,
   old research and unsent work intact. Use the existing
   [enrollment contract](workspace-enrollment.md),
   [recovery contract](recovery-adoption-ui.md) and
   [analysis contract](analysis-audit.md), not historical snapshot descriptions.
3. **Desktop completion:** verify the private AI handoff and retained-report
   review/finish flows in frozen/installed apps; source/widget tests alone do not
   close them. Finish the remaining recovery/attachment lifecycle UX and coverage.
4. **Deployment:** review the existing [GCP pilot plan](gcp-sync-pilot-plan.md),
   exact project/region/hostname/budget, operator and recovery boundary. Provisioning,
   HTTPS, coordinated mobile delivery, backup/restore rehearsal and owner enrollment
   have not been performed. An offline template renderer now prepares consistent
   operator review files; it neither verifies artifacts nor authorizes resources.
   This page does not authorize creating cloud resources.
5. **Installed-device acceptance:** run the maintained Windows/Mac and physical
   phone journeys, including offline edits, conflict, interrupted attachment,
   revocation and restore. Installed old-release upgrades, native vaults/IME and
   long-running behavior remain separate from source-format preservation.

No public v0.5 tag/release, production deployment, daily-app migration or owner
research mutation has been performed. These open items prevent completion of the
original milestone; delivering installers does not narrow that milestone.

## Development and evidence

- Keep the current integration branch and existing
  [coordination board](parallel-work-0.5.0.md); no additional worktree or board is
  needed to read this status. [Collaboration rules](collaboration.md) still apply.
- Focused changes use affected behavior checks, targeting 3-5 minutes. Candidate
  validation and packaging share a 20-30 minute budget. Use the existing bounded
  runner; do not run historical full tests after each edit.
- [The test map](testing/README.md) explains protected behavior. Case counts and
  pytest percentages are not feature coverage or overall project completion.
- [Release readiness](release-readiness-0.5.md) owns the acceptance gates;
  [the continuation ledger](testing/continuation-20261112.md) keeps dated results,
  corrections and prior snapshots. Update the current rows here when evidence
  changes rather than appending another chronological status section.
