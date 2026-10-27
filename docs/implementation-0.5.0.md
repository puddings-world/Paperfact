# v0.5.0 implementation and session handoff

Status: local implementation in development, 2026-10-27. Planning checkpoint: `c6ba6d9`.
Journal, research adapter, reference service, client and attachment foundations
exist. Opt-in SQL capture now exercises existing app actions in isolated fixtures;
user-facing enrollment and complete producer/file capture are still gated.
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
- **S03 partial:** portable identities, actual store transaction capture and typed
  graph/rich SQL projections preserve legacy rows. Existing list/intake actions and
  desktop note editing/deletion now exercise capture in fixtures. Unsupported writes
  fail closed; remaining editors, AI observations and file producers still need wiring.
- **S04 partial:** SQLite reference authority with device credentials, revocation,
  retries and conflicts. Bounded authenticated loopback HTTP is implemented; production identity
  and remote HTTPS deployment remain gated.
- **S05 partial:** bounded push/pull and atomic materialization/cursor, with preserved
  conflict history and explicit cross-device resolution. Desktop draft/selection
  integration and full entity coverage remain.
- **S06 partial:** authenticated workspace-owned blobs, primary-PDF manifests,
  independent desired/applied bindings and a bounded resumable transfer coordinator.
  Exact managed-reader activation, versioned derivatives and bounded block reads
  now have fixture coverage. Offline pinning, other attachment types, cache/history
  lifecycle and complete transfer/onboarding UI remain.
- **S09/S10 partial:** an independent PWA now has IndexedDB notes/outbox/drafts,
  private transport contracts, verified PDFs, read-only rich research and conflict
  handling. Its isolated agent worktree is integrated. Claude launch remains blocked
  by first-use workspace trust; no Claude execution is claimed. Public browser login,
  deck transport, mobile resume and physical-device acceptance remain gated.
- **S07 partial:** detached backups validate research, operation provenance and file
  closure, then restore with a fresh identity. Verified legacy PDFs and saved slide
  results now travel as archive-owned provenance. Bootstrap, retention policy and
  normal-reader adoption remain required; an archive is not device enrollment.
- **S08 partial:** retained-work review, durable edited drafts, grouped candidate
  review and workspace status/backup UI are implemented locally. User-facing
  onboarding, device management, sync connection, offline pinning and resume UX remain.
- **S11/S12 implementation pending.** Planning and task ownership are in
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

The [owned document transfer contract](adr/0004-owned-document-transfer.md) now has
an opt-in reference implementation; the reader/anchor gates remain unimplemented.
See [transfer coordinator](sync-transfers.md), [document bindings](sync-documents.md)
and [workspace blob service](sync-blob-service.md). This is not a shipped sync feature.


## Authenticated primary-PDF transfer checkpoint — 2026-10-26

- Added exact document manifests, metadata-only receive/intents, verified PDF binding
  and DTO2 availability; DTO1 and existing legacy research stay unchanged.
- Added workspace-owned upload/read/cancel APIs and authenticated session discovery.
  Bind the opaque credential to the intended workspace/device before sending bytes;
  generation invalidation alone does not prevent wrong-account uploads.
- Added shared local staging/attach actions and a bounded transfer coordinator.
  Research/outbox/action receipts commit together; byte transfer remains independent.
  Retry, cancel, restart, lost responses and stale completion use fixture tests.
- Internal review reproduced/fixed source-versus-durable-offset confusion, valid
  overlapping upload acknowledgments, corrupt partial retry loops, and publication
  after cancellation/sign-out. No credentials or provider error messages are saved.
- Full check: **1,921 Python tests passed** in 657.21s (0:10:57),
  **18 frontend tests passed**, privacy scan and Ruff passed. Local log:
  `build/sync-document-check.log`. This checkpoint does not enroll existing
  desktop/CLI/MCP/import/AI writers or activate
  the PDF reader, and it does not claim complete v0.5.0 or release readiness.
- Next implementation: hash-aware reader/anchor/cache activation and bounded
  per-chunk integrity verification; then full research entity capture, bootstrap/
  recovery, desktop UX and the mobile reader. All original S01–S12 gates remain.


