# Private v2 ordering contract

Status: isolated synchronization foundation, not production workspace enrollment.
The contract is private and unreleased. Ordering carries presentation intent;
it never creates, removes, or restores research items.

## Operations and observation

| Kind | Entity ID / parents | Put payload |
| --- | --- | --- |
| `list_order` | List ID; exactly that list and its incarnation | `list_id`, `items`, `observed_set` |
| `workspace_list_order` | Fixed `workspace-lists`; no parents | `items`, `observed_set` |

`items` is the complete ordered permutation of the observed scope. Each item has
exactly `id` and `incarnation`: membership UUIDs within a list, or list IDs within
the workspace. IDs are unique even across different incarnations. At most 2,000
items are allowed, subject to the independent 256 KiB envelope limit. Identifiers
retain the existing bounded ASCII identifier contract.

`observed_set` is a lowercase SHA256 digest of the scope and its sorted active
item references. `delete` has an empty payload and resets the order through the
normal tombstone lifecycle. A later put requires an explicit new incarnation.

The shared `sync_ordering.py` helpers accept a workspace-scoped graph dictionary
keyed by `(kind, id)` with existing graph lifecycle metadata values:

- `scope(operation)` returns `kind`, `id`, and scope `incarnation` (null for workspace).
- `active_items(operation, graph)` returns sorted effective-active item references.
- `canonical_set_bytes(operation, items)` and `observed_set(operation, items)` create
  the portable observation token. A scope stub needs only `workspace_id`,
  `entity_type`, `entity_id`, and `parents`.
- `validate_order(operation, graph)` returns false for a changed set, raises for a
  matching set with an incomplete permutation, and otherwise returns true.

Memberships are effective-active only while their own state and every exact
ancestor incarnation remain active. A restored list does not inherit stale
memberships or their former order. Graph lifecycle validation remains mandatory
independently of the digest, including for an empty deleted list.

## Digest encoding fixture

Encode the following structure as UTF-8 JSON, lexicographically sorted object
keys, compact comma/colon separators, no ASCII escaping, and no trailing newline.
Sort item references by ID; item display order does not affect the digest.
The domain and encoding version are explicit and distinct from envelope v2.

```json
{"domain":"paperfact.sync.ordering","items":[{"id":"alpha","incarnation":"create-a"},{"id":"zeta","incarnation":"create-z"}],"scope":{"id":"workspace-lists","incarnation":null,"kind":"workspace_list_order"},"version":1,"workspace_id":"workspace"}
```

Its SHA256 digest is:

```text
d85d98550510b7ab1b18f5f129fb74daee0964ce3e4bc90c76b384b7bb77c4b0
```

The bytes and digest are literal fixtures in `tests/test_sync_ordering_contract.py`.
Workspace, scope role, scope identity, and scope incarnation are all part of the
hash boundary; credentials and account information are not.

## Concurrency and lifecycle

The builder observes its optimistic graph; the authority checks accepted graph
state in the same transaction as its head and receipt writes. Incarnations are
fixed creation-operation IDs, so offline create-then-order chains require no
predicted server revisions. No lifecycle set-clock or set-dependency table exists.

A changed digest preserves the submitted intent as a conflict. A matching digest
requires the exact current permutation; a missing/extra/stale-incarnation item is
an invalid request with no allocated event. Duplicate IDs and malformed item data
are schema errors even when the digest is stale. Own head base revisions and
same-device `depends_on` still protect reorder-versus-reorder races.

Membership additions/removals/restorations after an accepted list order remain
subject to their normal graph preconditions. The projection filters removed
incarnations and appends new items without rewriting accepted order history.
Workspace list ordering follows the same rule for list-set changes. A transient
add/remove returning exactly the original active set may accept the old complete
ordering intent. Rename, citation, and reading-state changes do not alter the set.

Parent list deletion is deliberately different: `list_order` remains a graph child
and advances its parent's structural marker. Concurrent parent deletion and
reordering cannot silently discard each other's intent. The first accepted event
can make the second conflict. A same-device reorder-then-delete chain can use the
existing `structure_depends_on` mechanism. No presentation-specific exemption
weakens child-versus-parent deletion protection.

Resolving a set conflict needs a new complete current-set intent and digest;
updating only the head base revision is insufficient. Original versions and
resolution events remain in history.

## Projection and boundaries

Canonical fallback order uses accepted creation-receipt sequences. An accepted
order only addresses exact incarnations; new effective-active items follow in
fallback order. Pending local creations use a separate deterministic local tail
until they have receipts. Projection runs after entity/dependency materialization
through a trusted local writer and does not capture its own writes as new orders.

The service does not infer local positions, inspect file content, or scan event
history to validate an order. It reads current workspace graph heads atomically.
Tests cover both ordering/set-change arrival orders, concurrent reorders, parent
deletion protection, restores, offline chains, metadata independence, bounds,
cross-workspace authorization, receipt retries, and the portable digest fixture.
