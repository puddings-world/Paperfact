# Saved review drafts: remaining v0.5 acceptance contract

Active acceptance contract, 2026-11-01. Private preservation, receiver text editing/application and a separate
read-only original viewer have selected fixture coverage. Typed note continuation
now has local conflict/adoption/peer/re-backup and source-boundary coverage; remaining
note conditions, structured drafts and the full release journey remain incomplete. This contract is not completion evidence.
The full v0.5 roadmap remains in scope. This handoff supports a future available
Claude session; no new session has been assigned or claimed to be running.

## Researcher journey

1. Generate a real retained proposal using PDF A and explicitly select a target.
2. Save two different edited drafts, including two variants sharing the same
   application request ID. Restart and verify both bodies and displayed bases.
3. Prepare a sync copy with current PDF B, preserve private drafts and their
   required A, create a complete backup and restore without the old folder.
4. Inspect either draft as readable text. Its old database path, native identity,
   binding, observation and parent epoch are historical evidence, never authority.
5. Explicitly select the receiver's current target. Show old A/current B and the
   destination. Verify A using independent receiver-owned bytes. Do not borrow
   a claim/deck/material permission or substitute B merely because it is current.
6. Capture the current target, database identity, binding, parent incarnation and
   source proof at preparation. Apply only that displayed base after explicit
   confirmation. A changed target/source/workspace keeps the draft and refuses
   application; it must not silently recapture a new base or run AI.
7. Publish the verified source and accepted manual research, outbox and new review
   receipt atomically. Keep the original archived variant immutable. Retry creates
   neither duplicate research nor another accepted receipt. Export and re-backup
   retain the readable text, actual original and provenance.

## Actual maintained formats and boundaries

- `research_review_drafts` has eleven columns: draft_id, origin, origin_id,
  owner_json, preview_json, body, request_id, revision, updated_at, save_order,
  fingerprint. Validate bounded duplicate-key-safe nested JSON before the runtime
  validator. Preserve original JSON strings and all variants. Enrollment's generic
  `(protocol, request_id)` key must use draft_id for drafts; shared request IDs
  are legal and must not cause deduplication or rejection of a second variant.
- Snapshot fields are origin/id/record_hash/original/current/retained/source_hash/
  apply/editable/reason/expected/scope/target/requires_confirmation/parent_token/
  parent_row. Runtime generations and remote conflicts have distinct formats;
  validate actual SQL snapshots, observations and operations, not arbitrary maps.
- Archives and source declarations alone do not implement inspection, editable
  resumption, source-aware authorization or fresh target confirmation. Keep the
  original full-flow acceptance red until those real user outcomes work.
- A generic text-body route must not bypass typed claim/highlight/deck review.
  Unknown protocols remain refused; don't reinterpret structured scientific JSON
  as free text merely to make an archive pass.
- `research_review_receipts` is now independently supported for metadata/source
  preservation. It does not imply support for its origin's separate candidate
  tables, nor does it install live historical decision or job tables.
- `prepare_source` does bounded verification/staging off the GUI and outside the
  write transaction; `publish_source_in` can participate in the caller's atomic
  save. A process-only PreparedSource must never be serialized into draft JSON.
  Reopening needs a new verification of the retained displayed base, not implicit
  rebasing. Unpublished CAS bytes may remain cache; they grant no ownership.
- Historical-only originals are available under the new copy's trusted PDF
  history roots. A digest is identity, not permission or semantic support. Do not
  follow observed old context paths or write to the owner's daily database.
- Existing raw recovery intentionally preserves some opaque legacy capture
  candidates. Do not harden that existing backup contract incidentally. A strict
  new adoption validator may refuse unsafe formats while raw backup stays lossless.

## Required behavior controls

Use genuine producers/readers and disposable SQLite/PDF fixtures. Cover two draft
variants with a shared request ID; exact A/current B; no old-folder access; normal
edit/application; empty or removed target; cancellation and source failure/retry;
duplicate clicks; two-window CAS; changed paper/account/workspace/source while
pending; parent deletion/recreation; closed view while a worker is admitted;
rollback after source publication; restarted verification; typed source-aware
unsupported content; private data absent from public packages and sync payloads.
Assert visible/saved bodies, original bytes, provenance, outbox and receipts.
Use no real account login or paid AI. Preserve all old test assertions. Run focused
and interacting gates, then the default complete check before commit/release.

