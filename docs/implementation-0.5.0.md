# v0.5.0 implementation and session handoff

Status: local foundation in development, 2026-10-26. Planning checkpoint: `c6ba6d9`.
An isolated journal prototype exists; no app action participates in sync yet.
No cloud deployment, credential changes, production migration or version bump.

## Read first

1. Root [AGENTS.md](../AGENTS.md): preservation and full-check requirements.
2. [Release scope](roadmap-0.5.0.md): product goals, priorities, and exclusions.
3. [Sync architecture](sync-architecture.md): proposed contracts and unresolved decisions.
4. [Current architecture](architecture.md), [local integration](local-integration.md),
   [sharing](sharing.md), and the mobile section of [reader guide](reader-guide.md).

Use the active `Paperfact` checkout. The old `paper-daily` checkout is an archive;
verify the repository remote, branch, and worktree before editing. Preserve other
sessions' changes. This plan is shared context, not authorization to deploy, upload
research, publish a release, install global hooks, or use paid model calls.

Applicable canonical skills: `agentic-local-integration`, `agentic-provider-routing`,
and `agentic-private-events` under `skills/`. Read the relevant one before working
on its boundary. No global skill changes are needed for this unimplemented design.

## Work ledger

Owner/session: Codex, 2026-10-26, `feature/0.5-sync-foundation`.

- **S01 reviewed baseline:** [writer inventory](sync-write-inventory.md), with dynamic
  writers and unsupported integration paths explicitly listed. Adapter coverage is pending.
- **S02 partial:** [local journal ADR](adr/0001-local-sync-journal.md); production identity,
  remote conflicts, hosting/authentication and encryption decisions remain open.
- **S03 in progress:** isolated `sync_journal.py` and behavioral tests; no production
  writer adapters, integer-ID migration or full sync implementation.
- **S04-S12 not started.** The table below retains the complete acceptance targets.

| ID | Deliverable | Depends on | Acceptance evidence |
|---|---|---|---|
| S01 | Inventory research entities, file formats, and every mutation entry point | — | Writer-to-entity map; credential exclusion map; uncovered writers explicitly listed |
| S02 | Schema/protocol/conflict ADR and backend/auth/encryption decision record | S01 | Two-device sequence examples, version policy, recovery and hosting constraints |
| S03 | Stable IDs, transactional outbox, receipts, and safe local migrations | S02 | Duplicate, rollback, crash/restart, legacy-data preservation tests |
| S04 | Reference sync service with workspace authorization and fake transport | S02 | Cross-user denial, revoked device, retry-after-commit, bounded request tests |
| S05 | Desktop push/pull, causal ordering, conflicts, and UI invalidation | S03, S04 | Two isolated workspaces converge; same-record conflict preserves both versions |
| S06 | Immutable attachments, manifests, transfer resume, and offline pinning | S05 | Interrupted download, corrupt bytes, wrong PDF, missing deck asset, quota tests |
| S07 | Snapshot/restore, tombstone retention, bootstrap, and client compatibility | S05, S06 | Restored data/hash comparison; stale device cannot resurrect deleted research |
| S08 | Desktop onboarding, sync states, devices, storage, and resume UX | S05–S07 | Empty/nonempty onboarding, cancel/retry, account switch, close/repeated-click checks |
| S09 | PWA shell, private session, offline storage, and verified reading packs | S04, S06 | No desktop dependency; foreground recovery; quota/error and session-isolation tests |
| S10 | Mobile note writes, reading progress, and shared semantic fixtures | S05, S09 | Offline edits reach desktop once; conflicting edits and stale sessions preserve work |
| S11 | Companion features and new-flow language/accessibility pass | S08, S10 | Resume without focus theft; clear offline completeness; keyboard/touch checks |
| S12 | Cross-platform packaging, real-device pilot, docs, and release | S01–S11 | Full suites; frozen acceptance; Windows/Mac/iPhone/Android journey; approved service readiness |

## First implementation slice

