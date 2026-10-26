# v0.5.0 implementation and session handoff

Status: local foundation in development, 2026-10-26. Planning checkpoint: `c6ba6d9`.
Journal, research adapter, reference service, client and attachment foundations
exist. Existing app actions are not enrolled in sync yet.
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
- **S03 partial:** explicit-path list/paper/membership/plain-note adapters, portable
  identities and shared transactional intake actions preserve legacy rows. Existing
  UI/CLI/MCP/import/AI writers are not enrolled yet.
- **S04 partial:** SQLite reference authority with device credentials, revocation,
  retries and conflicts. Bounded authenticated loopback HTTP is implemented; production identity
  and remote HTTPS deployment remain gated.
- **S05 partial:** bounded push/pull and atomic materialization/cursor, with preserved
  conflict history and explicit cross-device resolution. Desktop draft/selection
  integration and full entity coverage remain.
- **S06 partial:** verified resumable local blob store; authorization, research manifests,
  offline pinning and transfer UI remain.
- **S09/S10 handoff prepared:** independent Claude mobile worktree created; launch was
  blocked by Claude's first-use workspace trust prompt. No Claude execution is claimed.
- **S07/S08/S11/S12 implementation pending.** Planning and task ownership are in
  [parallel work](parallel-work-0.5.0.md); the table retains complete acceptance targets.
- [Delivery decision](adr/0002-sync-delivery-boundaries.md) records the reference-first
  approach and the identity, hosting, encryption and retention gates.

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


## Second local slice (verified foundation)

- Source schemas: `sync_journal.py`, `sync_research.py`; existing application schema
  is exercised in `test_sync_research_roundtrip.py`, not the owner's database.
- Service/client: `sync_service.py`, `sync_client.py`; two isolated research stores
  exchange list names/plain notes and retain edit/edit or edit/delete conflicts.
- Attachments: `sync_blobs.py`; staged chunks, resumable offsets, quota reservation,
  hash verification and atomic publication, with no production file migration.
- Review caught upload-ack/pull gaps, stale-page materialization and fabricated conflict
  heads. Regression tests reproduce those failures before their fixes.
- Release and workspace UX plans: `docs/release-readiness-0.5.md` and
  `docs/workspace-settings-0.5.md` (planning complete; runtime/UI and release acceptance remain pending).
- Full-check evidence for this slice: **1,378 Python tests passed** in
  437.50 seconds, **18 frontend tests passed**, privacy scan and Ruff passed.
  Log: `build/sync-roundtwo-check.log` (local ignored artifact).
- The acceptance includes actual loopback HTTP between two fixture research
  databases and explicit conflict resolution. No production database, hosted
  service, real AI account, installer, Mac or mobile-device check was performed.
- Read projection: `sync_projection.py` exposes a consistent local DB snapshot
  with honest pending/awaiting/deferred state; it explicitly is not canonical
  server bootstrap and does not claim file/deck support.
- Next domain decision: [research entity capture](adr/0003-research-entity-capture.md).
  Paper/membership identities and parent-aware materialization must land before
  existing app writers are enrolled.
- Claude dispatch: both the isolated mobile worktree and existing checkout
  returned `Workspace not trusted`. No Claude task started. The owner was asked
  to accept first-use trust for the mobile worktree; core development continues.

Next integration gates, in order:

1. Verify explicit conflict resolution and bounded HTTP acceptance in fixtures
   with the complete existing regression suite.
2. Expand the operation/read-projection contract to paper metadata, list membership,
   order, reading state, anchors, analyses and deck/asset manifests before enrolling
   existing writers. Do not silently drop unsupported content.
3. Add shared transactional capture to the audited UI/CLI/MCP/import/AI write paths;
   verify unsaved desktop drafts and selection during remote refresh.
4. Add consistent bootstrap, authenticated blob ownership/transfer, backups/restores,
   and explicit enrollment/revocation lifecycle.
5. Integrate the Claude mobile contribution and its tests into the full check;
   implement reviewed private browser sessions and foreground/offline acceptance.
6. Run the release matrix, including real Mac/phone and packaged upgrade journeys.
   Preserve v0.4.1 until the complete v0.5 release gate is satisfied.


## Third local slice: complete graph intake (verified core)

- [Private v2 graph](sync-graph-contract.md): paper metadata, list membership and
  portable paper IDs; parent incarnation/structural preconditions protect deletion,
  explicit restoration and concurrent child edits. V1 cannot bypass enrolled parents.
- [Client](sync-client.md): root-first projection, protected pending descendants,
  recoverable stale children and bounded deferred diagnostics. Accepted history stays
  separate from materialization; a later parent rename cannot strand an older child.
