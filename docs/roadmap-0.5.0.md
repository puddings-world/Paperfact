# v0.5.0 — Research across devices

Status: in development, unreleased; updated 2026-11-13. The independently
maintained v0.4.x releases remain the daily-use line. They do not enable unfinished
v0.5 synchronization. See [current implementation evidence](status-0.5.0.md);
[delivery status](delivery-status-0.5.md) preserves the historical gate ledger.
The reference service, managed PDF reader, partial app-writer capture and independent
mobile client have fixture coverage. Complete writer/file enrollment, production
identity/hosting, recovery UX and real-device acceptance remain release gates.
See the implementation ledger for exact coverage rather than inferring release readiness.

## Release goal

- Continue the same research on Windows, macOS, and a phone.
- Read and edit offline; reconcile changes when connected.
- Keep research local and usable without sync, AI login, or analytics consent.
- Support researchers in any field, using their own supported AI accounts.
- Preserve every user's existing research when enabling sync or upgrading.

**Acceptance journey:** prepare research on a desktop, read and annotate on an
offline Mac, add a note on a phone, then return to the desktop with all changes
accounted for. Conflicting edits remain recoverable.

## Required scope

| Area | v0.5.0 outcome |
|---|---|
| Desktop sync | Lists, membership, names, order, reading state, notes, analysis, source anchors, and editable decks synchronize between Windows and macOS. |
| Offline work | Local saves survive restarts; queued changes retry without duplicate records. |
| Conflicts | Concurrent changes to the same content retain both versions and offer an explicit resolution. |
| Attachments | PDFs, figures, and deck assets use verified hashes, deduplication, resumable transfers, and optional offline pinning. |
| Mobile reader | A private PWA reads PDFs, explanations, citations, highlights, and slides; adds or edits text notes; records reading progress. |
| Sync visibility | Distinguish saved locally, pending upload, synchronized, failed, and conflicted. |
| Recovery | Version history, recoverable deletion, independent backups, and tested restore. |
| Workspace settings | Show the active location, storage usage, offline availability, backup actions, and connected devices. |
| Private access | Per-user workspaces, authenticated device enrollment, session revocation, and no anonymous research URLs by default. |
| Existing integrations | UI, CLI, MCP, imports, and completed AI jobs produce consistent research changes. |

Reading position is a resume suggestion, not a command to jump the active reader.
Mobile sync runs reliably on launch, foreground return, and reconnect. Background
sync is an enhancement where supported, not a delivery guarantee.

## Grounded reading features (planned)

The first three planned v0.5 reading features match the README positioning added in
`90f8c60`. They are not claims about the currently published release or complete
writer enrollment in this development snapshot.

- **Per-list reading goals:** give each list an editable research goal and intended
  depth/background, so its papers can be read and analyzed for that purpose.
  Preserve the user's goal separately from generated analysis and manual notes.
- **Claim-level sources:** connect each explanation claim to an inspectable passage
  in the correct source document, or explicitly show that no source was found.
  Keep document identity and anchors with the claim; never invent a citation.
- **Lineage explanations — why this paper exists:** explain the gap in earlier
  work and how later work built on this paper, grounded in quotations from the
  relevant papers. Distinguish supported statements from inferred relationships.
- **Analysis audit:** check every AI output against the paper and against the
  other outputs (quotes, numbers, reference identity, claim grounding, lineage
  rules), and show the reader each finding. Design: [analysis-audit.md](analysis-audit.md).

Acceptance includes changing a list goal without losing research, inspecting a
claim against its exact PDF version, showing missing evidence honestly, and
preserving the goal/source/lineage provenance across supported sharing and sync.
Per-list purpose editing, sharing, capture and mobile display are in the current
local candidate. Source-pinned claim extraction, deterministic quote-location
checks, saved-first cards and portable/unbound original-version inspection also
have fixture coverage. Quote location does not certify semantic support. Grounded
lineage has a saved-first desktop reader, explicit native publication and mobile
saved display with local integration tests. Source-complete enrolled package
import and mobile exact-original reading now have affected integration evidence.
Native package version comparison and preserved prior history now have local
integration evidence. Existing-beta history backfill now has a bounded local
service, offline action and automatic-sync integration with fixture acceptance.
Unknown legacy-result migration, actual installed migration, complete analysis audit, remaining typed
producer/history enrollment, complete editable-recovery migration/UX and
physical-device acceptance remain open;
task templates do not satisfy those gates. A bounded local A1 audit and the
editable-recovery service have focused coverage in the current candidate; neither
satisfies the complete audit or recovery release requirement.

A bounded source-fact/consistency slice is also present in the local candidate:
one explicit Audit request over selected saved outputs, inspected quotations and
paired value differences in a modeless view. It remains a researcher-review
proposal with temporary copyable results. Pending comparisons now have a bounded
read-only recapture for unchanged research inputs after reading-state writes;
source/owner changes still reject delivery, without an automatic model retry.
Complete corpus/CLI coverage, continuity after result acceptance and expert
evaluation remain separate work. See [reading continuity](audit-reading-continuity.md).

The next list-recency improvement is initially local-only reading state. Dragging
still commits the explicit shared custom order. See the concrete
[list recency and ordering handoff](list-recency-handoff.md) before implementing it.

## Companion features