Start with S01/S02 and record the inventory before introducing a cloud dependency.
Then prove a small vertical slice using two synthetic local workspaces and a fake
remote service:

1. Create/rename a list and add/edit a text note in workspace A.
2. Save the mutation and pending operation atomically; simulate process restart.
3. Push twice, pull twice into workspace B, and assert one logical result.
4. Edit the same note offline in A and B; preserve both after synchronization.
5. Apply a remote update while an editor has an unsaved draft; keep the draft and focus.
6. Verify that AI calls, provider credentials, and analytics were never involved.

This slice proves mechanics only. Do not claim full workspace sync until every
supported research writer and attachment type in S01 is covered.

## Decision records to complete

Use concise ADRs with status, alternatives, decision, consequences, and evidence.

- Stable identity, bootstrap, and import-versus-sync identity boundaries.
- Capture method for direct SQLite/file writers; no silent unsupported mutation path.
- Wire schema, causal dependencies, conflict resolutions, and protocol compatibility.
- First service/storage backend, self-host packaging, auth, and operating budget.
- Encryption, recovery, deletion/history retention, and offline device horizon.
- PWA session/storage model and minimum iOS/Android browser versions.
- Workspace location/migration policy, including source/installed copies and Windows.

Record unresolved product choices instead of choosing a paid service or uploading
the owner's real workspace as a shortcut. An isolated local prototype can proceed
without those external actions once implementation is requested.

## Verification matrix

- **Durability:** interrupted save/apply/upload, timeout after server commit, duplicate
  delivery, out-of-order responses, process restart, unavailable or full storage.
- **Concurrency:** independent edits, same-field edit, edit/delete, rename/order,
  multi-list membership, stale base, concurrent conflict resolution.
- **Identity:** second user/device, stale auth response, revocation, restored backup,
  cloned directory, nonempty workspace joining, incompatible client.
- **Files:** large fixture PDF, content/hash mismatch, changed PDF version, interrupted
  attachment transfer, missing slide asset, cache eviction, offline-only access.
- **UI:** cancel, retry, repeated activation, selection/account/workspace changes,
  close while pending, unsaved drafts, visible saved/synced/offline distinctions.
- **Mobile:** iPhone/Safari and Android/Chrome foreground return, offline restart,
  touch selection, text size, session isolation, storage pressure, and recovery.
- **Privacy:** no AI secrets/telemetry in sync; no research in diagnostics; no implicit
  generation, network PDF fetching, or consent changes on remote apply.

Use fixture data, simulated services, and isolated profiles. Real account/device
checks are separate and recorded honestly. Backend/PWA checks must become part of
the project's full check as their code lands, rather than a separate optional suite.

Run the existing full check before declaring an implementation complete or committing:

```powershell
.\.venv\Scripts\python.exe scripts/check.py
```

```bash
.venv/bin/python scripts/check.py
```

## Handoff after each slice

- Update this ledger with scope, owner, evidence, and remaining failures.
- State which data types/writers are still unsupported.
- Record exact automated counts and separate manual/device/provider results.
- Preserve the current release; do not bump versions or publish from a planning task.
- Update reusable skills only after a verified pattern warrants it; this proposal
  itself is not implementation evidence.

## Planning checkpoint

- Prepared the English scope, architecture proposal, and implementation sequence.
- Added discovery links for repository readers, Codex, and Claude sessions.
- Runtime behavior and existing workspace paths remain at the v0.4.1 baseline.
- Next task: connect a shared list/note adapter in fixture workspaces, then implement
  fake-peer push/pull, accepted revisions and preserved conflicts. The two-device
  vertical slice above is not complete.
- Verification: 32 new journal cases; full `scripts/check.py` passed with 1,157 Python
  tests and 18 frontend tests, plus privacy scan and Ruff. Log: `build/sync-foundation-check.log`
  (local ignored artifact). No live cloud, mobile, power-loss or cross-device check was performed.
- This applies an existing repository-local atomic receipt pattern; no new global
  skill rule or installation was introduced at this checkpoint.