Concrete next contracts: [reader activation](adr/0005-document-reader-activation.md)
and [bounded blob integrity](adr/0006-bounded-blob-integrity.md). Both are plans,
not completed runtime features. The Claude/mobile handoff now points to the actual
DTO2 and authenticated document contracts rather than the earlier v1 proposal.


## Managed reader and bounded integrity checkpoint — 2026-10-26

- Implemented [ADR0005](adr/0005-document-reader-activation.md): exact document
  resolution, registered device-local roots, owned `.pdf` projections, metadata-only
  list inspection, and background desktop verification. Registration does not enroll
  legacy research or capture existing writers into sync.
- Incoming versions announce an explicit switch while retaining the current PDF,
  selection, drafts and focus. Activation rechecks context; failed replacements
  preserve the prior native view. Managed/ambiguous/missing documents cannot fall
  through to legacy aliases, publisher fetching or automatic AI.
- New note anchors carry a PDF hash. Source jumps/highlight writes/external opening
  validate the currently rendered version; old verified versions remain usable until
  explicitly switched. Invalid contexts clear the PDF without erasing editor text.
- Fixed native Qt handle release by detaching and disposing the old document. The
  Windows fixture can remove the projection after unload; both PDF backends retain
  the old document on a rejected replacement.
- [Versioned derivatives](document-derivatives.md) cover text/figures, previews,
  pocket/share consumers and editable-deck intake. Positional managed figure/page
  IDs include source hashes, so versions coexist without reusing the wrong asset.
  Legacy files, caches and deck assets are retained.
- Implemented [ADR0006](adr/0006-bounded-blob-integrity.md): server-computed block
  digests committed with ownership, bounded verified reads and safe lazy backfill.
  Instrumented tests verify one aligned block, at most two unaligned blocks and zero
  content reads at EOF; full-file checks still guard manifest publication.
- Targeted evidence: 29 actual reader/context cases, 26 resolver cases, 92 derivative/
  presentation cases (22 new), and 187 integrity/transport cases. Windows offscreen
  renders with bundled fonts were visually inspected at 1300×850; the new-version
  notice leaves the selected passage and unsaved note visible. Local ignored previews:
  `build/managed-reader-verified.png`, `build/managed-reader-new-version.png`.
- Full check: **2,031 Python tests passed** in 654.48 seconds, **18 frontend
  tests passed**, privacy scan and Ruff passed. Local ignored log:
  `build/managed-reader-full-check.log`. No Mac, phone, installed app, OS PDF
  association, real research or public service acceptance is claimed.
- Next delivery slice remains runtime research capture/enrollment, not another
  standalone transport prototype: every UI/CLI/MCP/import/AI write must participate
  before enabling user-facing sync. Full research entities/decks, snapshots/recovery,
  onboarding/status/devices/offline pins and the independent PWA remain required.


## Existing SQL writers and guarded note editing — 2026-10-26

- [ADR0007](adr/0007-research-writer-enrollment.md) now has an opt-in actual store
  boundary. Dirty scopes, portable identities, research, receipts and outbox share
  one commit, including legacy inner commits. Typed remote projection is suppressed
  from capture and retains its lifecycle markers. Ordinary unbound workspaces remain
  usable; there is no user-facing enrollment toggle yet.
- [SQL research content](sync-content.md) covers ten analysis/message/highlight
  families with per-feature/per-row identity and exact graph parents. Rich notes
  preserve kind, time and PDF anchors without weakening the existing plain contract.
  File-backed decks/JSON, conversation total order and large-content manifests remain
  separate gates; the PDF transport is not silently reused for arbitrary content.
- The actual note editor saves against its loaded version. Failure keeps the dialog,
  text and selection; a stale save retains a deduplicated local candidate and does not
  replace newer research. Delete checks the visible note before using a fresh guarded
  transaction. Repeated activation does not duplicate saves or tombstones.
- SQLite authorizer/cache, cursor scripts, raw transaction exits, savepoints and
  REPLACE identity changes have explicit regressions. A temporary transaction graph
  cache reduced the same synthetic 500-paper intake from 100.759 to 7.917 seconds,
  retaining 500 papers and 1,503 operations. This is fixture timing, not a performance
  guarantee for the owner's corpus or other devices.
