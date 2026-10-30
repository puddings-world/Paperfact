# v0.5 delivery status and next integration gates

Updated: 2026-10-30. Working branch: `feature/0.5-sync-foundation`.
This is the current integration map. Historical checkpoint sections remain in
`implementation-0.5.0.md`; their old pending descriptions are not a current audit.
No v0.5 public release or production research enrollment has been approved.

## Prior verified checkpoint

The offline-verification dialog/entry and read-only duplicate detector passed the
complete gate on a frozen 615-file input set: **3,227 Python/desktop cases,
18 frontend cases, 91 mobile cases and two actual Python HTTP scenarios**.
Privacy scanning and Ruff passed. Runtime: 2,260.2 seconds. No source inputs
changed during the gate. Evidence remains in ignored
`build/offline-integration-full.log` and `build/offline-integration-inputs.json`.

Offline verification checks selected actual current PDF/deck bytes with a bounded
budget. Pins are device-local intent, not an implemented eviction policy.
Selective downloads, annotation integration and per-list goals are separate
isolated candidates; their focused passes are not this full-gate result.
No installed daily app, production research, public release or physical Mac/phone
acceptance was exercised by this checkpoint.

## Current combined candidate

The pending candidate combines source-pinned annotations, selected downloads,
per-list purposes, reference links, membership-bound pins, supported-subset
first-enrollment preparation and bounded professional evidence validation.
These changes have focused fixture evidence; the combined full gate is pending.

- Analysis and located PDF marks publish together. Complete remote annotation
  analysis can be reviewed only against its exact registered source; individual,
  incomplete or unlocatable annotation conflicts remain keep/export-only.
- Explicit offline downloads fetch selected current attachments through the
  in-memory connection. Separate resumable verification hashes actual bytes;
  progress counts verified objects/bytes, not estimated completion time.
- Per-list purposes are user-owned observed edits, shared, synchronized and shown
  separately from generated analysis on mobile. Rolled-back changes do not refresh
  displays. Reference links preserve both paper incarnations; pins also depend on
  the current list membership, preventing removal/re-add from reviving old flags.
- Field-neutral deep dives distinguish study design, evidence, interpretation and
  missing details. Recorded citation links do not establish influence or agreement.
  Existing saved dives are retained.
- Claim extraction captures one source and AI route, preserves old results on
  failure, and publishes through observed edits. Saved-first desktop cards and PWA
  content separate quote location from proposed semantic support. Restoration is
  explicit; changing the current PDF never relabels original-version evidence.
- Continuous desktop sync is explicitly enabled per app session after connection
  verification. Shared bounded workers defer busy work, retry offline with backoff
  and pause on identity/protocol/storage failures. Login alone never uploads data.
  Secure remembered login and production enrollment remain open.
- Maintenance fixes preserve partial citation work, keep legacy completion unknown,
  move source-status checks off Qt, respect manual-only scheduling, serialize
  preferences and initialize the first WebEngine view correctly.
- Extended research packages declare capabilities and reject unsupported content
  or lost deletion knowledge; legacy packages without extensions remain readable.
- Enrollment preparation creates a supported isolated copy and inspected backup;
  it reports runtime enrollment incomplete and refuses unsupported legacy data or
  assets. Reference links and valid per-list pins are covered; queue/log/history,
  orphan flags and unmigrated decks/assets still block this limited workflow.
- Mac packaging explicitly forbids background-only app flags and includes a native
  foreground gate. Windows fixture checks do not prove Mac foreground behavior.

Focused selections include 166 combined claim/pin/goal cases, 88 polished desktop
claim cases, 85 continuous-sync/UI cases, 23 controller/status cases, 155 maintenance
cases, 96 resumable-verification cases, 52 remote-review cases and 20 packaging
cases. These overlap; do not sum them. The merged PWA passed 184 cases and three
actual Python HTTP scenarios before the separate original-source follow-on.

Two earlier full attempts exposed regressions: 451 passed / one failed for
unconditional annotation-trigger replacement, then 718 passed / one failed for a
pin cleanup trigger installed without its optional base tables. Both underlying
initializers were repaired; original rollback assertions remain unchanged. The
optional-schema selection passed 43 cases. Another Windows file-proof boundary
was reproduced: same-size mutation with restored mtime could reuse a cached
proof. A timestamp-only repair exposed a same-clock-tick collision; the unchanged test
now passes using a per-file revision as well. The focused revision selection
passed 44 cases. A frozen combined full gate is required before committing; its
final result belongs in the checkpoint commit and ignored run ledger. A later
complete gate reached 1,653 passed before a legacy material fixture lacked a
loaded source owner. Actual owner/load fixtures now retain every original
stale-result and failure assertion, with a separate unbound refusal case. The
affected seven-file selection passed 97 cases; no source guard was removed.

Historical PDF transfer, private provenance archive, selected offline closure
and distinct mobile source access are now integrated. Their merged selection
passed 144 Python cases and 198 mobile cases, with four actual authenticated HTTP
runners (six reported acceptance checkpoints). This is focused evidence, not a
whole-project gate or complete enrollment claim. The portable original-version
desktop viewer and read-only missing-store resolver are integrated: their merged
selections passed 108 and 44 cases respectively. Private source archives now
initialize lazily; the unchanged fresh-database/recovery/enrollment selection
passed 112 cases. These selections overlap. Current source publishing does not
activate a reader or replace the primary PDF.

