# Private v2 research graph contract

Status: local service/schema implementation, 2026-10-26. This extends the isolated
sync foundation; it does not enable production capture, hosted service deployment,
or automatic synchronization of existing workspaces. V1 list/plain-note operations
remain supported outside graph-enrolled entities.

## Closed operation schema

Version 2 retains all version-1 envelope fields and requires:

- `incarnation`: stable identifier of this entity's creation or restoration operation.
- `parents`: a closed array of `{kind, id, incarnation}` references. Parent order is
  not semantically significant; preserve the original envelope for exact retries.
- `structure_revision`: nonnegative integer recording the entity's observed structural
  marker. It is checked when deleting; ordinary metadata edits do not compare it.

Optional `resolution_of` retains the explicit-conflict-resolution contract.
Optional `structure_depends_on` names an accepted same-device operation that touched
this entity's structure, for offline deletion before its server revision is known.
It is separate from `depends_on`, which still orders edits to the same entity.
Unknown fields, invalid identifiers, booleans used as integers and envelopes over
256 KiB are rejected. V2 is not accepted as an incomplete V1 envelope.

| Kind | Identity and parents | Put payload |
|---|---|---|
| `list` | Existing stable list ID; no parents | `name` (nonblank, 200 characters), `note` (text, 128 KiB characters) |
| `paper` | Canonical lowercase UUID; no parents | Exactly `title`, `authors`, `year`, `venue`, `abstract`, `doi`, `arxiv_id`, `s2_id`, `page_url`, `pdf_url`, `source` |
| `note` | Stable note ID; one `paper` parent | `paper_id` must match its parent, `body` is text up to 200 KiB characters |
| `membership` | Deterministic UUID for the list/paper pair; one parent of each kind | Exactly `list_id`, `paper_id`, `citation`, `added_at`; IDs must match parents |

Paper title is nonblank text up to 2,000 characters; authors is at most 200 nonblank
names of at most 300 characters. Year is null or an integer from 0 through 2200.
Other metadata is nullable text: venue/source 120, abstract 128 KiB characters,
DOI 512, arXiv ID 100, Semantic Scholar ID 200, and each URL 4096 characters.
Nonempty URLs must use HTTP(S), contain a hostname, and have no credentials or
whitespace. They remain metadata; validation and remote apply never fetch them.
The envelope's UTF-8 byte limit applies in addition to individual character limits.

Membership citation is null or text up to 4,000 characters. `added_at` is an ISO
timestamp with timezone, at most 64 characters. It is immutable within a membership
incarnation: ordinary updates preserve the creation receipt timestamp, while an
explicit restoration may establish a new timestamp. Creation receipts must remain
available to validate live incarnations; future bootstrap/compaction must preserve
that evidence or a validated immutable equivalent. Dense local position and reading
state are deliberately absent; their own conflict domains are later work.

`sync_schema_v2.membership_id(list_id,paper_id)` returns:

```python
str(uuid5(NAMESPACE_URL, "paperfact:membership:" +
          json.dumps([list_id, paper_id], separators=(",", ":"))))
```

Deletes require `{}` payload and retain required parent references. Paper deletion
is rejected until research-retention rules cover all of its children. No alias or
legacy paper identity is guessed by this schema; explicit mapping belongs to the
research adapter and enrollment process.

## Shared graph rules

Both authority and receiver use pure helpers from `sync_graph.py`:

```python
check_preconditions(get_entity, get_receipt, operation)  # bool; may raise ValueError
apply_accepted(get_entity, set_entity, operation, sequence)
```

Accessors are workspace-scoped. `get_entity(kind,id)` returns null or a detached
dictionary with exactly `incarnation`, `structure_revision`, `active`, `parents`.
`get_receipt(operation_id)` returns the retained event or null.
`set_entity(kind,id,metadata)` writes within the caller's existing transaction.
Helpers do not mutate caller-owned operations or prior metadata objects. Schema
validation and ordinary entity base-revision/causal checks remain caller duties.

- Missing parent metadata raises `ValueError`: upload/synchronize that parent first,
  then retry the unchanged operation. No event or receipt is allocated on this failure.
- A tombstoned or different-incarnation parent yields `False`: preserve the child
  operation as a conflict rather than silently reparenting it or retrying forever.
- First enrollment uses `incarnation == operation_id`. Live edits retain incarnation.
  A put restoring an entity after its own or an ancestor's deletion requires a **new**
  incarnation equal to its restoration operation ID. Parent IDs cannot change.
- An accepted creation/restoration/deletion sets the entity's structural marker to
  its event sequence. Ordinary live metadata edits preserve that marker. Every
  accepted child mutation advances all matching active parents' structural markers.
- A delete must observe the current structural marker. Alternatively,
  `structure_depends_on` must reference an accepted same-device lifecycle/direct-child
  operation touching this incarnation, whose sequence equals that marker. A later
  child edit invalidates this precondition even when parent metadata did not change.
- A first delete may establish an inactive tombstone with its own creation ID and
  structural revision 0. Repeated logical deletes use the existing incarnation and
  current marker; exact retries return the original receipt without another event.

Example: create list L, create paper P, add membership M, then delete L while offline.
The delete can retain `depends_on=L` and `structure_depends_on=M`; no device invents
a server sequence. A concurrent accepted membership edit makes that delete conflict.
A list rename alone does not change the marker or invalidate a membership's parent.

The reference service persists graph metadata in `sync_graph` in the same transaction
as canonical heads and receipts. Per-operation lookups are indexed by workspace and
entity; pushes do not reconstruct the graph by scanning history.

## Explicit retirement of an obsolete child

Ordinary puts/deletes cannot bypass a deleted or restored parent. A narrow exception
supports discarding a conflicted child without restoring its parent:

- The operation is `delete` with `resolution_of` naming a real conflict for that
  same workspace/entity. The service validates the target before graph checks.
- It retains the exact current child incarnation and parent references; if the child
  never became canonical, it retains those from the original conflicting operation.
- Base revision, own-incarnation and structural checks still apply. The exception
  cannot move the child to another parent or adopt the parent's new incarnation.
- Graph application updates only matching **active** parent incarnations. It never
  advances the structural marker of a tombstoned or restored/different parent.
  The child tombstone and all previous versions remain retained.

A reference to a parent that never existed is still a missing-dependency error.
This exception is not general permission to write orphaned research or force-delete
another incarnation. Client-only hiding of archived projections does not emit deletes.

## V1 transition and remaining gates

An existing V1 root can explicitly enroll with a first V2 incarnation, using its
actual current base revision. V1 mutations of a graph-enrolled entity are rejected;
V1 note puts cannot bypass an enrolled paper parent. The service also checks the
existing V1 note head when a delete's empty payload cannot identify its parent.
An identical pre-enrollment V1 retry still returns its historical receipt.

Tests cover indexed persistence/restart, parent-delete/child-edit races, missing
dependencies, stale incarnations, rename compatibility, offline structural chains,
retirement, rollback, workspace isolation and unchanged V1 behavior. Client projection
must independently order parents before children and hide archived descendants;
revision sorting alone is insufficient. Runtime writer capture, ordering/read-state,
full research kinds, retention, hosted authentication and real-device acceptance
remain separate gates.
