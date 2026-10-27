# List recency and custom ordering handoff

Decision: keep the first per-list last-opened timestamp and sort-mode preference
local-only. This is a proposed implementation contract for the next Claude change,
not an implemented feature in this checkpoint.

## Scope and storage

- Record successful explicit user navigation into a list, not rendering, background
  refresh, remote apply, import, restore, or automatic startup selection.
- Store each timestamp in `kv` under `ui.lists.last_opened:<list_id>` and the mode
  under `ui.lists.sort` (`recent` or `custom`, default `recent`). Use the existing
  `store.connect()` transaction and `set_kv`; no new sync envelope or migration of
  the closed `list` payload is needed. Keep timestamps out of list research bundles.
- Remove the local recency key when deleting its list. Re-created/imported lists
  must not inherit the previous incarnation's visit. Whole-workspace backups may
  retain UI history as local recovery data; restoring one is not a synced visit.
- Use bounded UTC timestamps and deterministic ties/missing-value fallback. Treat
  invalid/future values and clock rollback explicitly. A timestamp is display and
  ranking data, never authority to overwrite research or resolve a conflict.
- Opening a list must not overwrite `lists.order`, publish a sync operation, invoke
  AI, or reorder another device's current view. Background refresh must not steal
  the selection, keyboard focus, or scroll position.

The current `CaptureConnection._mark` ignores every `kv` key except `lists.order`.
That is the deliberate local-only seam. Do not broaden the `kv` sync allowlist.

## Dragging selects custom order

Materialize the current complete ordering of active lists, apply the drag, then
save it to `lists.order` and set `ui.lists.sort=custom` in one transaction. Reuse
the complete-permutation validation in `lists.reorder`; extend that boundary so
mode and order cannot commit separately. Do not persist only a filtered subset.
A stale list set should refresh/retry, preserving both the user's data and mode.
Returning to recent mode does not erase the saved custom ordering.

The custom ordering already has this journal path when sync is enabled:

```text
lists.reorder / store.connect transaction
  -> kv["lists.order"] + local ui.lists.sort
  -> sync_capture.CaptureConnection.commit()
  -> sync_capture._flush()
  -> SyncClient.new_order_operation_in(...)
  -> Journal.apply_in(...) in the SAME transaction
  -> workspace_list_order / entity_id="workspace-lists"
```

The operation retains the existing observed active-list/incarnation set digest,
base revision and dependency chain. It is not `list_order` (paper order within a
list), and not `reading_state` (paper membership read/delivered state).
Remote custom-order changes update the stored custom order; they do not remotely
switch this device's local sort mode.

## Future cross-device recency

Do not invent a new entity type on the client alone: `sync_schema_v2` currently
rejects it. A later versioned capability can add a separate `list_visit` domain,
scoped by list incarnation and device, with device sequence/retry identity and
explicit parent lifecycle rules. Keep it independent of names, membership,
custom ordering and paper reading state. Route writes through the same atomic
research-operation/journal boundary, then enroll service validation, projection,
bootstrap, recovery, mobile, and old-client compatibility together.

Per-device visit sequences avoid conflicts caused by two devices opening the same
list; wall-clock timestamps alone cannot establish the true order of offline
visits on different devices. Cross-device ranking policy remains a separate
decision. No synced visit should make an active reader jump or reshuffle mid-edit.

## Required behavior tests for the next implementation

- Opening a list updates only its local visit; repeated/background render does not.
- Recent order, missing/tied/invalid dates, clock rollback and restart are stable.
- Opening in an enrolled workspace creates no journal event and leaves names,
  membership, paper reading state and saved custom order unchanged.
- Drag from recent mode saves the complete observed order and custom mode together;
  cancellation, stale list set, duplicate activation and failed commit change neither.
- Switching modes preserves the custom order; filtered views cannot drop hidden lists.
- Delete/re-create/import does not revive a prior list incarnation's timestamp.
- Concurrent local windows cannot lose each other's visits or half-commit drag mode.
- Remote custom-order apply respects recent mode and the current focus/selection.

References: [entity domains](adr/0003-research-entity-capture.md),
[ordering contract](sync-ordering.md), [atomic journal](adr/0001-local-sync-journal.md).