Already-enrolled package import is integrated through typed graph operations,
exact source/deck byte validation and one caller-owned transaction. It rejects
unsupported scopes and ambiguous updated-package identities; the desktop mapping
preview remains required. A native Windows archive-version JSON round-trip
regression was reproduced and repaired without weakening stale-file rejection.
The merged import/source/bundle selection passed 86 cases (121.87s). Existing-job history migration
and unbound original ownership remain isolated follow-ons.

See `remote-annotation-review.md`, `workspace-offline-verification.md`,
`list-reading-goals.md`, `list-pins.md`, `reference-edges.md` and
`workspace-enrollment.md`. Physical devices and production hosting remain open.

## Requirement-to-evidence map

| Requirement | Current authoritative implementation/evidence | Still required |
|---|---|---|
| Shared research operations | `local_operations.py`, UI adapters, JSON CLI/MCP; `test_local_integration.py`, capture/compound tests | Complete remaining observed producers and file capture; external raw SQLite writes are not supported |
| Existing research starts sync | `SyncSession` deliberately rejects unbound databases; `test_unbound_nonempty_workspace_cannot_silently_enroll` | Explicit copy-and-enroll workflow, complete source inventory, maintenance locking and baseline/file closure |
| New device joins safely | `sync_bootstrap.join`, guarded sessions and no-replace publication; workspace sync/bootstrap fixtures | Compatibility, authority generation/retention and secure production device issuance |
| Offline desktop changes converge | Journal/client/service, guarded capture, typed research projections; two-workspace/actual HTTP fixtures | Complete writer enrollment and Windows/Mac acceptance with independently edited copies |
| Safe conflicts and retained AI work | Generation/chat/compound observations, grouped review and durable edited drafts | Complete source-aware review for every content type; editable recovered copies with source closure |
| Verified attachments | Managed PDFs and editable-deck manifests, blobs, resumable transfers and strict source checks | Remaining derived asset producers and the retention/eviction lifecycle |
| Desktop workspace UX | Status, backup, restore, manual connection/join and opt-in continuous synchronization | Initial enrollment UX, secure remembered connection, device management and resume UX |
| Private mobile reader | Independent PWA, 91 domain cases and actual Python HTTP scenarios at f7155c0 | Physical iPhone/Android offline restart, storage pressure, IME, accessibility and hosted login acceptance |
| Recovery preserves work | Detached backups, legacy source/deck recovery, read-only restored-reader adapters | Editable recovery adoption and every annotation/file closure; do not reactivate old device identities |
| Professional paper reading | Task drafting, per-list goals and bounded source-aware claim cards in the pending candidate | Unbound original ownership, grounded lineage, full audit and device acceptance; source location is not semantic proof |
| Duplicate identity review | Read-only detector from df3392c, complete frozen gate passed | Reviewed portable-ID alias operation and nonempty-device join; local merge 7a25a0d is not safe to expose |
| Release and device evidence | Current 0.4 maintenance remains independent | Frozen 0.5 installers, preservation/upgrade checks, owner Windows/Mac and phone journey |

## Worktree reconciliation

Read-only manifest comparisons found that producer, compound, recovered-reader,
review and older mobile layers are largely already integrated or superseded by
newer canonical protections. Never copy an entire dirty worktree back over the
canonical branch simply because its files appear modified relative to its old HEAD.

`Paperfact-annotations/build/annotations-progress.json` explicitly records an
isolated incomplete layer. Its frozen hashes match its current worktree, but it
is not a completed integration. Typed grouped annotation review, real producer/UI
wiring, backup/source closure and merged acceptance remain open. Retain all work.

The clean identity branch contains a separable read-only detection commit and a
local-merge commit. Detection is included in verified checkpoint `63732ee`; merging remains blocked. Independent
synthetic repros found that the merge commit:

- Relocates decks/question/highlight caches without updating embedded paper ownership.
- Can relabel hashless anchors onto a different PDF.
- Does not bind application to the displayed preview (an intervening note changes the merge).
- Moves files before SQL commit; a process exit can leave the original DB pointing
  to missing files with no durable file-move recovery journal.

Required merge repair is document-aware identity migration, sealed preview/apply,
durable file publication/recovery and portable alias convergence. Detection's
`same`/`likely` classifications remain proposals, never automatic merge authority.

## Independent coordination

A real local Claude Code session completed a read-only first-enrollment review
using only Read/Grep/Glob tools. Its report proposed an independent staged copy,
explicit coverage checks and reuse of capture/bootstrap primitives. Suggestions
were checked against source: some assumed missing chat/highlight adapters already
exist, so the report is input to review, not an implementation or acceptance result.
No trust bypass, credential reading, research upload or shell tool was granted.
The ignored task/result files remain under `build/claude-enrollment-review-*`.

Internal independent reviews corroborated the first-enrollment gap and reproduced
the identity hazards above. Separate owned files are now used for offline intent
and verification, and for its desktop dialog, while the parent owns main-window
integration. Each candidate needs merged tests before commit.

## External gates kept explicit

- Select/operator-approve the hosted identity/storage service, deployment region,
  budget, incident/retention policy, device issuance/revocation and recovery flow.
- Review remote HTTPS, authentication, cross-user isolation and rollback generation.
- Choose and document an encryption threat model; no end-to-end-encryption claim yet.
- Run the complete owner-device Windows/Mac/offline-phone journey on the frozen
  installers and hosted pilot. Fixture passes do not replace that evidence.
- Publish only after owner acceptance. Candidate rebuilds use the same planned
  version and distinct commit/build identity; test repairs do not require new versions.