- Managed research-bundle exports pack the verified PDF into the portable package;
  they do not reuse a legacy alias or search for a public URL. Curated decks/assets
  remain included. Unproven old text/figure derivatives are omitted and can be rebuilt
  locally from the PDF. Import never adopts sender sync identity or overwrites another
  paper's colliding filename. Explicit old-hash anchors cannot navigate into a newer
  PDF, including after importing into an ordinary unbound reader.
- Targeted evidence: 130 capture/note/journal/client cases, four final boundary
  regressions, 66 SQL-content/adapter cases, and 30 bundle/provenance cases passed.
  A Windows offscreen note-conflict render was inspected with bundled fonts; the draft,
  preview, status and Save/Cancel actions remain visible. This is not a live Mac test.
- Full check: **2,116 Python tests passed** in 764.79 seconds,
  **18 frontend tests and 58 mobile tests passed**, with actual JavaScript-to-Python
  HTTP interoperability, privacy scan and Ruff passing. Local ignored log:
  `build/capture-mobile-full-check.log`. No production workspace, real AI/account,
  hosted service, phone or installer acceptance is claimed. Candidate publication,
  complete AI/editor observations, file capture, baseline/backup/recovery and the
  desktop sync setup remain required before enabling enrollment or releasing v0.5.0.


## Mobile integration checkpoint — 2026-10-26

- Integrated the isolated implementation under `mobile/`; see
  [mobile contract and limits](mobile-0.5.md). Root `scripts/check.py` now requires
  mobile domain tests plus JavaScript-to-Python loopback service interoperability.
- The browser stores note changes/outbox atomically, keeps observed versions with
  drafts, preserves stale drafts, and flushes the old workspace before switching.
  Credentials remain memory-only. Session checks bind workspace/device; incoming
  research never initiates AI or automatic document downloads.
- Rich SQL content and anchored notes receive into read-only projections without
  flattening metadata. Canonical deletion suppresses older supplementary content.
  Bounded sync passes distinguish more work from completion. DTO imports never
  become writable bootstrap or advance the canonical cursor.
- Agent evidence: 58 Node tests, actual latest-core Python HTTP interoperability,
  and four isolated headless Edge checks passed. Parent inspected the 390×844 phone
  render: readable content, visible actions and no horizontal clipping. This is not
  physical-phone, public-authentication or installed-PWA acceptance.
- Integrated full-check result is recorded with the SQL writer checkpoint above.
  The app's connection form is a developer seam; hosted sign-in/pairing and deck
  reading remain required release work, not a finished public mobile product.


## Observed producers, file closure, recovery and mobile decks — 2026-10-27

- Close reading and list surveys capture their actual input and target versions
  before generation. Survey editors save against the displayed revision. Duplicate
  jobs use nonblocking, database-scoped process locks. Late results retain their
  original database binding and become candidates rather than replacing new work.
- Generation receipts and bounded recovery sidecars retain successful output when
  the original database is missing or replaced. Unbound legacy cached-text analysis
  remains usable without claiming verified PDF provenance. Enrolled or managed
  documents cannot silently use that fallback.
- Editable decks, speaker notes, guides and referenced assets have closed manifests,
  verified transfer closure and separate desired/applied versions. Existing slide
  generation and editor saves participate; incomplete incoming versions retain the
  last usable deck and local drafts. This is not complete coverage of every producer.
- Detached recovery archives reconstruct trusted schema and validate research,
  operation history, candidates and file bytes. They restore with a fresh recovery
  identity, keep old-device operations inactive and reject incomplete backups.
  Windows no-replace directory publication is exercised locally; Linux/macOS native
  publication still needs execution on those systems. Recovery UI and enrollment
  remain required.
- The PWA receives verified deck bodies and assets, retaining old content until the
  full new closure is available. Offline slide, speaker-note and source reading is
  implemented; mobile slide editing remains outside scope. Agent evidence: 74 Node
  tests, real loopback Python HTTP interoperability and five headless Edge checks.
  Phone/desktop renders were inspected. These are not physical-device acceptance.
- Targeted producer, artifact, service and recovery checks passed; the first combined
  check exposed a legacy text-preparation compatibility regression and a short-window
  layout case. Both received code fixes while retaining existing expectations. The
  full current-tree check remains the commit gate; targeted counts overlap and must
  not be added as a project-wide total.
- A separate v0.4.2 worktree contains only the question-input/layout/progress hotfix
  and the requested suggestion-browser UX. Its changes are forwarded to this branch;
  unfinished v0.5 sync code does not enter that release.
