# Reading state in the private synchronization contract

Status: fixture-tested protocol and adapter slice. This does not enroll an existing
workspace or enable production/device synchronization. Ordering remains separate.
The unreleased v2 envelope is private and has no deployed compatibility promise.

## Identity and payload

`reading_state` describes one paper within one list. Its entity ID is
`membership_id(list_id, paper_id)`, scoped by kind and workspace, so the same paper
can have different reading states in different lists. It has exactly three closed
parent references: `membership`, `list`, and `paper`, each with `kind`, `id`, and
`incarnation`. Parent array order carries no meaning.

The membership reference ID must equal the reading-state ID. The list and paper
references must match the membership's actual parent identities and incarnations.
The direct root references are a required dependency closure, not arbitrary links.

A `put` has exactly these payload fields:

| Field | Contract |
| --- | --- |
| `list_id` | Matches the list parent |
| `paper_id` | Canonical UUID matching the paper parent |
| `state` | `pending`, `delivered`, `read`, `skipped`, or `deferred` |
| `delivered_at` | Null or timezone-aware ISO timestamp, at most 64 characters |
| `read_at` | Null or timezone-aware ISO timestamp, at most 64 characters |

Timestamps describe user data; they never order operations or select a winner.
They need not be inferred from `state`: a later deferred/skipped state can retain
historical delivery/read timestamps. The caller chooses them explicitly.
A `delete` has an empty payload and still carries the complete parent closure.

## Conflicts and lifecycle

The normal entity base-revision and same-device predecessor rules apply. Missing
parents cause a retryable precondition error without allocating an event. All
parent existence checks finish before deciding stale-parent conflicts, independent
of parent order. Invalid root identities are rejected; stale incarnations or
inactive parents preserve the incoming operation as a conflict.

Every accepted reading-state mutation advances each of the membership, list, and
paper structural markers exactly once. It does not recursively traverse the graph.
Therefore a concurrent membership/list deletion and reading update cannot both
silently win: the first accepted mutation invalidates the second mutation's
structural marker or parent availability. Both submitted versions remain in the
event stream. List renaming does not invalidate a reading state.

An ordinary reading update cannot revive a deleted state or an orphaned state after
parent restoration. Explicit restoration requires a new own incarnation equal to
its creation operation ID, current parent incarnations, and the current own head
revision. Resetting the state to `pending` is an ordinary explicit `put`; deleting
the state creates a tombstone rather than a fabricated pending update.

Explicit conflict resolution may retire a child with `delete` plus `resolution_of`
while its parents are deleted or replaced. It must retain the child's exact own
incarnation and original parent references, and satisfy ordinary base/structure
checks. If the membership was replaced, the retained membership-incarnation
receipt proves the root closure of that retained incarnation attempt; the attempt
may itself have been rejected. This permits explicit disposal of a never-canonical
child conflict without claiming its parent was active. Missing or fabricated
historical identity is rejected. Retirement never resurrects a parent and never changes the
structural marker of a different parent incarnation. Matching active parents may
still advance their markers. Conflicted payloads stay available in history.

## Boundaries and verification

`sync_schema_v2.py` closes the envelope and payload; `sync_graph.py` supplies the
shared authority/client dependency rules. The reference service stores accepted
heads, graph markers, events, and retry receipts in one transaction. Existing v1
and other v2 kinds retain their contracts; only reading state allows three parents.

`tests/test_sync_reading_state_service.py` exercises state/timestamp validation,
restart/retry, both orders of delete/read races, closure validation, structural
touch counts, missing-parent ordering, explicit restoration, and retirement after
parent replacement. Companion client, projection, research-adapter, and operation
tests cover the local write path. All tests use isolated fixture databases.

This slice does not synchronize list ordering, analysis jobs, generated files,
usage telemetry, account credentials, or remote PDF downloads.
