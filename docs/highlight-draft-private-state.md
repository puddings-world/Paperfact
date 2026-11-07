# Typed highlight private state

Status: 2026-11-02, `0.5.0.dev`, isolated integration candidate, unreleased.
Backend receiver selection, private variants/restart and independent recovery are
implemented. Exact-original verification and independent reading are also available
as backend operations; see [their contract](highlight-source-verification.md).
Confirmed [atomic backend Apply](highlight-draft-application.md) is connected
separately; desktop controls and CLI/MCP tools for this type are **not connected**.
A private save or source check grants no publication.

## Shared operation and storage boundary

`ResearchReview` delegates four bounded operations to `highlight_draft_resume`:

| Operation | Observable result |
| --- | --- |
| `highlight_draft_targets(preview, after, limit)` | Bounded enrolled-paper choices; a remote analysis is restricted to its original portable receiver. |
| `select_highlight_draft(preview, target_id, body=None)` | A sealed private preview and closed editable body, preserving explicit unsaved content. |
| `save_highlight_draft(preview, body, request_id, draft_id, revision)` | Stable draft identity, compare-and-save revision and transactional retry-safe private result. |
| `load_highlight_draft(identity, draft_id=...)` | Original body/base after restart; verification-required, stale, foreign, decided or corrupt status as appropriate. |

No new provider login, model, remote service, public tool or alternative draft table
is involved. The existing `research_review_drafts` journal owns bounds, revisions,
rollback, variants and history. A typed body may use220KiB; the generic200KiB limit
does not truncate it. A caller must retain a stable variant identity across retries.

## Captured scope and changes

- Capture the actual native database identity, enrolled binding, local/portable paper,
  parent epoch, complete current analysis and its graph observation. These are fresh
  receiver observations, not authority recovered from a sender path.
- Capture the current AI mark rows, hidden choices, known-analysis flag and graph
  tokens including tombstones. Retain a bounded digest/count of all manual rows as
  a change observation, not replayable manual content or source authority.
- Aggregate stored-byte and row bounds precede full mark allocation. JSON uses closed
  fields and strict duplicate/nonfinite checks. Every stored private snapshot is
  validated during live load and history wrapping, including source declarations.
- Retained generation/owned sidecar inputs use their typed receipts; archived typed
  highlight drafts retain their closed body/baseline. Remote input must be a whole
  analysis put. A lone AI-mark operation is not an analysis or grouped Apply grant.
- Remote drafts capture the actual unresolved conflict, canonical comparison and
  causal state. Offline save/restart uses only the local workspace. Another update
  makes the original private observation stale without replacing human text.
- A changed analysis, AI hide/delete choice, manual mark set, parent, retained record,
  graph or conflict prevents treating the old base as current. An unrelated plain
  note does not rebase the draft. Explicit reselection retains supplied human fields.

Generic `decide` rejects this type, including Keep. Restoring a draft never enables
Apply. Closing before save admission rejects new work; an admitted private save may
drain into its pinned original database. Native replacement refuses before connecting
to the new file. Older draft and receipt formats remain unchanged.

## Independent recovery

The maintained history codec enumerates the retained/current/original and observed
mark/document source hashes without opening historical owner paths. Normal backup,
detached read-only restore and editable adoption retain the body/source declaration.
The old folder can be unavailable. A recovered body requires explicit fresh receiver
selection; new saves use the receiver's native identity/binding and still cannot Apply.
The shared private-state journal is not sent as a new research operation to peers.

Original A can be independently read/verified while B stays current. The separate
atomic application now handles explicit restoration and source+analysis+marks+outbox+
decision/private receipts. Actual remote resolution, recovery/offline-peer/second
backup data journeys have focused evidence. Native editing, tools and complete
derived-link audit still prevent claiming the full feature. Initial mobile scope
remains reading/highlight display and text notes, not mobile highlight editing.

[Executed actions](testing/highlight-private-scenarios.md) ·
[Remaining integration contract](highlight-draft-continuation.md) · [Release scope](roadmap-0.5.0.md)