- Next required work: complete remaining producer/editor observations, reviewed
  candidate application ([ADR0011](adr/0011-retained-work-review.md)), workspace
  bootstrap/enrollment, desktop sync status/devices/storage/backup UX, offline pins,
  resume/inbox, production identity/hosting decisions and cross-device acceptance.
  The full v0.5 objective remains open. No hosted deployment or production migration
  is claimed, and the Claude trust prompt has not been bypassed.


### Follow-up audit fixes and next isolated assignment

- Artifact verification now rejects a wrong on-disk size before opening the body,
  bounds the read to the declared size plus one byte, and compares open-handle and
  path identities. Six regression cases and the related 50-case artifact group
  passed. Manifest limits must constrain allocation as well as validation.
- Detached recovery now rejects case-insensitive or sanitized PDF alias collisions
  across all retained paper IDs, including papers without an applied PDF. Windows
  reserved device names are also rejected. It fails before publishing an archive or
  restore destination and never silently renames research. Eighteen new cases and
  the 70-case recovery group passed. This is a documented migration gate, not proof
  that every legacy ID can already be restored into detached legacy filenames.
- The existing prohibition on application-wide Python event filters caught a startup
  geometry regression. The fix reuses the scoped window/focus watcher; that existing
  regression test is unchanged. Current-tree full verification is required again.
- The independent `feature/0.5-producer-completion` worktree now contains a public
  source snapshot and initial file hashes. Its assignment is actual dive/context
  generation plus manual save/editor paths, with observed inputs and retained late
  results. It must not edit the release or checkpoint worktrees. This is active
  implementation work, not completed producer coverage or a Claude execution claim.


### Four observed producers and verification fixes — 2026-10-27

- Integrated the exact owned-file delta for dive and research-context generation,
  their Data/CLI/manual editor entrypoints, and the existing close-reading/survey
  callers. All four capture the original workspace, inputs and AI connection.
  Completed outputs survive SQL publication failure; changed stale manual drafts
  remain distinct retained work. See `research-producer-completion.md`.
- The producer handoff passed 183 related regression cases, a later 60-case
  selection/worker handoff run, and 85 adoption/close-reading/survey cases. These
  sets overlap; they are not a summed project-wide test count.
- Fixed a reproducible Windows early-HTTP-rejection reset with bounded graceful
  cleanup after the response. Existing routes/authentication are unchanged. The
  related HTTP suites passed 113 cases, including 16 new regressions.
- Forward-applied the native startup teardown correction from the isolated
  v0.4.3 hotfix. Real WebEngine fast exit and native deletion now have subprocess
  coverage. The hotfix alone passed 1,163 Python/desktop and 18 frontend tests;
  its installers still require all three platform packaging gates.
- The previous combined tree completed 2,350 Python tests: 2 Windows HTTP-reset
  failures and 2,348 passes. Both failures were reproduced independently and
  fixed in code; no existing expectation or timeout was weakened. A fresh full
  check of this integrated tree remains the commit gate.

Next independent work: typed retained-work review, durable QA turn publication,
compound citation/followup/resource producers and observed highlight/question
artifacts. Workspace enrollment, complete writer coverage, desktop sync status,
device/storage/backup controls and external deployment/device acceptance remain
required. No research sync is enabled automatically by these changes.


### Retained review and durable questions — integration in progress, 2026-10-27

- The preceding `19a5b86` checkpoint passed the full check: 2,441 Python/desktop,
  18 frontend, 74 mobile tests and actual mobile-to-Python HTTP interoperability.
  This is prior-checkpoint evidence, not a full-check claim for the changes below.
- Integrated hash-verified review service/dialog files and their transaction-owned
  conflict resolution seam. Research data now opens one pinned review dialog;
  repeated activation, failure/retry, parent close and workspace change have actual
  desktop tests. The independent slice passed 214 related tests; the combined
  entry/dialog check passed 13. These overlapping selections are not additive.
- Reproduced offline same-ID parent replacement before adding local epochs to
  generation observations. Twenty new cases failed before the fix. Current
  lifecycle tests cover both paper and list replacement, metadata changes,
  caller-owned rollback and legacy recovery records: 22 passed. Legacy records
  remain readable but need explicit review rather than automatic publication.