- [Shared operations](sync-operations.md): one connection and commit cover list,
  paper, membership, notes, outbox and action receipt. Identical and concurrent retries
  return the original result; partial failures leave no partial intake.
- [Read projection](sync-projection.md): explicit DTO v2 uses portable references and
  known graph write metadata. DTO v1 remains unchanged; neither is server bootstrap.
- Targeted transaction/intake/import-boundary tests: **31 passed**. This includes
  a real loopback HTTP journey into an empty fixture research DB with paged delivery
  and a late list rename. Review then reproduced/fixed a late-peer membership
  creation-time mismatch and three whole-transaction SQLite abort cases. Full-check
  evidence: **1,506 Python tests passed** in 387.67 seconds, **18 frontend tests
  passed**, privacy scan and Ruff passed. Log: `build/sync-graph-check.log`
  (local ignored artifact). No real cloud, AI account, Mac, mobile or installer
  acceptance was performed for this library slice.
- Existing app actions, complete order/read-state, analyses, anchors, editable decks,
  attachment transfer/authentication, backups, production login and mobile acceptance
  remain incomplete. No real workspace, account, deployed service or release changed.

Next implementation: order and per-membership reading state with separate conflict
domains, then audited shared writer capture. Production enrollment stays disabled
until unsupported writes cannot silently escape synchronization.


## Fourth local slice: per-list reading state (verified core)

- Add `reading_state` as a separate conflict domain with a closed membership/list/paper
  parent closure. This fixed domain depth does not require a generic recursive graph.
- Shared actions preserve existing timestamp transitions, isolate each list, retain
  retry results and roll back bulk failures. Targeted action tests: **14 passed**.
- The research adapter guards the projected membership incarnation; old-state retirement
  cannot reset the state of a newly restored membership. DTO2 exposes readiness and
  timestamps; DTO1 is unchanged. The DTO2 exact-shape test is extended for the new
  reading-state object while retaining every previous field assertion.
- Full check: **1,619 Python tests passed** in 411.04 seconds, **18 frontend tests
  passed**, privacy scan and Ruff passed. Log: `build/sync-reading-state-check.log`
  (local ignored artifact). No real cloud, account, Mac, phone or packaged UI
  acceptance was performed. Existing application writers remain unenrolled.
- Next: lifecycle-aware list/paper ordering, then complete research/file capture.
  Ordering, desktop sync UX, backup/bootstrap/authentication, mobile and the
  full release matrix remain required; this is not a completed v0.5 release.
- Review confirmed safe retirement of a child tied to a rejected membership
  creation attempt in an isolated temporary fixture. A named regression is
  queued for the next slice; the reported suite count does not include it.


## Fifth local slice: deterministic ordering (verified core)

- Keep list/paper ordering independent of metadata and reading state. Full ordering
  intents use their own entity revision, plus an observed-set digest over exact active
  identities/incarnations in an authenticated scope. Normal parent lifecycle checks
  still apply to an empty list; a matching digest cannot authorize a deleted scope.
- The digest replaces the earlier proposed separate set clock: offline creation uses
  stable incarnation IDs, so clients need not predict server revisions. Citation/read
  edits do not invalidate it. Transient add/remove returning the identical active set
  may accept the old complete permutation; history still retains those events.
- A stale reorder arriving after a set change conflicts. Later membership-set changes
  can remain valid: filter removed/replaced incarnations, then append new ones by
  accepted creation-receipt sequence. Never sort by latest metadata revision. Existing
  graph deletion guards still apply: list_order touches its parent list structure, so
  a concurrent parent-list deletion may conflict with that child edit.
- Implement the same deterministic fallback when no explicit order exists, with an
  independent trusted projection writer. Pending local ordering/lifecycle work defers
  projection; received order payloads remain immutable history.
- Shared action integration: **21 targeted tests passed** using two isolated
  actual-schema research databases. Service/adapter/client suites cover additional
  races and projection failures. Full check: **1,750 Python tests passed** in
  357.15 seconds, **18 frontend tests passed**, privacy scan and Ruff passed.
  Log: `build/sync-ordering-check.log` (local ignored artifact). Existing desktop
  drag/drop controls remain outside sync until the writer enrollment gate is complete.
- The four rejected-lineage retirement cases queued in the previous slice are now
  committed and included in this count. Historical parent attempts can be safely
  discarded without changing a different canonical child or resurrecting a parent.
- Next: authenticated immutable PDF transfer and paper-document manifests, with
  separate desired/applied byte availability. The current legacy reader/text/figure
  caches and some anchor jumps require hash-aware integration before PDF activation.
  Do not call legacy PDF replacement or URL discovery during remote application.
- No real account, workspace, hosted service, Mac, phone or installer acceptance
  was performed. Full research/file capture, UI enrollment, recovery, production
  authentication and mobile acceptance remain release gates.
