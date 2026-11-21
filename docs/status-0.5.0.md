# v0.5.0 current status

Updated 2026-11-22. **Development candidate. Physical device acceptance is pending.**

The [f489005 desktop installers](testing/mac-acceptance-0.5.md#start-here-on-apple-silicon) support automatic selected-list sync after confirming device enrollment. Newly checked lists include notes, linked Q&A, original PDFs, guides, reading status and page numbers. Previously saved lists retain their individual settings. Windows, Apple Silicon and Linux passed the [packaged research workflow](https://github.com/puddings-world/Paperfact/actions/runs/44938896885). The same run produced the [mobile web artifact for staging](https://github.com/puddings-world/Paperfact/actions/runs/44938896885/artifacts/14720892910). Physical personal Drive exchange and offline mobile acceptance over HTTPS are still pending.

The downloaded mobile artifact for **297c7a3** (content digest `9f5a5bb4a0de`) passed the offline reading and two-way plain-note journeys in Windows Chrome with isolated profiles. The reader reopened a cached PDF offline. A synthetic note survived an offline reload, queued once and reached an isolated desktop database through a loopback service. The desktop revision returned to the mobile reader. Real phone storage eviction, mobile HTTPS pairing and physical device sleep/wake still need testing.

The [211f117 paired desktop installers](https://github.com/puddings-world/Paperfact/actions/runs/44891577834) include per-list reading progress, conflict comparison and offline guide editing. Both installers include device-local saved Google sign-in and opt-in startup sync for ordinary lists. Native credential storage and restore still require physical acceptance on each OS. A synthetic 5,010-paper round trip passed with a lost acknowledgment and an offline addition from the second device. This build also recovers interrupted uploads when Drive saved a change but its reply did not reach the device. The [same-source candidate run](https://github.com/puddings-world/Paperfact/actions/runs/44891577834) passed the packaged research workflow on Windows x64, Apple Silicon and Linux. Its [verified mobile web build](https://github.com/puddings-world/Paperfact/actions/runs/44891577834/artifacts/14702192506) is available for staging. On Windows Chrome, the downloaded PWA artifact (35119ed1584a) reopened one verified PDF offline. The paper metadata digest and empty outbox persisted. English and Traditional Chinese fit a 390-pixel viewport. Chrome declined persistent storage, and the app showed best-effort storage without requesting permission again on reopen. Physical Windows/Mac exchange through personal Drive, mobile HTTPS deployment, and iOS/Android offline acceptance remain pending.

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
Older downloads below do not contain personal Drive sync. The scoped live Drive
check completed on November 22 using two isolated desktop databases on Windows.
It created 14 synthetic objects, wrote 17,783 bytes, verified the received PDF
by hash and received the laptop fixture's offline note edit back on the desktop.
Cleanup completed. Discovery was restricted to the test folder. Opening the
installed apps on two physical devices, discovering the same account directory,
and resuming after restart with the native credential stores still need acceptance.

The personal Drive path exchanges list membership, original PDFs, saved notes,
explanations, reading status and page suggestions. The reader's chat history is
stored separately. The scoped Drive transport now carries native message IDs,
reply links and source hashes in an independently permissioned conversation
history. Its two-client fixture sends a question from one device and returns
the reply from another. Directory format v12 appears only when a conversation
head is published. Older readers stop on this format. A concurrent rename must
refresh before retrying and preserves the latest message-history head.
An explicit v13 transport capability permits historical messages without reply
links. A directory advances to v13 when one is published and preserves this
requirement across list renames. Newly enabled desktop Q&A sync includes these messages.

The ordinary desktop sync cycle transfers linked reader questions, answers and
one-sided text edits. A two-database test on Windows uses the real reader schema
and simulated Drive. It verifies a reply from the second database, a later edit,
conflicting offline edits and preservation of a local removal. The reader offers
to reload externally changed Q&A. Previously enabled Q&A keeps its linked-only scope
until the user selects **Include older Q&A** for that list on that device. Historical rows receive stable per-paper IDs
without inferred reply links. The in-app comparison can resolve divergent text edits on either side and
rejects stale choices. A reader can restore a locally deleted message with its
original reply link, or keep that version deleted only on this device. Restoring a
historical message with a saved local identity preserves its place in the conversation. A later
remote revision reopens review. Reader deletion and its observed Drive revision are
recorded in one local transaction. Restoring the message withdraws the deletion
record. A missing row alone is identified as missing in the comparison. Propagation of confirmed deletions remains open. Continuing a conversation in the installed Windows and
Mac apps through the user's Drive remains an acceptance gate.

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

## Which lists a second device can see

Build 7211313 reads the private Drive library directory. Each device chooses
its own lists, including lists that have never been downloaded on that device.
Selecting a list exchanges its bibliography and details. Reading progress,
notes, original PDFs and saved guides have per-list controls. Background sync
while the app is open and reconnect on startup are device settings. See the
[desktop sync guide](../README.md#sync-a-desktop-and-laptop-v05-preview).

The earlier 052d9ab pilot used an isolated selected-list workspace. Migration
from that pilot and the installed Windows/Mac round trip with a personal Drive
account still require acceptance. See the [device checklist](testing/mac-acceptance-0.5.md).

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
3. **Desktop completion:** candidate 1c3baea passed a synthetic private survey
   handoff into the installed Windows CLI and the CLI copied from the Mac DMG.
   Both saved the intended model and verified quotation, reopened the retained
   report and served the cached retry with one loopback completion. The parent
   ran the Qt handoff harness. Verify the installed desktop account switch and
   the retained-report review/finish buttons end to end; source/widget tests alone do not
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
