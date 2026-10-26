# Experimental research writer adapter

Status: local v0.5 foundation. No existing desktop, CLI, MCP or import action is
automatically enrolled. This adapter is not a complete workspace synchronizer.

## Contract

- `prepare(path, workspace_id=..., device_id=...)` opens an **existing** database,
  validates the required research schema, and adds portable note mappings in one
  transaction. A missing path fails instead of creating a new workspace.
- `initialize(conn, workspace_id=..., device_id=...)` does the same within an
  existing caller-owned transaction. It never commits the caller's work.
- `note_identity(conn, local_id)` returns an enrolled note's portable ID.
- `research_writer(conn, operation)` applies a list/text-note put or delete under
  the caller's transaction. Use it with `Journal.apply` or after remote conflict
  validation. It performs no model calls, file access, publishing or network work.

The envelope is the private `sync_journal` prototype contract. Retry suppression,
accepted revisions, remote authorization and conflict decisions belong to the
sync caller; invoking this writer directly does not provide those guarantees.

## Preservation rules

- The adapter uses the actual `store.py` list/note schema. Existing note integer
  IDs, creation timestamps, text and anchors are untouched during enrollment.
- Portable legacy note IDs derive from workspace, originating device, integer
  ID, paper and creation time. Two devices independently owning note `1` do not
  accidentally refer to one note. Existing mappings survive repeated preparation.
- A stored workspace/device mismatch is rejected. Cloning/restoring a database
  or joining a second device needs an explicit enrollment/bootstrap workflow;
  changing the initializer's arguments is not that workflow.
- A new incoming note gets a new local integer ID. An update changes only its
  body; its paper and creation identity cannot silently change. A deletion retains
  its portable mapping with a null local ID, so an explicit later restoration can
  reuse the portable identity without reusing an unrelated integer.
- Paper metadata must exist before a note is applied. The adapter never invents
  paper titles or downloads source material to satisfy a missing dependency.
- This contract accepts only `kind='note'` with null page and anchor. Updating or
  deleting an anchored/other-kind note fails rather than stripping unsupported data.
- List rename preserves creation time and memberships. List deletion removes only
  that list and its memberships; it does not remove papers, notes, analysis, pins,
  surveys or another list's membership. List-owned analysis/pin cleanup and recovery
  must be integrated with their own versioned entities before release.
- An identity whose original paper/creation timestamp no longer matches its local
  row is rejected for reconciliation. Direct external database writers remain an
  unsupported bypass; arbitrary tampering cannot be fully detected from these fields.

## Verification and remaining work

`tests/test_sync_research.py` builds the real research schema in temporary files.
It checks enrollment/reopen, preserved legacy content, device integer collisions,
list rename/deletion, note create/edit/delete/restore, unsupported anchors, missing
papers, wrong bindings, invalid schemas and rollback of content plus identity.
The parent development checkpoint records full-suite counts separately.

Remaining: all research entity shapes, paper metadata replication, stable chat IDs,
anchored notes/PDF versions, creation-time metadata on the wire, deleted list-owned
content recovery, explicit bootstrap/re-enrollment, UI invalidation for note edits,
and routing every supported app writer through shared transactional operations.

## Private version 2: paper and membership graph

Version 1 remains available with its original local-paper-ID text-note semantics.
Version 2 uses the closed graph envelope from `sync_schema_v2`: portable paper
UUIDs, deterministic membership IDs, incarnation and parent references, plus
structure revisions. List/note identifiers retain their validated contract forms.
The journal validator dispatches by version; this writer never infers a protocol
from the payload. The sync service/client own parent-incarnation and conflict
acceptance. Calling the writer directly does not bypass those integration duties.

`prepare`/`initialize` now also add `research_paper_identity(sync_id, local_id)`.
Legacy paper identities derive from workspace, origin device and local paper ID.
Enrollment preserves existing paper rows, local IDs, file naming and note links.
`paper_identity(conn, local_id)` exposes the portable mapping. Repeated enrollment
retains mappings; independently initialized nonempty devices do not silently
identify their papers merely because titles, DOIs or local IDs match.

An incoming unmapped paper receives local ID `sync:<portable UUID>`. An existing
unrelated row at that ID is a reconciliation error, even if its metadata looks
similar. A missing row behind an existing mapping also fails. Nonempty-workspace
joining, external identifier reconciliation and authorized bootstrap remain
separate workflows. The adapter never silently merges two existing papers.

Paper puts update only title/title key, authors, year, venue, abstract, DOI,
arXiv/Semantic Scholar IDs, source URLs and source label. Rank, scores, crawl
timestamps, local research and paper IDs remain unchanged. Unknown wire year/venue
map to the existing SQLite schema's `0`/empty-string sentinels; no year is invented.
An unknown source label is stored as `sync`; the private v2 contract forbids paper deletion.
No source URL is fetched by this writer.

Membership identity is the schema helper's deterministic UUID for a list/portable
paper pair. Its existing SQLite composite key is sufficient for retry-safe local
materialization; no separate integer membership identity is introduced. A put
requires both parents, resolves the portable paper to its local ID, and appends
after the current maximum position. An update changes only citation text, keeping
position, reading state, original added time and read/delivery timestamps. A delete
removes only that membership, never its paper, notes or another list's membership.
The sync graph retains tombstones/incarnations outside this materialized view.

Version-2 notes similarly translate their portable paper parent before using the
existing integer-note mapping. They cannot move an existing note to another paper;
anchored/non-note protection remains unchanged. List deletion still removes only
the list and its materialized memberships. Graph history and independent paper
research survive; service/client parent-incarnation rules decide whether dependent
content may later materialize after a list is recreated.

`tests/test_sync_graph_research.py` checks an empty receiver's paper/list/membership/
note path, enrollment and metadata preservation, identity collisions, missing
parents, membership ordering/state preservation, note reassignment prevention,
list deletion, retry/reopen and transactional rollback of paper metadata/mapping.
Existing v1 adapter tests remain unchanged and are run alongside these cases.

## Version-2 membership reading state

`reading_state` uses the deterministic membership ID in its own entity namespace.
Its closed payload contains `list_id`, portable `paper_id`, `state`, `delivered_at`
and `read_at`. The state is pending, delivered, read, skipped or deferred; each
timestamp is null or a timezone-aware ISO timestamp. The shared graph validates
the complete membership/list/paper parent closure and their incarnations.

The adapter updates only the existing membership's state and two timestamps.
It does not infer timestamps, create a membership, alter order/citation/added time,
update the legacy queue, or change another list's progress for the same paper.
Higher-level actions own timestamp transition semantics. An explicit delete resets
the current membership to pending with null timestamps; a removed membership is
left absent.

Explicit preparation adds `research_membership_projection`, an adapter-owned
marker recording the successfully projected membership incarnation and its root
parent incarnations. Preparation does not enroll existing legacy membership rows
or change their content. A successful membership put records the marker in the
same transaction; membership removal clears it. Reading-state puts require a
matching marker and an existing row. A delete with a missing/mismatched marker is
a no-op, so retiring archived state cannot reset a restored membership or an
unenrolled legacy row. List removal may leave an inert marker; there is no row to
reset, and an explicit membership restoration replaces the marker before state
can be written. Canonical graph metadata remains owned by the sync engine.

`tests/test_sync_reading_state_research.py` checks all five states, list isolation,
unchanged metadata, exact retries, reopen/citation preservation, explicit reset,
missing members, stale retirement after restoration, legacy migration and rollback.
No existing desktop/CLI writer is automatically enrolled.
