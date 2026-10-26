# ADR 0001: Atomic local sync journal foundation

Status: accepted for an isolated prototype, 2026-10-26. Not a public wire contract.
Scope: S02 local durability decision and initial S03 experiment.

## Context

Paperfact has SQLite and file-based research writers. Its UI revision counter
cannot reconstruct missing edits or deletions. Research bundle import has merge
semantics rather than replication semantics. The [writer inventory](../sync-write-inventory.md)
must guide adapter coverage before sync can be advertised.

## Decision

- Put a local research mutation and its pending operation in the same SQLite
  transaction. An exception rolls back both. Do not append a journal after saving.
- Bind a journal explicitly to a path, workspace ID and device ID. A mismatch
  requires explicit enrollment; never silently reassign a copied database.
- Keep operation identity separate from research identity. Persist a canonical
  payload fingerprint and receipt; exact retries return the original sequence
  without writing again, while changed content using the same ID is rejected.
- Retain acknowledged receipts. Pending operations survive reopening. Consecutive
  offline edits to an entity must reference the latest pending predecessor.
- Use a closed, size-bounded envelope. Version 1 of this private prototype accepts
  only list metadata and unanchored text notes, with put/delete actions. No generic
  SQL, filesystem paths, credential records or arbitrary configuration payloads.
- Use trusted application callbacks with a transaction guard. The callback may
  write research data, but accidental commit, schema changes, database attachment
  or journal modification are rejected. This is not a sandbox for untrusted code.
- Keep the experiment independent of runtime configuration, network, AI routing
  and app startup. Existing workspace schemas and actions are unchanged.

```mermaid
sequenceDiagram
    participant Caller as Research operation
    participant DB as Local SQLite
    Caller->>DB: Begin write transaction; check binding and retry ID
    Caller->>DB: Write research content
    Caller->>DB: Save pending operation and receipt
    Caller->>DB: Commit both
    Note over DB: Reopen retains pending work
    Note over Caller,DB: Any failure before commit rolls back both
```

Example: offline rename A has no predecessor; rename B depends on A. Both survive
restart. A repeated submission of A does not revert B. Acknowledging B before A
fails; acknowledging A then B clears pending work while retaining replay receipts.

## Alternatives

- **Copy SQLite or watch its modification time:** cannot resolve simultaneous edits,
  distinguish deletion from eviction, or preserve causality. Rejected for replication.
- **Emit events after commit:** a crash can lose the event. Rejected for durable capture.
- **Use generic database triggers as the complete protocol:** useful for invalidation,
  but file writes, payload allowlists and domain conflicts still need explicit semantics.
  Deferred as a compatibility/detection tool, not chosen as the domain protocol.
- **Start with cloud hosting:** would add authentication and operational dependencies
  before local preservation is demonstrated. Deferred.

## Consequences and limits

`sync_journal.py` supplies the local transaction primitive only. Callers must ensure
that the research mutation actually matches its envelope; the journal cannot infer
domain semantics from arbitrary trusted DML. All existing writers still bypass it.
Local integer note IDs are not migrated. Caller-supplied stable IDs are experimental.
The 256 KiB limit is for this prototype, not a new restriction on existing notes;
large content needs a chunk/blob contract before production integration.

No remote apply, accepted entity revision tracking, conflict resolver, cursor,
transport, device revocation, blob transfer or server authorization exists here.
The acknowledgment method is a trusted local seam, not authentication. Acknowledged
receipts have no pruning policy yet. Binding a restored/cloned database to another
device and journal schema migration require later explicit workflows.

The proposed A/B concurrent-note example remains an acceptance requirement:
both devices edit a common revision offline; the service accepts one and records
the other as a preserved conflict; neither overwrites an unsaved editor draft.
It is not proven by local journal tests.

## Evidence and remaining decisions

`tests/test_sync_journal.py` checks persisted content and pending operations for
restart, chaining, concurrent retry, changed replay, rollback, callback transaction
escape, invalid payloads, acknowledgment ordering and workspace/device mismatch.
Exceptions and reopen tests simulate interruption boundaries; they are not physical
power-loss or filesystem fault tests. Final full-suite counts are in the
[implementation handoff](../implementation-0.5.0.md).

S02 remains open for production identity migration, wire evolution, remote conflict
and retention rules, hosting/authentication, encryption/recovery and operating costs.
S03 remains open for production adapters, stable IDs and safe schema migrations.
