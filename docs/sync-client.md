# Explicit sync client and conflict resolution

Status: isolated v0.5.0 implementation, 2026-10-26. `SyncClient` uses an explicit
`Journal` and trusted research writer; no app startup hook, timer, HTTP policy or
desktop conflict UI is installed by this module.

## Durable operations

- `new_operation(kind, entity_id, payload, ...)` creates a bounded list/note envelope.
  Retain it when retrying the same action; `save(operation)` writes research and
  its outgoing operation atomically. A changed payload using the same ID fails.
- `sync_once(transport, token, limit=100)` pushes a bounded batch, then pulls a
  contiguous event batch. Concurrent calls on the same instance return `busy`.
  The supplied transport owns authentication and network policy.
- Acknowledged edits remain causal predecessors until their server events arrive
  in the contiguous inbox. Partial pull pages cannot replace a newer acknowledged
  local edit with an older canonical version. Restart preserves this boundary.
- `receive(events)` atomically stores history, updates canonical heads, materializes
  research and advances the cursor. Failure rolls all of these back. A conflict
  cannot introduce a head that was never accepted earlier in the stream.
- Canonical absence is materialized through a local-only delete callback. The
  rejected incoming creation stays in conflict history; no synthetic delete is
  uploaded. Unsaved editor drafts remain a separate desktop integration concern.

`status()` distinguishes upload `pending`, `awaiting_receipts`, unapplied canonical
heads (`deferred`), unresolved `conflicts`, and the contiguous `cursor`. Upload
success alone does not imply that the client has received the canonical outcome.
`history(conflicts_only=True)` retains **all** historical conflicts, including
resolved ones; the unresolved status count intentionally differs from that length.

## Explicit resolution

```python
result = client.resolve_conflict(
    conflict_sequence,
    choice="incoming",             # or "canonical"
    payload=None,                  # optionally edit the chosen record's payload
    operation_id="caller-retry-id",
)
```

- `incoming` selects the conflicted operation's content/action. `canonical` selects
  the **current** canonical head, including deletion or absence. An optional payload
  overrides content while retaining the selected action; a delete requires `{}`.
- The helper creates a new operation against the current head with optional
  `resolution_of` naming the original conflicting operation. It preserves all old
  versions. Ordinary edits never implicitly mark a conflict resolved.
- A private `research_resolution_intents` row records the logical request and
  immutable generated operation in the same transaction as research and the outbox.
  This is local control data, not a research payload or a credential store.
- Reusing `operation_id` with the same request returns the original receipt, even
  after acknowledgment/restart. A changed choice or payload using that ID fails.
  Without an ID, the same pending request reuses its intent; a different pending
  resolution is rejected. Callers should retain returned `operation_id` and disable
  repeated UI activation while an action is running.
- Outstanding edits to that entity must synchronize first. The helper rechecks the
  canonical head and conflict state inside the save transaction, so a concurrent
  update cannot be overwritten using an obsolete resolution preview.
- Only an **accepted resolution received in the contiguous event stream** marks
  the original conflict resolved. A stale resolution is itself a preserved conflict.
  When two resolutions race, one may resolve the original while the other becomes
  a new unresolved conflict. Every device derives the same resolution state from
  accepted events; no local-only clearing of the conflict count is used.

The optional `resolution_of` field extends the unreleased private version-1
envelope. The service requires a prior conflict in the same workspace and entity;
the client checks this relationship again when applying events. This is not a
compatibility promise for deployed clients; wire versioning remains a release gate.

## Verification and limits

Tests use synthetic workspace pairs and the local reference service. They cover
offline edits, duplicate transfer, acknowledgment/pull interruption, partial pages,
preserved conflicts, explicit incoming/canonical/custom resolution, concurrent
resolution, failed writes, restart, malformed references and receipt validation.
No model is invoked and no provider credential travels in an operation.

Desktop draft/focus behavior, all research entity adapters, hosted authentication,
real networking, mobile storage and real-device acceptance remain separate work.


## Version-2 dependency-aware graph

The explicit graph builder is separate from the legacy version-1 helper:

```python
operation = client.new_graph_operation(
    "note", portable_note_id, {"paper_id": portable_paper_id, "body": "Observation"}
)
client.save(operation)
```

`new_graph_operation_in(conn, kind, entity_id, payload, ...)` uses a caller-owned
transaction on the same journal database. Combine it with `Journal.apply_in` to
save a paper, list, membership and note as one compound action. It sees earlier
uncommitted outbox operations; it never commits, closes or replaces the connection.
An inactive transaction, wrong database or workspace/device mismatch is rejected.

- The builder derives incarnations, parent references and structural dependencies
  from accepted graph state plus outstanding local operations. Acknowledged edits
  remain outstanding until their outcomes arrive in the contiguous inbox.
- Roots (paper/list) have no parents; notes reference a paper; memberships reference
  one list and paper. Membership identity comes from `sync_schema_v2.membership_id`.
  The graph contract defines the closed payload shapes and lifecycle semantics.
- A deleted entity or child of a restored parent cannot be revived by an ordinary
  edit. Explicit `restore=True` assigns a new incarnation and current parent refs.
  Missing/deleted parents must be restored first. No implicit title matching,
  reparenting, download or AI call occurs.
