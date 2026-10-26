# v0.5.0 — Research across devices

Status: in development, unreleased, 2026-10-26. Published baseline: v0.4.1.
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

Keep v0.4.1 available during development. Set the package version to v0.5.0 only
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
- Windows, macOS, and Linux full checks and packaged acceptance pass; iPhone and
  Android results are recorded separately from simulated browser tests.

Architecture: [sync design](sync-architecture.md).
Implementation and agent handoff: [work plan](implementation-0.5.0.md).
