# Shared graph research operations

Status: explicit local library for v0.5 development. Existing desktop, CLI and MCP
handlers are not automatically redirected through this API yet. No sync enrollment
is enabled on startup, and no AI, PDF download or remote service is invoked by intake.

## One action, one connection

`Journal.transaction()` owns one connection and commit. `Journal.apply_in(conn,
operation, writer)` uses that existing transaction and a per-operation savepoint;
it never commits the caller's transaction. A propagated failure rolls the compound
action back. A caller may deliberately catch an item failure to retain earlier work,
but must document such partial-success behavior instead of implying all-or-nothing.

The connection must belong to the journal's exact database and must already have a
transaction. The trusted writer cannot accidentally commit, change journal tables,
alter schema, or read/write an attached database. This method temporarily owns the
SQLite authorizer; do not pass a connection with another component's authorizer.
It is an application transaction boundary, not a sandbox for untrusted Python code.

`SyncClient.new_graph_operation_in(conn, ...)` builds against that same transaction,
including uncommitted parent operations. This avoids opening a second connection
that cannot see the papers/lists created earlier in the action.

## Intake facade

```python
from paper_daily.sync_operations import ResearchOperations

actions = ResearchOperations(client)  # explicitly bound client + research_writer
result = actions.create_list(
    "Research route",
    [{"paper": validated_metadata, "citation": "Start here", "notes": ["Observation"]}],
    request_id="caller-retained-retry-id",
    note="Scope of the route",
)
```

- Each entry contains either a closed v2 `paper` metadata object or an already
  graphed portable `paper_id`. Optional `citation` and plain-text `notes` are bounded.
- New papers, the named list, memberships, notes, outgoing operations and the action
  receipt commit together. No title/DOI matching silently merges unrelated research.
- `add_papers(list_id, entries, request_id=...)` adds to an active graph list. Explicit
  reuse of a portable paper preserves its metadata, existing read state and ordering;
  citation changes do not reset those local fields.
- Stable action-derived IDs and an immutable request fingerprint make identical
  retries return the original result, even after sync/restart. Changed content using
  the same request ID fails. Distinct requests may legitimately create equally named lists.
- Empty named lists are supported. Unsupported/invalid entries fail before saving;
  a later writer or receipt failure rolls back every record and identity mapping.

The result contains `list_id`, per-paper portable IDs/membership IDs/note IDs, and
the emitted `operation_ids`. It contains neither provider credentials nor research
bodies. Retain the request ID across retries; do not allocate one on each repeated click.

Prototype bounds: 200 paper entries, 100 notes per entry, 1,000 emitted operations,
8 MiB request and 256 KiB result. A larger intake needs explicitly bounded batches
with reported progress; these limits do not change existing app intake behavior.
Existing papers must already be graphed before reuse; legacy adoption and nonempty
join remain explicit workflows. Adding a new metadata record does not deduplicate it
against the recipient's private library merely because its title looks similar.

## Verification and next integration

Tests use the actual SQLite research schema, an empty peer, and loopback HTTP.
They cover atomic intake, concurrent retries, later renames, explicit paper reuse,
invalid later entries, writer/receipt rollback, independent equal list names,
dependency-aware paging, and absence of implicit AI/workspace initialization.

Remaining: wire this facade and further typed actions into audited UI/CLI/MCP/import
writers; extend order/read-state, anchors, analyses and file manifests; add capture
coverage guards, enrollment/backup UX and real-device acceptance. Shared library
functions alone do not prove every application button is synchronized.

Membership updates preserve the original creation time. A late empty peer receives
the same timestamp as existing peers; an update cannot silently turn it into an edit
time. The graph protocol validates this within each membership incarnation.

A SQLite whole-transaction abort (for example, `ON CONFLICT ROLLBACK`) cannot
retain earlier savepoint work. The original failure is preserved; the action scope
also detects a swallowed abort and refuses success, including a subsequent implicit
transaction. External owners using `apply_in` must abort/retry their entire action.


## Explicit reading actions

`set_reading_state(list_id, paper_ids, state, request_id=...)` marks between 1 and
200 selected portable paper identities in one transaction. Supported states are
`pending`, `delivered`, `read`, `skipped` and `deferred`; duplicates, missing/removed
memberships and invalid IDs fail without partial changes. Each list retains its
own state when it shares a paper with another list. The legacy daily queue is separate.

The action captures its input selection and timestamps once. Marking delivered or
read updates the corresponding timestamp; other transitions preserve prior timestamps.
The request fingerprint excludes the generated clock value, so exact retries return
the saved receipt even after restart, later edits or removal. A different explicit
mark on a restored membership creates state for the current incarnation, rather
than attaching an old offline state to it. Every child state uses the membership's
exact list/paper ancestry, protecting both membership and list deletion races.

The action returns selected states, timestamps and operation IDs after the commit.
Failure on a later paper or the action receipt rolls back the entire selection.
This library API is not yet connected to the existing desktop reading controls.


## Explicit ordering actions

- `reorder_papers(list_id, paper_ids, request_id=...)` takes a complete ordered list
  of portable paper IDs. It resolves the current membership incarnations within the
  same transaction, then records an independent `list_order` intent and retry receipt.
- `reorder_lists(list_ids, request_id=...)` records the complete workspace list order.
  Only the explicit `lists.order` key changes; other key/value state and the legacy
  daily queue remain local and untouched.
- Empty lists/workspaces accept an empty order. Partial, duplicate, foreign, missing
  or deleted entries fail without changing positions. Requests are bounded to 2,000
  entries and the existing 256 KiB envelope limit; these are prototype contract limits,
  not a change to the existing desktop drag/drop behavior.
- Exact retries return their original receipt after later reorder operations, without
  rewinding the visible order. A changed retry ID payload is rejected. Research writes,
  order intent and action receipt share one transaction, including receipt failures.

Construct an ordering-aware client with `order_writer=research_order_writer`. The
dedicated projection applies filtered accepted orders and deterministic defaults;
ordinary research writes do not reinterpret retained historical order payloads.
Missing projection support is shown as deferred, never silently marked applied.
See [the ordering contract](sync-ordering.md) for set conflicts and lifecycle rules.

Targeted shared-action acceptance: **21 tests passed**, covering empty peers, default
creation order despite later citation updates, append/remove projection, both ordering
scopes, repeated actions, invalid selections and transaction rollback. The full-suite result is recorded in the implementation ledger;
existing desktop control integration remains a separate gate.


## Explicit primary-PDF attachment

`attach_document(paper_id, manifest, store=..., request_id=...)` takes a portable
paper identity and already staged immutable bytes. `stage_file(store, path)` is
an explicit local-file helper; it neither discovers URLs nor publishes research.
The shared action validates PDF readability, rechecks the exact graph target and
commits desired metadata, outbox and the request receipt in one transaction.
An exact retry cannot revert a newer document; changed retries fail. Bytes remain
local until the separate authenticated coordinator uploads them. No current desktop
control, legacy PDF alias or AI workflow is automatically enrolled by this action.
See [document transfer](sync-transfers.md) for recovery and acceptance evidence.