- Integrated durable desktop QA, stable question/answer links, original source
  provenance, bundle round trips and detached recovery. The independent QA slice
  passed 126 tests; merged QA/review/question-layout adoption passed 49. Mobile
  optional-link compatibility and restart/resume UI remain in progress.
- The review service can copy/export unsupported retained formats, but does not
  yet apply compound or artifact candidates. Durable edited review drafts remain
  required. No generic SQL replay or old-device activation is enabled.
- [ADR 0012](adr/0012-bounded-reading-annotations.md) specifies canonical bounded
  highlight analyses, explanation links and research questions, with repairable
  legacy caches. It is a concrete next implementation contract, not completed
  annotation synchronization.

The next full check must cover the entire merged tree before commit or release.
Complete writer enrollment, bootstrap, workspace settings/status/devices/storage,
offline pins/resume/inbox, hosted identity and physical-device acceptance remain
part of v0.5. The external Claude trust gate has not been bypassed. Independent
internal-agent handoffs do not constitute execution by that Claude session.


### Compound producers and mobile QA integration — 2026-10-27

- Integrated 11 hash-verified compound-owned files. Actual citation, followup,
  resource and native item-editor paths capture original inputs and preserve
  manual edits; grouped SQL/outbox/receipts commit together. The independent
  combined run passed 230 tests. A later lifecycle/cache selection passed 113;
  its new 200-row fixture was corrected to make the second refresh change data,
  then passed with the original 400-operation assertion retained.
- Added typed compound receipts and sidecars to detached recovery. Completed
  research and stale/storage-failure candidates survive backup; old jobs remain
  inactive after restore. Hash-only source references fail complete-backup
  validation. The combined recovery adoption check passed 46 tests.
- Integrated mobile QA compatibility: explicit per-paper exchange pairing,
  readable orphan answers, offline persistence and inert text rendering. The
  independent mobile check passed 91 Node tests, two actual Python HTTP checks
  and six isolated Edge browser cases. Physical-phone acceptance is still open.
- The integrated content initializer now rejects a missing caller transaction
  before creating any table. New rejection/rollback tests plus existing content
  coverage passed 20 cases. No existing expectation was weakened.

This batch is ready for the mandatory full-tree check. Review draft durability,
QA restart/resume and typed candidate application, and late single-slide rewrite
retention continue in isolated worktrees; their in-progress code is not part of
this checkpoint. The original v0.5 release scope remains unchanged.


### Verified checkpoint and retained-work continuation — 2026-10-27

- The pre-continuation tree passed the complete check: 2,670 Python/desktop tests,
  18 frontend tests, 91 mobile tests and two actual Python HTTP scenarios. The
  original source hashes matched at restart. This is evidence for that snapshot,
  not for later integrations. The app was safely reopened without force-killing
  workers; the locked Windows desktop prevented native visual acceptance.
- Integrated the exact draft and single-slide handoffs (15 hash-verified files)
  and the nine-file QA resume/review patch. Shared recovery edits were composed
  contextually; baseline bytes were retained outside the public source tree.
- Edited review drafts now retain their displayed base and source across restart.
  Close/save failure leaves the text visible; concurrent saves retain separate
  variants. Detached restore archives drafts as provenance, not apply authority.
- QA restart uses stable question/answer identities and explicit selection of the
  current available AI route. Completed retained answers have typed review; merely
  opening a paper or review dialog does not resume generation.
- The actual single-slide worker retains completed output and its asset closure
  before the UI callback. A late result cannot replace a different page or paper;
  delivery retry does not call AI. Backup integration is being completed separately.
- The first merged review/draft/QA/slide/recovery selection passed 102 tests.
  Unexpected answer-publication exceptions remain a known restart-retention gate
  until the supplemental fix and merged full check pass. Existing tests were not
  weakened. No commit, release, production migration or hosted deployment occurred.

The isolated annotation worktree now exercises an observed question producer with
captured SQL inputs, verified PDF, original AI route and durable publication. Its
26 producer/legacy cases and an actual two-desktop -> HTTP -> mobile offline test
passed. This code is not yet in the canonical checkout. Actual desktop entrypoints,
legacy-cache adoption/deletion, grouped highlights and explanation links still need
integration; contract fixtures do not prove complete annotation enrollment.

