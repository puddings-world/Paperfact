# v0.5.0 current status

Updated 2026-11-21. **Development candidate; v0.5.0 is not release-approved.**
The [0fdc567 desktop installers](testing/mac-acceptance-0.5.md#start-here-on-apple-silicon) receive membership removal history through normal desktop sign-in and saved subscriptions. The [paired build](https://github.com/puddings-world/Paperfact/actions/runs/44899387884) passed packaged research checks on Apple Silicon, Windows x64 and Linux. A local two-device fixture also retained a subsequent offline edit after the response to a conflict resolution was lost. The installed personal Drive round trip is still pending.

The [211f117 paired desktop installers](testing/mac-acceptance-0.5.md#start-here-on-apple-silicon) include per-list reading progress, conflict comparison and offline guide editing. Both installers include device-local saved Google sign-in and opt-in startup sync for ordinary lists. Native credential storage and restore still require physical acceptance on each OS. A synthetic 5,010-paper round trip passed with a lost acknowledgment and an offline addition from the second device. This build also recovers interrupted uploads when Drive saved a change but its reply did not reach the device. The [same-source candidate run](https://github.com/puddings-world/Paperfact/actions/runs/44891577834) passed the packaged research workflow on Windows x64, Apple Silicon and Linux. Its [verified mobile web build](https://github.com/puddings-world/Paperfact/actions/runs/44891577834/artifacts/14702192506) is available for staging. On Windows Chrome, the downloaded PWA artifact (35119ed1584a) reopened one verified PDF offline. The paper metadata digest and empty outbox persisted. English and Traditional Chinese fit a 390-pixel viewport. Chrome declined persistent storage, and the app showed best-effort storage without requesting permission again on reopen. Physical Windows/Mac exchange through personal Drive, mobile HTTPS deployment, and iOS/Android offline acceptance remain pending.

Windows Chrome also exercised this exact PWA artifact against an isolated service and desktop database. A note saved twice offline produced one pending operation, survived an offline reload, and arrived on desktop after reconnection. A desktop reply returned to the browser and remained editable. A separate cookie-pairing journey retained cached research after forgetting the browser session. These checks used a loopback service with synthetic research. The mobile web app still needs a same-origin HTTPS service on the phone; personal Drive selected-list sync currently connects desktops.

The full target remains the [release scope](roadmap-0.5.0.md), including desktop
and mobile offline research, safe synchronization, recovery and private access.
This page separates current evidence from unfinished implementation and external
acceptance. Historical iterations belong in the
[continuation ledger](testing/continuation-20261112.md#2026-11-16-superseded-status-snapshot-90b13e5).

PDF writer adoption: source-observed replacement, list prefetch and reader/analysis
intake share the native publication boundary. Exact missing originals/artifacts can
be restored without a new research version; PDF supply does not start AI. Reviewed
package import can restore exact included private bytes and retain nullable list
descriptions; preview commits no research. Legacy cleanup retains declared saved
SQL research/reference owners, offline intent and managed originals, with fresh
checks before removal. These changes are now included in d14c512 candidates.
Existing legacy files are not automatically enrolled. Complete supported writer/
file lifecycle and reference-aware immutable-store eviction remain open.

## Personal Drive candidate preparation

The desktop Drive path is connected in source: Google account choice, workspace
discovery/create/join, selected-list intake with PDFs, supported legacy copy plus
backup, installed-workspace persistence, native grants/device
records, startup reconnect, existing conflict handling, offline outboxes,
delta/checkpoint storage and verified PDF chunks. No paid VM was provisioned.
[Contracts and limits](sync-architecture.md#desktop-drive-pilot-2026-11-18).

Drive source **052d9ab** is committed, pushed and fast-forwarded into `develop/0.5`.
The bounded critical gate passes 14 cases in 15.1 seconds; affected runtime,
selected-list/PDF, authority, UI and build-client checks pass 19 cases in 41.4 seconds.
An overlapping low-level/UI/scope check passes 18 cases in 12.6 seconds. These are
separate selections, not an additive unique-case total or an exhaustive suite.
[Mac-only run44134098189](https://github.com/puddings-world/Paperfact/actions/runs/44134098189)
succeeded: about 10 minutes queued, 7m03s executing. The [Apple Silicon installer](https://github.com/puddings-world/Paperfact/actions/runs/44134098189/artifacts/14351978610)
contains personal Drive sync. Independently hash-matched provenance confirms
clean052d9ab/arm64, actual DMG copy/detach, foreground activation, three reader
launches, package preservation and all15 named protocol outcomes. Source phases
pass14/1/54/24 cases (five warnings each); no historical full run was performed.
[Exact download and physical acceptance steps](testing/mac-acceptance-0.5.md#personal-drive-candidate-desktop-to-mac).
Older downloads below do not contain personal Drive sync. The approved synthetic
workspace test stopped at browser authorization timeout before any Drive file was
created; full live round-trip acceptance remains pending authentication. Real native-vault prompts, the user's
Google account, installed Windows/Mac journeys and the wider v0.5/mobile release
scope remain acceptance gates. No owner research was uploaded or migrated by tests.

## Previous native deliverable (before personal Drive)

Integration branch: `develop/0.5`. Latest Mac candidate source: **66855cc**. The Apple Silicon Mac
candidate now uses that exact clean source, version `0.5.0.dev`, beta-candidate.
[Run43881479241](https://github.com/puddings-world/Paperfact/actions/runs/43881479241)
passed in5m35s; draft/release skipped. It includes cancellable exact-original
supply, unsupported-format pause and claim-card regeneration history enrollment.
[Downloads and separate-app/workspace steps](testing/mac-acceptance-0.5.md#latest-tested-downloads).

Its downloaded/hash-matched native report proves arm64, exact clean source,
read-only DMG mount/copy/verification/detach, workflow from the copied app, three
reader launches/foreground and all15 sync flags. Source phases pass critical14,
first-enrollment1 and selected54; five warnings each, no failures. This does not
certify every dialog, real credential store, physical input or two-device journey.
The large installer ZIP was not independently downloaded locally.

Windows/Linux installers remain clean30b5776 from the earlier all-platform run;
no matching66855cc native build is claimed. The reproducible PWA exporter is in
current source, but this Mac-only run creates no new mobile artifact. Previously
verified mobile artifact14223076072 remains built, not deployed HTTPS/PWA or
physically accepted. Hosted continuous sync is undeployed; package export/import
is the available cross-machine snapshot handoff.

Independent authority anchoring/fencing, complete supported adoption and retention,
full new GUI/live accounts/native vaults/IME, quarantine/notarization, older installed
binary upgrades, hosted recovery and physical device journeys still gate v0.5.0.
Detailed identities and previous candidate records stay in the acceptance guide and
continuation ledger. This candidate does not authorize deployment or daily-data migration.

## Branch integration review (2026-11-18)

The current candidate includes the complete committed `feature/0.5-pdf-reference-list`
performance branch (40b36c6), both minimal-update branches, and current master.
The performance worktree is clean. Included changes reduce whole-list repaints,
avoid full-PDF reads when opening papers/slides, reduce Lineage widget counts,
defer heavy panels and warm parsing dependencies. Git inclusion is verified;
no new end-to-end latency benchmark is claimed.

Separate unmerged work is paper-identity/merge review (two commits) and the older
parallel-test runner (one commit). They are not missing runtime performance fixes;
neither was silently merged during this review. Retain the bounded serial gate.

Cross-user packages already carry supported saved research and exact included
originals into an independent recipient database. Captured/enrolled receivers use
the observed transaction path, including source-complete Lineage and explicit
native-result comparison. Remaining limits include unsupported legacy scopes,
unowned/deleted result adoption, reviewed updates after later edits, package
budgets and installed cross-user acceptance. Sharing is a snapshot, not team
co-editing; same-owner continuous Drive sync remains a separate opt-in.

## Requirements and actual boundaries

| Required outcome | Verified implementation boundary | Still open |
|---|---|---|
| Desktop research synchronization | Shared operations, transactional local writes/outbox, retained history and strict transport have source/packaged protocol evidence | Complete supported writer/runtime adoption, remaining legacy/source mappings, installed two-device convergence |
| Offline work and retry | Local research, durable requests, duplicate/restart checks and cached report generation pass for named journeys | Full installed offline trip/reconnect journey and remaining producer/file lifecycles |
| Conflicts and deletion | Supported edit/delete resolution and reviewed recovery preserve history in fixtures | Remaining scientific deletion/recovery mappings and installed conflict UX. Global paper deletion is explicitly rejected by the current shared codec; supported list retirement preserves paper research. |
| Verified attachments | Exact originals, owned manifests, resumable transfers, offline preparation and wrong-source refusal have scoped evidence | Automatic reference-aware eviction/history lifecycle, complete supported attachment coverage and physical interrupted-transfer acceptance; source legacy cleanup now rechecks saved SQL research, reference/graph ownership, offline intent and managed-original owners under a writer reservation at each deletion |
| Mobile reading and notes | PWA source includes durable notes/outbox, private sessions, verified reading, offline preparation and explicit origin-wide storage-protection status/request; content-addressed d14c512 artifact is built and independently verified | Coordinated HTTPS deployment, Safari/iOS/Android durability, quota and foreground/reconnect journeys |
| Sync visibility and settings | Workspace/device status, explicit pairing and device-local reconnect opt-in have desktop fixtures | Installed location/storage/offline and backup/device controls, native vault prompts, restart/account-switch/focus/input and cross-device UX |
| Backups and recovery | Verified authority/client backups, fresh-identity restore and reviewed editable adoption exist for supported content | Complete lossless migration/runtime adoption, cloud backup/restore rehearsal, scheduling/retention and unsupported-source handling |
| Private access | Credential isolation, revocation, verified-history writes, strict official routes and same-host listener exclusion are tested; source adds restart-persisted file identity and a local device/pairing checkpoint | Installed control-checkpoint acceptance, independent anchoring/cross-host fencing and hosted authorization/recovery; current source retains device-local prefixes across desktop join/restart and browser reconnect |
| UI/CLI/MCP/AI integrations | Existing shared operations and 45 MCP tools pass named package journeys; frozen source-aware report CLI gate now passes on all desktop OSes | Full frozen desktop private report/dialog journey and live provider/account acceptance; source now verifies production QProcess handoff to an actual CLI with disabled child disk settings |
| Grounded research features | Reading goals, exact-source claims/Lineage and bounded audit/recovery/report paths have source evidence; report provenance also has frozen CLI evidence | Complete audit/retained-result adoption and mappings; source after0a64ec7 adds list-report original/location checks in desktop/CLI/MCP. Scientific support needs researcher review beyond quotation location |

A named pass is not certification of every button, writer, document corpus or
platform. Quote location does not prove scientific support. Preserved unsupported
content must remain a visible blocker rather than being dropped to enable sync.
Typed queue pins are implemented; their historical unsupported label is obsolete.
See [queue pin migration](queue-pin-migration.md) and
[recovery UI](recovery-adoption-ui.md) for the supported boundary.

## Whole-library selection gap (owner clarification, 2026-11-18)

The installed Mac candidate at 052d9ab shows only lists in its active local database. Source
052d9ab creates a separate selected-list sync workspace; it does not expose the
complete source-library directory or let another device subscribe to arbitrary
lists in that library. This fails the clarified whole-database list-selection
requirement. The candidate is available for the existing pilot, not acceptance
of this broader workflow. See the [required correction](sync-architecture.md#whole-library-list-selection-required-correction-2026-11-18).
The owner confirmed independent selection on each device. Local directory and
revision-checked selection services now exist with bounded fixture coverage,
including cancellation/concurrency and no research mutation. The development dialog now discovers the
private directory, saves device choices and exchanges list names/descriptions
in ordinary local databases. Saving the selection also publishes an initial bibliography
or receives it into an empty list, then exchanges additions from either device on save. Subsequent metadata
edits, research notes, attachments, background replication and reviewed pilot
migration remain unfinished; Mac052d9ab does not contain
this directory flow. No owner database/cloud data
were changed during this implementation.

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
4. **Personal Drive integration:** the owner prefers their existing Drive to a
   separately billed VM. Reuse app-scoped Google login and implement safe native
   authorization persistence, account-bound replica storage, attachment transfer,
   conflict/retry and offline/reconnect acceptance. The desktop adapter is now
   implemented in source; real-account and installed-device acceptance remain. The earlier
   [GCP pilot](gcp-sync-pilot-plan.md) is optional and no cost approval was received.
   See [the revised architecture](sync-architecture.md#personal-drive-first-owner-direction-2026-11-17).
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