## Delivery gates still outside this handoff

Complete all other writers/history/candidates, lineage and durable research
outputs; safely integrate the authoritative worktree; green full check; matching
installers; deployed sync identity/service and operator decisions; actual Windows,
Apple Silicon Mac and phone offline/reconnect/conflict/recovery acceptance.

## Implemented reader checkpoint (2026-11-01)

Prepared-copy and independent-recovery reading now include archive wrappers and
raw direct-backup drafts, exact variant identities, byte/record bounds and
bilingual native copy/export/cancel/close controls. This fulfills the read-only
inspection slice; steps5–7 above remain required before resumption is complete.


## Receiver text checkpoint (2026-11-01)

Fresh target selection, private edit persistence/restart, worker source verification,
confirmed atomic application and re-backup now have selected evidence for the five
plain-text families. See [actual scenarios](testing/resumed-draft-scenarios.md).
This does not close the whole contract: typed remote notes and structured content,
all adoption/peer journeys, remaining
writers/histories, full check, deployment and installed-device gates remain open.
Do not label byte verification as scientific support or a metadata declaration as
permission to reopen a historical path. The original full roadmap remains required.


## Text-original viewer checkpoint

The resumed text's exact A now opens read-only under its own source capability,
with current B and private edits retained. Native fences keep SQL/PDF/hash/provider
work off GUI admission; worker revalidation retains the original displayed base.
See [viewer actions and screenshots](testing/draft-original-scenarios.md).
The [typed-note continuation](review-note-resumption.md) now has selected local
evidence, including source location and owner continuity. Its remaining conditions
and the full structured/release journey remain required; earlier checkpoints above
are historical scope statements.

## Structured claim content foundation (2026-11-02)

A closed editable proposal format and deterministic exact-original revision core
now have 22 new actual-PDF cases, passing with 91 existing safeguards. This is
internal content processing, not an exposed editor or durable typed resumption.
Fresh receiver observations, private structured draft history, atomic source/claim
application, UI and the independent recovery/peer journey remain required.
[Contract, exact local evidence and remaining integration](claim-draft-resumption.md).
Generic claim-as-text refusal remains unchanged.

## Structured claim private backend (2026-11-02)

Explicit receiver observation, closed structured private saves, restart and
independent backup/adoption now have selected backend evidence. A detached
preview no longer initializes runtime lifecycle tables. The interacting group
passes93 cases,22new. Source verification, atomic publication and the native claim
form remain unimplemented; sidecar/remote lanes and the full peer/device journey
remain required. [Actual private actions and limits](testing/claim-draft-private-state-scenarios.md).

## Structured claim source application (2026-11-02)

The preceding sections retain their original historical scope. Exact-A verification,
confirmed source/claim/outbox/receipt publication, rollback/retry and independent
recovery now have selected backend evidence. A real local peer receives the accepted
claim and PDFs, adds a note offline, restarts, returns it and passes another backup.
The current interacting selection passes231 cases,22new, in 392.92s.
Native claim editing, claim CLI/MCP adapters, actual sidecar/remote editing and
offline claim-edit convergence remain required, along with the full device/release gates.
[Human actions/results](testing/claim-draft-application-scenarios.md) ·
[Operation contract](claim-draft-application.md).

## Native claim editor candidate (2026-11-02)

The preceding backend-only scope is historical. The isolated UI now connects
field-based claim revisions, private variants, source verification, explicit Apply,
background typing-safe saves and owned close/cancel to the same operations.
Actual English/Traditional Chinese Qt and interacting old views pass60 cases,
20new. Native replacement, independent recovered editing and A inspection with B
retained are included. Claim-specific CLI/MCP, broader history and offline claim-edit
journeys plus full integration/device/release gates remain required.
[Actions and screenshots](testing/claim-draft-application-scenarios.md).