Remaining release scope is unchanged: complete all writers and source-file closure,
review every supported retained format, bootstrap/enroll safely, expose workspace
status/devices/storage/backup/offline pins/resume/inbox, and run the hosted/private
access and physical-device acceptance gates. The external Claude session still
requires its owner-controlled trust step; internal agents are not that session.

### Question composer integration regression - 2026-10-27

The integrated retained-work/QA delivery check passed privacy and Ruff, then
reported 2,756 passing Python cases and two failing short-window layout cases.
Adding a separate retained-QA action row raised the desktop minimum height above
the existing 560-pixel regression boundary. The action now shares the suggestion
toolbar; the original composer-visibility assertions remain unchanged.

A 24-case focused run passes, including both original failing font/layout cases
and added recovery-button reachability. A fresh full check is required before
calling this snapshot verified or restarting the development app. Independent
compound-review, slide-recovery, workspace UI and annotation work stays staged
outside this checkout until this integration boundary is verified.

## Workspace/recovery integration checkpoint - 2026-10-27

The prior root snapshot passed the complete check with 2,758 Python/desktop cases,
18 frontend cases, 91 mobile cases and two actual HTTP scenarios. The question
composer regression was corrected without relaxing either small-window assertion;
the verified app was safely restarted with its position/draft-preserving protocol.

The next integration adds 22 files from four independently frozen layers:

- Compound candidate review previews grouped citation/follow-up/resource changes,
  validates displayed versions and applies the group atomically with its receipt.
  Restoration is decided per item; archived inputs retain their actual provenance.
- Slide recovery archives bounded typed receipts and verified asset closures.
  Restored records remain inactive provenance rather than resumable old jobs.
- Existing source PDFs can satisfy archive closure from explicit trusted workspace
  PDF roots by exact hash and bounded validation, without modifying live research
  or creating current-document operations. Missing/corrupt files still fail closed.
- The desktop workspace dialog reports location, pending/conflict/attachment state
  and provides complete backup, preview and restore to a new directory. It guards
  repeated actions, cancellation, workspace changes and concurrent writes. It does
  not pretend that restored data is already enrolled or connected.

An exact root-derived shadow with all four layers passed 168 selected tests and
Ruff. The canonical source has been hash-checked against that shadow, preserving
the small-window fix and all prior uncommitted work. Only added CRLF line endings
were normalized; logical lines were unchanged. The merged full check is required
before calling this new snapshot verified, committing or restarting it.

Independent work continues on normal restored-deck reading/edit adoption, explicit
desktop sync sessions/onboarding, and workspace-owned annotation producers. The
annotation tree has canonical read/deletion authority, actual question generation
and a no-AI legacy adoption operation with scoped tests; its desktop adoption entry
and highlight/link/manual-mark writers are still unfinished. None of that isolated
annotation code is implicitly covered by this root check.

External gates remain unchanged: production identity/hosting/encryption decisions,
the physical Windows/Mac/phone journey, cross-platform packaged acceptance and
public release approval. No real user research, AI account, hosted service or
credential was exercised by the fixture checks.


## Restored reader and explicit sync connection integration - 2026-10-27

The preceding 626-file canonical snapshot passed the complete check: 2,884
Python/desktop cases, 18 frontend cases, 91 mobile cases and two actual HTTP
scenarios. Its safe restart preserved the workspace; process health was checked,
but native visual acceptance remains open.

This next integration composes 27 owned files from frozen restored-reader and
connection layers. Shared files are patched against the verified baseline rather
than replaced from an older branch.

- Restored saved decks open in the ordinary canvas, HTML and native PDF exporters
  using their retained exact PNG/evidence closure. Unknown PDF provenance stays
  unknown. Original archived decks remain protected; creating an editable local
  copy is still a separate unfinished requirement.
- Workspace settings expose an explicit authenticated connection, bounded manual
  sync and new-device join to a separate directory. Login alone does not enroll or
  upload existing research. Device credentials stay in memory, outside backups.
- A completed restore/join can open its own app window. The original window,
  drafts and workspace remain open. Startup validates the selected database before
  migrations; provider secrets are not forwarded. Missing editable-copy capability
  rejects that focus request before launching.
