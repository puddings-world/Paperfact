# v0.5.0 current status

Updated 2026-11-16. **Development candidate; v0.5.0 is not release-approved.**
The full target remains the [release scope](roadmap-0.5.0.md), including desktop
and mobile offline research, safe synchronization, recovery and private access.
This page separates current evidence from unfinished implementation and external
acceptance. Historical iterations belong in the
[continuation ledger](testing/continuation-20261112.md#2026-11-16-superseded-status-snapshot-90b13e5).

PDF writer adoption: `repdf` now observes the enrolled workspace's
original before download/staging and uses shared versioned attachment publication.
Prior originals/anchors remain retained; stale/failed publication is refused.
First-original list prefetch now uses the same native boundary, including atomic
successful-URL publication. Existing legacy files are not migrated automatically;
managed missing originals still use workspace attachment transfer. These source
changes are included in2021103 native candidates. Newer source also routes enrolled
reader/analysis first-original intake through the shared downloader and delivers
the exact reader projection for text extraction. List/PDF intake also preserves
existing originals across memberships, refuses ambiguous or retired ownership and
passes first-original intent to the final publication boundary. These newer
changes are not yet in2021103 installers. Current source additionally repairs
missing active originals from exact local bytes, retaining their version and
citations; supplying PDFs no longer automatically starts AI. Explicit transfer
retry can restore absent finalized bytes, while corrupt finals remain protected.
Remaining writer/runtime enrollment still requires work. [Contract and acceptance limits](sync-operations.md#observed-native-pdf-replacement).

## Current deliverable

Integration branch: `develop/0.5`. Windows, Apple Silicon Mac and Linux now share
clean **20211036cea31cc7d0764c28946926870617a7f4**, version `0.5.0.dev`, beta-candidate.
[Run43820427097](https://github.com/puddings-world/Paperfact/actions/runs/43820427097)
succeeded: Mac5m52s, Windows9m09s, Linux3m32s; draft/release job skipped.
[Downloads and separate-app/workspace steps](testing/mac-acceptance-0.5.md).
All small provenance ZIPs were independently hash-matched and inspected against
source/host; actual native reports have `passed=true` and all15 protocol flags.
Large installer ZIPs were not independently downloaded here.

Each OS passes critical14, first-sync1 and48 authority/control/recovery/offline/
original source cases. New first-original success and atomic URL rollback join
the existing three-minute gate, without a new job or historical full suite.
Mac source cases pass with five reported warnings; the native report passes.
Frozen CLIs exercise exact originals, source-aware reports, private captured model
handoff, durable/cached retry, verified history and official-v4 challenge/refusal/
restart. Mac passes three reader launches and native foreground activation;
its actual screenshot has readable Chinese/formula/code. Windows isolated actual
install/reinstall/uninstall preserves research. Linux AppImage integration now
uses the same official-v4 source; older88b2497 is superseded for acceptance.
Source-format0.4.3 preservation is tested, not an older installed-binary upgrade.
Full frozen GUI, live account/IME/vault, hosted and physical-device gates remain.

These candidates include native repdf and first-original prefetch adoption,
retention-safe cleanup and mobile storage protection. Source tests cover the new
writer actions; packaged protocol/report acceptance does not prove every new GUI
workflow. Prior exact candidates remain in the continuation ledger and Mac guide.
No daily data migration, public tag/release, cloud resource or owner account change.

The [matching mobile artifact](https://github.com/puddings-world/Paperfact/actions/runs/43820427097/artifacts/14204845490)
was independently downloaded, SHA-256-matched and verified against all54 assets,
proxy map and cache identity in0.453s under the existing CPU/time governor. Content
ID:`5a55483512ff75d5a09b676b865b721e07ce9390f8f882a6f858243400f54246`.
Its origin-storage protection permission remains separate from per-paper pinning,
PDF verification and research backup. It is built, not deployed HTTPS/PWA or
physically accepted on Safari/phones. Hosted continuous sync remains undeployed;
list-package export/import is the available cross-machine handoff.

Device-retained control prefixes and recovery comparison are not independent
anchoring/fencing. Complete writer/file enrollment, hosted recovery and installed
multi-device acceptance still gate v0.5.0. Queued offline verification also refuses
changed originals/research/storage; this is not whole-workspace offline proof.

## Requirements and actual boundaries

| Required outcome | Verified implementation boundary | Still open |
|---|---|---|
| Desktop research synchronization | Shared operations, transactional local writes/outbox, retained history and strict transport have source/packaged protocol evidence | Complete supported writer/runtime adoption, remaining legacy/source mappings, installed two-device convergence |
| Offline work and retry | Local research, durable requests, duplicate/restart checks and cached report generation pass for named journeys | Full installed offline trip/reconnect journey and remaining producer/file lifecycles |
| Conflicts and deletion | Supported edit/delete resolution and reviewed recovery preserve history in fixtures | Remaining scientific deletion/recovery mappings and installed conflict UX. Global paper deletion is explicitly rejected by the current shared codec; supported list retirement preserves paper research. |
| Verified attachments | Exact originals, owned manifests, resumable transfers, offline preparation and wrong-source refusal have scoped evidence | Automatic reference-aware eviction/history lifecycle, complete supported attachment coverage and physical interrupted-transfer acceptance; source legacy cleanup now rechecks offline intent and managed-original owners under a writer reservation at each deletion |
| Mobile reading and notes | PWA source includes durable notes/outbox, private sessions, verified reading, offline preparation and explicit origin-wide storage-protection status/request; content-addressed2021103 artifact is built and independently verified | Coordinated HTTPS deployment, Safari/iOS/Android durability, quota and foreground/reconnect journeys |
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
