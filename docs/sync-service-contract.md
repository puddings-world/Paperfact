# Reference sync service contract

Status: local implementation for isolated clients, 2026-10-26. This is not a hosted
service or a public API. `sync_service.ReferenceService` takes an explicit SQLite
path and never loads the app's workspace, AI accounts or runtime configuration.

## Interface

- `enroll(workspace_id, device_id) -> token`: trusted administrative enrollment.
  Return a random opaque credential once; store only its SHA-256 hash. Reject reuse
  of a workspace/device pair, including a revoked identity. Enroll replacement
  hardware under a new device ID; never silently recycle a revoked identity.
- `revoke(token)`: trusted administrative action, idempotent for a known credential.
  Revoked credentials cannot read, push or retrieve an existing retry receipt.
- `session_info(token) -> {workspace_id, device_id}`: authenticate the opaque token
  without creating data, namespaces or uploads. Use before transmitting private bytes.
- `push(token, operation) -> event`: authenticate and validate the closed v1/v2
  journal/graph envelope, then atomically persist canonical state and a durable receipt.
- `pull(token, after=0, limit=100) -> events`: read ordered events from that
  credential's workspace. Limits are 1-1,000; cursors must be nonnegative integers
  at or below that workspace's current sequence. Boolean values are not integers
  in this contract. Clients persist their applied cursor transactionally.

Credential failures raise `PermissionError`; invalid operations, mismatched retry
content, missing/unrelated dependencies and invalid cursors raise `ValueError`.
SQLite failures propagate, with the transaction rolled back.

```json
{
  "sequence": 1,
  "outcome": "accepted",
  "operation": {"...": "the complete validated operation envelope"},
  "head": {"revision": 1, "operation": {"...": "the accepted canonical envelope"}}
}
```

Events contain exactly these four top-level keys. `outcome` is `accepted` or
`conflict`. `head.operation` may be null with revision 0 when an edit asserts a
stale base for an entity that does not exist. Sequences are strictly increasing
within each workspace, not globally across users. Revisions use those sequences.

## Retry and conflict semantics

- Receipt identity is `(workspace, operation_id)`. An identical retry returns the
  original immutable event, even after later edits and service restart. Reusing
  the same ID with a different device or content fails; no new event is allocated.
- Without `depends_on`, an edit is accepted only if its base revision equals the
  current entity head revision. A new entity starts at revision 0.
- A dependency must be an earlier operation for the same device and entity. If
  accepted, its event sequence becomes the child's effective base. If conflicted,
  the child remains a conflict, preserving the entire offline branch.
- A stale edit retains its incoming content and a snapshot of the canonical head
  in a conflict event. The canonical head remains unchanged. No timestamp chooses
  a winner and no automatic merge discards a version.
- An explicit resolution is a new operation based on the current canonical head.
  Conflicting versions remain in event history; conflict resolution UX and retention
  are separate work. A delete is a retained tombstone, so a stale edit cannot
  resurrect deleted content silently.

All authentication and push mutations occur within a database transaction. Two
concurrent retries yield one event; two concurrent edits based on one revision
yield one accepted event and one preserved conflict. A response lost after commit
can be obtained by retrying the original operation.

## Boundaries and acceptance

The module has no network listener, OAuth login, ownership-account system, TLS,
request throttling, enrollment UI, blob store, retention policy or deployment.
`enroll` and `revoke` must never be exposed as unauthenticated HTTP endpoints.
Any adapter must authorize administrative callers independently. Possession of a
device credential grants access to its one workspace; credentials must never be
included in research exports, telemetry or event bodies.

The local implementation uses synthetic test data only. Behavioral tests cover
workspace/device isolation, revocation, hash-only credential storage, restart and
concurrent retries, offline causal chains, edit/delete conflicts, malformed payloads,
bounded paging and atomic rollback. This does not establish hosted security,
multi-process production performance or real-device sync acceptance.


## Explicit resolution extension (private version 1)

An operation may include `resolution_of`, the operation ID of an earlier conflict.
It must identify a conflict for the same workspace and entity, not an accepted
operation, unknown ID or itself. The normal current-head/causal checks still apply;
a stale resolution becomes a preserved conflict instead of overwriting newer work.
An accepted resolution lets every client mark that specific conflict resolved while
retaining its full history. A resolution race can leave a new unresolved conflict.
Ordinary accepted edits carry no such link and do not implicitly resolve conflicts.
This extends an unreleased private contract, not a deployed compatibility promise.


Primary-PDF puts additionally require committed workspace-owned bytes; an exact
previous receipt remains retryable after byte loss without changing history.
See [blob service](sync-blob-service.md), [HTTP transport](sync-http.md) and
[transfer coordinator](sync-transfers.md). These are private development seams,
not a public enrollment or browser-account API.