- The legacy builder rejects accepted/pending graph entities and legacy notes
  under a graph paper, directing callers to the version-2 builder. `save()` and
  conflict resolution recheck this inside the journal transaction, so a supplied
  stale version-1 envelope cannot bypass the builder and mutate local graph data.

Accepted events maintain graph metadata transactionally with history and cursor.
The first opening of an older private prototype backfills graph metadata from its
retained ordered inbox once; normal restarts do not replay the whole history.
Research projection applies roots before children even when a root's latest rename
has a later sequence than a child's creation. Parent changes reevaluate children
whose own heads did not change, so restoring a list cannot resurrect its former
memberships automatically.

Pending local parent edits, unreceived acknowledgments or deferred parent projection
hold dependent children without blocking unrelated ready entities. An accepted list
delete/restoration waits while an old-incarnation membership has outstanding local
work; its content remains in the outbox/history until the authority preserves its
conflict. Once settled, obsolete memberships are hidden using a local writer-only
delete, never an extra outgoing operation. Notes belong to papers and survive list
removal. Writer failure rolls graph state, content and cursor back together.

`deferred_reasons(limit=100)` returns bounded entity IDs and reason codes, without
research text: `pending_local`, `pending_descendant`, `parent_pending`,
`parent_deferred`, `parent_missing`, `parent_deleted`, `parent_incarnation`, or
`canonical_absence`. `status().deferred` includes these blocked projections.
A child with an obsolete parent remains hidden until an explicit restoration or
retirement; "deferred" does not imply automatic eventual resurrection.

For version-2 conflicts, `resolve_conflict(..., restore=True)` is required when an
incoming choice would restore research. A canonical choice for an obsolete child
creates the graph contract's narrow explicit retirement: it preserves old parent
refs, does not revive/reparent anything and closes the conflict only after accepted
receipt. Ordinary edits cannot request this bypass. Pending resolution retries keep
their original identity and choices. Graph/structural state is rechecked in the
same transaction as saving the resolution.

Paper deletion remains outside this version's retention contract. A rejected local
paper creation whose canonical head is absent is retained for explicit reconciliation
with reason `canonical_absence`; the client does not invent a paper-deletion action.
Projection scans and private schema evolution still need performance/migration
review before production enablement. These APIs do not attach existing UI/CLI/MCP
writers, implement a desktop conflict screen or prove real-device synchronization.

`tests/test_sync_graph_client.py` exercises graph ordering, offline chains, pending
ancestor/descendant protection, explicit restore and retirement, acknowledged pull
gaps, same-connection rollback, graph-index rebuild and bounded diagnostics. The
parent checkpoint records exact final full-suite evidence separately.


Membership `added_at` is immutable within one incarnation. The graph builder and
the save/resolution transaction compare it with that incarnation's creation
operation, found in the local journal or retained received receipt. This includes
pending creations and acknowledged operations whose events have not yet arrived.
A supplied raw envelope cannot change the time after passing the builder. Changing
the citation keeps the creation time; explicit deletion/restoration with a new
incarnation may establish a new time. This prevents an updated existing projection
and a newly bootstrapped peer from deriving different membership timestamps.


## Reading state as a dependent graph entity

`new_graph_operation("reading_state", membership_id, payload)` accepts the closed
reading-state shape from the graph contract: `list_id`, `paper_id`, `state`,
`delivered_at`, and `read_at`. Supported states are `pending`, `delivered`, `read`,
`skipped`, and `deferred`; timestamps are nullable timezone-aware ISO values.
The identity is the portable membership identity, not a global paper state.

The builder derives all three references from one membership incarnation: the
membership itself and its stored list/paper parent references. It verifies that
this exact closure is active; it never combines an old membership with independently
chosen newer root incarnations. Uncommitted local parent operations and acknowledged
but unreceived parent creations remain visible to the builder. Raw `save()` calls
repeat closure validation inside their journal transaction before research writes.
Canonical retirement has only the shared graph contract's validated conflict bypass.

Projection ordering is roots, memberships/notes, then reading states, regardless of
the latest head sequence. A pending/awaiting/deferred parent holds the dependent
state without blocking unrelated ready data. Membership deletion or restoration
cannot cascade away an unsent state edit. The same protection applies when an
unchanged membership becomes obsolete because its list was deleted or restored.
Once the state outcome arrives, any rejected local content stays in conflict history
and obsolete projections can be hidden safely. No extra outgoing delete is emitted.

Restoring a list or membership does not restore its old reading state. The user
must choose a new reading-state incarnation with `restore=True`, including an
incoming conflict resolution that would revive the old state. Canonical retirement
preserves the old closure and cannot silently reparent to the new membership.
Reading-state changes touch all three direct parents' structural revisions; offline
ancestor deletions use the latest state operation as their structural predecessor.

`tests/test_sync_reading_state_client.py` covers pending/acknowledged parents, late
renames, exact/forged closure, ancestor deletion races, explicit restore, custom
resolution/retirement, same-transaction chains, restart and atomic receive failure.
This remains an explicit local API; production reading UI actions, complete graph
enrollment, per-device PDF reading positions and real-device sync are separate work.
