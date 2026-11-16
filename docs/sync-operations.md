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
- New notes use the existing full native note contract: source-authored UTC
  creation time, `kind="note"`, and explicit empty page/anchor. One intake captures
  its clock once; an empty peer preserves that time instead of substituting its
  own wall clock. This applies to both `create_list` and `add_papers`. Callers still
  provide ordinary text strings. No wire format, result shape or operation count changes.
- Stable action-derived IDs and an immutable request fingerprint make identical
  retries return the original result, even after sync/restart. Changed content using
  the same request ID fails. Distinct requests may legitimately create equally named lists.
- Empty named lists are supported. Unsupported/invalid entries fail before saving;
  a later writer or receipt failure rolls back every record and identity mapping.

Successful retry retains the original note IDs and creation times, including after
later edits and process restart. Partial writer or receipt failure also rolls back
rich-note projection markers. Existing two-field legacy note operations remain
readable; this does not infer missing historical times or rewrite old receipts.
Existing desktop/CLI/MCP routes retain their separate current contracts; this
library fix does not redirect the public 500-candidate import into its 200-paper bound.

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


## Observed native PDF replacement

`repdf <paper_id> --file <path>` and `repdf <paper_id> --url <url>` now use the
shared attachment action in a completely enrolled workspace with registered,
owned reader/blob storage. First-original list prefetch shares this boundary as
described below. A partially enrolled or unavailable store refuses replacement.
Unenrolled workspaces retain the existing alias/reanchor behavior.

The native operation captures the paper lifetime, original graph head, reader
registration and database/store identities **before** downloading or staging.
It verifies immutable PDF bytes outside the write transaction, then rechecks the
observed base inside the single shared transaction. Publication records desired
metadata, outbox, applied verified bytes and receipt together. Failure or
cancellation before commit keeps the previous original. Stale publication or
retry cannot overwrite or revive a newer original. Previous immutable PDFs,
legacy aliases and existing note anchors are retained; no derivative deletion or
automatic source relabeling occurs. Other peers receive metadata/bytes through
the existing separately authenticated coordinator; this command does not contact
an authority or enable hosting.

Worker-level API in `native_primary_publication`:

- `observe(database, local_id, *, ticket=None, current=lambda: True, first_only=False)` captures the
  source before external work; returns `None` only for an unenrolled workspace.
- `prepare(observation, path, *, request_id=None, pdf_url=None)` stages an explicit local PDF;
  callers may retain the returned prepared action for exact retry.
- `run(prepared)` publishes through the shared attachment transaction. Repeated
  activation of the same running action is refused; exact completed retry returns
  its receipt while that original is still current. A new CLI invocation is a new
  explicit replacement, not a persistent retry of an earlier command.

This source change is not in the currently delivered1875db5 native installers.
Frozen CLI acceptance and physical Mac replacement remain separate gates.
No live download, AI call or owner database is used by regression
fixtures (`tests/test_native_primary_publication.py`).

## First-original background downloads

List prefetch (`pdf_downloads.download`) captures its database native identity at
entry, before waiting for the existing per-paper process lock. It uses the same
native publisher for a fully enrolled paper with no managed-document history and
no legacy file, with owned reader/blob storage already configured. The streamed
PDF stays in an owned temporary directory until verification and publication.
Real byte progress remains visible; verification is indeterminate until the queue
reports completion. No arbitrary percentage is assigned to staging or SQL work.

`first_only=True` refuses an original that appeared before admission; the observed
base is rechecked after streaming and in the final transaction. A newly supplied
legacy PDF, changed workspace/path or replaced database also invalidates pending
publication. Existing aliases stay legacy; existing managed originals use their
verified bytes, and unavailable managed versions require workspace attachment
transfer rather than searching for another PDF. This is not read-time migration
of all legacy files or adoption of `fetch.ensure_pdf`'s remaining legacy fallback.

When `pdf_url` is supplied, publication includes the successful candidate's ordinary
paper-metadata operation and clears the local PDF-failure cache in the same SQL
transaction as the original/outbox/receipt. Local URL projection changes only that
column, preserving rich existing local author data. The complete ordinary paper
payload travels in the existing shared graph; this adds no new wire entity. Failed
or cancelled publication rolls all these changes back. A receipt retry does not
re-clear a later failure cache or overwrite a later metadata edit. Final publication
is the completion boundary; cancelling after a successful commit does not undo it.

`tests/test_native_pdf_downloads.py` covers actual mocked HTTP streaming, alternate
sources, atomic metadata/byte publication, cancellation, failure after URL write,
source/workspace/lock races, independent manual originals, retained rich metadata,
exact retry and managed-byte recovery boundaries. Existing queue/stream tests
retain their concurrency, deduplication, progress and partial-file assertions.
No external service/provider, owner research, or physical-device acceptance is used.

## Deletion boundary: remove from a list versus erase a paper

The current v2 codec explicitly refuses `paper` operations with action `delete`
(`sync_schema_v2.validate`); global paper deletion requires a later retention
contract. This check already applies before authority history is changed. It is
not a new admission restriction or a completed global deletion feature.

Remove a membership or delete a list through supported operations instead. A
native list retirement preserves paper metadata/research and retains accepted
operation history. Use the real client's operation builder: base revisions and
structural observations come from received state, not guessed per-entity counters.
Unsupported attempts do not grant permission to reset a cursor, discard a queued
operation or rewrite history. A native peer can continue verified synchronization
after such an attempt is refused.

`tests/test_official_research_admission.py` checks repeated unsupported attempts
against a real official authority with unchanged SQL/history, then actual native
list retirement and verified retry/convergence with paper metadata retained.
It also checks sanitized raw HTTP refusal, client-side validation and ownership
refusal of a valid wrong-device operation. Two cases pass in2.09s pytest/6.1s
bounded stages. This does not certify arbitrary scientific deletion/recovery,
physical-device history or real owner data.