Include these after the sync invariants pass; keep them tied to the release goal.

- **Continue reading:** recent papers and a clear resume action across devices.
- **Prepare for a trip:** pin selected papers; show missing files and required space.
- **Recent changes:** summarize completed research changes from other devices.
- **Research inbox:** paste a DOI, URL, or short idea on mobile for desktop triage;
  adding an item does not silently invoke AI.
- **Language-ready flows:** externalize new strings and plan English/Traditional
  Chinese onboarding, sync, and mobile copy. Full legacy UI translation is separate.

Version history, backup, and conflict handling are release requirements, not optional
polish. Workspace relocation is a separate migration task, not a folder-picker shortcut.

## Explicit boundaries

- One research owner with multiple devices; team co-editing is a later milestone.
- Sharing a bundle remains a snapshot transfer, separate from private synchronization.
- Mobile starts with reading and notes; full slide editing and remote desktop AI jobs
  are outside the initial mobile scope.
- No AI subscriptions, credentials, billing receipts, or vendor login directories
  travel with research. Provider/model preference sync is deferred until devices can
  explicitly map preferences to their own available connections.
- No automatic analysis, PDF re-download, or paid fallback merely because data arrived.
- No direct synchronization of a live SQLite file through a cloud folder.
- No app-store/native mobile release, commercial token service, or multiple cloud-drive
  adapters required for this milestone.
- Enabling research sync does not opt the user into product analytics.

## Delivery sequence

1. **A — Desktop correctness:** inventory writes, define identities, build local
   mutation/outbox boundaries, and prove two isolated desktops converge.
2. **B — Offline and recovery:** attachments, retry/restart, conflicts, deletion,
   device revocation, snapshots, and compatibility checks.
3. **C — Mobile continuation:** independent PWA login, offline packs, notes, resume,
   and real iPhone/Android acceptance.
4. **D — Public beta:** package all desktop platforms from one tag, document the
   service's privacy/cost limits, and run the complete user journey.

Keep the stable v0.4.x maintenance release available during development. Set the package version to v0.5.0 only
when preparing a release candidate. Mark the initial release as a GitHub prerelease;
the existing updater recognizes numeric `vX.Y.Z` tags.

## Decisions before a hosted pilot

- First hosting/storage deployment, region, capacity, operational budget, and operator.
- Sync identity provider and device-enrollment/recovery flow; independent of AI login.
- Encryption threat model: TLS/storage encryption versus end-to-end encryption,
  including key recovery. Do not advertise end-to-end encryption before it exists.
- Version/deletion retention and the maximum supported offline interval.
- Minimum mobile browser versions, offline size targets, and accessibility checks.
- Default workspace location policy and safe migration of existing installations.

Choose one reference sync backend first; keep a documented self-host deployment
path and replaceable storage boundary. Do not assume every file host can enforce
the transactional revision and authorization requirements.

## Release gate

- Three devices converge after supported independent edits; conflicts lose no content.
- Restart, interruption, duplicate delivery, and reordered retries produce no duplicates.
- Membership removal does not delete a paper still used by another list.
- Old/deauthorized devices cannot resurrect deleted data or access another workspace.
- Wrong PDF versions never receive another version's highlights or source anchors.
- No account secrets or telemetry enter sync payloads; cross-user isolation is tested.
- Backups restore into an isolated workspace with matching research and file hashes.
- Mobile notes survive ordinary reload/restart and show any unsent or storage-failed state.
- Curated release requirements pass once, with critical/frozen acceptance on each
  shipped Windows/macOS/Linux target and affected regressions. Historical exhaustive
  runs are opt-in diagnosis. iPhone/Android physical results remain separate from
  simulated browser tests; see [release gates](release-readiness-0.5.md).

Architecture: [sync design](sync-architecture.md).
Implementation and agent handoff: [work plan](implementation-0.5.0.md).


Local recovery preparation now includes explicit authority snapshot export and
read-only verification; see [operator backup](sync-authority-backup.md). Cloud
backup automation, hosted restore and installed old-device recovery acceptance
remain required; local export/reconstruction does not complete the milestone.


Exact matching-package adoption now has an explicit reviewed native path; see
[legacy matching analysis](lineage-matching-adoption.md). This advances migration
without claiming direct source selection for every unowned legacy result, native
history repair or full installed/release acceptance.


Cloud backup preparation includes a [tested local GCS publication adapter](gcp-backup-publication.md)
with shared content and completion-last manifests. Actual private GCS execution,
remote fetch/restore, managed scheduling/retention, capacity and physical-device
acceptance remain required; a simulated upload is not an operational backup.

- Local cloud-backup retrieval: implemented exact-snapshot download, byte/generation verification and closure-before-completion; cloud restore rehearsal, retention/scheduling and installed-device acceptance remain pending. See [operator workflow](gcp-backup-retrieval.md).

- Old-device recovery review: local read-only journal/backup comparison and Advanced desktop entry implemented; explicit fresh-identity per-change reconciliation and installed recovery journey remain pending. [Details](device-recovery-review.md).

- Direct private-result adoption: explicit original-selection backend and saved-reader verification/confirmation now implemented for supported rows; no list package or AI required. Native authority corruption, unknown migrations and full/device/hosted gates remain open. [Workflow](lineage-direct-adoption.md).
