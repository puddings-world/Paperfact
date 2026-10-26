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