- A picker defect discovered in integration is fixed: its destination is validated
  after folder/name selection. Six added action cases cover successful publication,
  folder/name/confirmation cancellation, blank/invalid names and repeated activation.
  Existing tests and assertions were preserved.

The isolated combined selection passed: 148 passed in 290.76s (0:04:50).
Ruff passed. The canonical merged full check is now required; this checkpoint does
not claim release readiness or native/packaged acceptance. The self-hosted reference
connection still requires administrator-issued workspace/device credentials.

Parallel annotation work remains isolated: canonical readers, atomic highlight
publication, a two-stage highlight/link workflow and observed manual marks have
focused coverage (150, 56 and 135 cases in overlapping selections; 119 mobile cases).
Typed grouped highlight review and actual material/deep-reading entrypoints remain
unfinished. Do not merge the annotation registry alone or apply only its analysis
row through generic review. The workers stopped at provider quota; the primary
session owns these explicit remaining tasks and preserved their handoff manifests.

Unchanged release gates include complete writer/file enrollment, editable recovery
copies and their backup closure, secure device issuance/revocation, compatibility
guards, production identity/hosting and the Windows/Mac/phone acceptance journey.
No real research upload, paid AI call, credential change or release was performed.


## Checkpoint for incoming Claude merges — 2026-10-27

The restored-reader/explicit-connection integration passed the complete local
check with 2,953 Python/desktop tests. The subsequent diagnostics/support change
passed privacy, Ruff, 2,981 Python/desktop tests, 18 frontend tests, 91 mobile tests
and two actual HTTP scenarios. Its 28 new cases use fixture data; no real account,
research upload or native Mac/Linux upgrade was exercised. The support UI was
rendered with bundled fonts and inspected, and the desktop restarted safely.

This checkpoint preserves all integrated retained-work, review, QA, workspace,
restored-reader and diagnostic work currently in `feature/0.5-sync-foundation`.
Run `scripts/check.py` again on the final checkpoint tree before committing.
The independently staged annotation and editable-copy worktrees remain outside
this commit; their unfinished status and prior handoffs still apply.

Incoming merges, to be performed by Claude after this checkpoint:

- `hotfix/0.4.4` (`1f79466`, `f13599c`): RichView note-card opening, note/Q&A
  cards spanning the column, and Gemini access through an AI Studio key.
- `feature/drive-share` (`ed2d52c`): list-package sharing through the sharer's own
  Google Drive with `drive.file`, resumable upload and copied link.

These commits are not implicitly merged by the checkpoint. When resolving shared
desktop/research changes, preserve both the incoming fixes and the retained-work,
source/version and active-worker guards. Re-run the full check after merging;
neither this checkpoint nor an earlier passing suite verifies the merged result.

README `90f8c60` is already an ancestor. Its per-list reading goals, claim-level
sources and lineage explanations are now explicit planned roadmap scope.
The next Claude list-recency task follows
[the local-only recency/shared-order decision](list-recency-handoff.md): local
visit timestamps and sort mode; existing `workspace_list_order` journal for a
dragged custom order. Do not extend the membership-scoped `reading_state` payload.

### Update/release automation follow-up (not implemented here)

The owner requested a persistent bottom-right version indicator, timely update
checks, optional automatic download/apply, and Windows/Mac release acceptance.
Review confirmed the existing release banner, user-initiated installer path,
hourly polling with daily successful-result cache, and draft-release build matrix.
The current Mac artifact selector is ARM64-only; installers remain unsigned.

Next implementation should add an immediate check and bounded shorter cache,
explicit per-device update policy, verified platform/architecture-matched downloads,
safe application shutdown and recoverable installer failure. Keep update settings
and account credentials outside research synchronization. Do not describe hashes
alone as publisher signing or claim a Windows fixture validates native Mac upgrade.

Use the same synthetic research fixture for both native builds and the owner's
devices. Record candidate version/commit and artifact hashes with startup, import,
read, edit, export, diagnostics and previous-version upgrade results. Produce draft
artifacts first; publish only after the owner has accepted the same Windows/Mac
candidates. Automated tests must not exercise real AI accounts or private research.
The existing `verify_built_app.py` harness and CI matrix are starting points, not
proof that this new automation is complete. No updater implementation, remote CI
run, signing setup, native-device enrollment or release was performed in this
planning-only follow-up.
