# v0.5 delivery status and next integration gates

Updated: 2026-10-30. Working branch: `feature/0.5-sync-foundation`.
This is the current integration map. Historical checkpoint sections remain in
`implementation-0.5.0.md`; their old pending descriptions are not a current audit.
No v0.5 public release or production research enrollment has been approved.

## Latest verified checkpoint

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

## Requirement-to-evidence map

| Requirement | Current authoritative implementation/evidence | Still required |
|---|---|---|
| Shared research operations | `local_operations.py`, UI adapters, JSON CLI/MCP; `test_local_integration.py`, capture/compound tests | Complete remaining observed producers and file capture; external raw SQLite writes are not supported |
| Existing research starts sync | `SyncSession` deliberately rejects unbound databases; `test_unbound_nonempty_workspace_cannot_silently_enroll` | Explicit copy-and-enroll workflow, complete source inventory, maintenance locking and baseline/file closure |
| New device joins safely | `sync_bootstrap.join`, guarded sessions and no-replace publication; workspace sync/bootstrap fixtures | Compatibility, authority generation/retention and secure production device issuance |
| Offline desktop changes converge | Journal/client/service, guarded capture, typed research projections; two-workspace/actual HTTP fixtures | Complete writer enrollment and Windows/Mac acceptance with independently edited copies |
| Safe conflicts and retained AI work | Generation/chat/compound observations, grouped review and durable edited drafts | Annotation analysis + located-mark grouped review; editable recovered copies with source closure |
| Verified attachments | Managed PDFs and editable-deck manifests, blobs, resumable transfers and strict source checks | Remaining annotation/derived asset producers, selective download execution and retention/pinning lifecycle |
| Desktop workspace UX | Status, backup, restore, manual connection/join, independent window opening | Initial enrollment UX, device management, complete offline preparation and resume UX |
| Private mobile reader | Independent PWA, 91 domain cases and actual Python HTTP scenarios at f7155c0 | Physical iPhone/Android offline restart, storage pressure, IME, accessibility and hosted login acceptance |
| Recovery preserves work | Detached backups, legacy source/deck recovery, read-only restored-reader adapters | Editable recovery adoption and every annotation/file closure; do not reactivate old device identities |
| Professional paper reading | f7155c0 task drafting, 3155 Python + 18 frontend + 91 mobile cases and 2 HTTP scenarios | Per-list goals, validated claim-level sources, lineage and source audit; templates are not validation |
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
local-merge commit. Only detection is currently being integrated. Independent
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
