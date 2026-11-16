# v0.5.0 current status

Updated 2026-11-16. **Development candidate; v0.5.0 is not release-approved.**
The full target remains the [release scope](roadmap-0.5.0.md), including desktop
and mobile offline research, safe synchronization, recovery and private access.
This page separates current evidence from unfinished implementation and external
acceptance. Historical iterations belong in the
[continuation ledger](testing/continuation-20261112.md#2026-11-16-superseded-status-snapshot-90b13e5).

## Current deliverable

Integration branch: `develop/0.5`. Latest tested downloads are Mac **e26ec8f**
([run43796990188](https://github.com/puddings-world/Paperfact/actions/runs/43796990188),4m27s)
and Windows/Linux **88b2497**
([run43795810511](https://github.com/puddings-world/Paperfact/actions/runs/43795810511),8m40s/3m22s).
Mac adds only a screenshot-helper/test/docs correction; app research code matches.
All three exact clean provenance ZIPs were independently hash-verified. Each OS
passes critical14, first-sync1 and authority/offline-delivery17. Frozen CLI report
acceptance now also verifies read-only list-report audit. Mac screenshots show
readable Chinese, formula and code. Full frozen GUI, physical-device and hosting
gates remain open. [Current downloads](testing/mac-acceptance-0.5.md).

The preceding common-source0a64ec7 candidate is historical; details remain in the
[continuation ledger](testing/continuation-20261112.md). Documentation-only commits
do not create another native build. Current candidates retain v3 local authority
identity/control checkpoints and offline/retained-original cleanup protection.
Legacy authority v1/v2 requires explicit backup/fresh restore; retained local
checkpoints are not independent anchoring or fencing.

Actual frozen CLIs pass import/export, original-file preservation, CLI/MCP retry/
restart, verified-history sync and a source-aware report using one synthetic
loopback completion. The production host `JobHandoff` drives a real QProcess to
the frozen CLI while its disk AI route is disabled: captured models are honored,
disk settings remain unchanged and cached retry makes no second completion.
This is not the full frozen GUI dialog journey. Windows also passes isolated
install/reinstall/uninstall with research preserved; Mac passes three reader
launches and foreground; Linux passes AppImage integration.

The [current mobile web artifact](https://github.com/puddings-world/Paperfact/actions/runs/43795810511/artifacts/14194207419)
was independently downloaded and ZIP-hash-checked. It includes restored Traditional
Chinese report copy and a content-derived shell cache; numeric-cache exports stay
readable. Content ID: `2383b47d34db70bbaed1cdf1a9b608a6c2144ecb459dedc861db1ee223222f1a`.
This is built, not deployed HTTPS/PWA or physical-phone acceptance. No IndexedDB
research/connection migration, public release/tag, daily-app migration, cloud
resource or owner research mutation was performed.

Source after these downloads adds official-authority v4 transactional control
history and explicit legacy v1/v2/v3 backup/fresh recovery. This is source-only;
installed control checkpoints and independent anchoring/fencing remain open.

Current desktop downloads also guard offline verification at queued delivery:
changed originals, research or storage ownership clear prior readiness and require
retry. This does not certify the whole workspace as available offline.

## Requirements and actual boundaries

| Required outcome | Verified implementation boundary | Still open |
|---|---|---|
| Desktop research synchronization | Shared operations, transactional local writes/outbox, retained history and strict transport have source/packaged protocol evidence | Complete supported writer/runtime adoption, remaining legacy/source mappings, installed two-device convergence |
| Offline work and retry | Local research, durable requests, duplicate/restart checks and cached report generation pass for named journeys | Full installed offline trip/reconnect journey and remaining producer/file lifecycles |
| Conflicts and deletion | Supported edit/delete resolution and reviewed recovery preserve history in fixtures | Remaining scientific deletion/recovery mappings and installed conflict UX. Global paper deletion is explicitly rejected by the current shared codec; supported list retirement preserves paper research. |
| Verified attachments | Exact originals, owned manifests, resumable transfers, offline preparation and wrong-source refusal have scoped evidence | Automatic reference-aware eviction/history lifecycle, complete supported attachment coverage and physical interrupted-transfer acceptance; source legacy cleanup now protects offline intent and retained managed-original owners |
| Mobile reading and notes | PWA source includes durable notes/outbox, private sessions, verified reading and offline preparation; content-addressed88b2497 artifact is built and ZIP-verified | Coordinated HTTPS deployment, Safari/iOS/Android durability, quota and foreground/reconnect journeys |
| Sync visibility and settings | Workspace/device status, explicit pairing and device-local reconnect opt-in have desktop fixtures | Installed location/storage/offline and backup/device controls, native vault prompts, restart/account-switch/focus/input and cross-device UX |
| Backups and recovery | Verified authority/client backups, fresh-identity restore and reviewed editable adoption exist for supported content | Complete lossless migration/runtime adoption, cloud backup/restore rehearsal, scheduling/retention and unsupported-source handling |
| Private access | Credential isolation, revocation, verified-history writes, strict official routes and same-host listener exclusion are tested; source adds restart-persisted file identity and a local device/pairing checkpoint | Device-held control checkpoints, independent anchoring/cross-host fencing and hosted authorization/recovery; source after current downloads adds bounded v4 transactional control history |
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
   complete device-held control knowledge and independent anchoring/fencing.
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
