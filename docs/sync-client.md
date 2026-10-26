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
