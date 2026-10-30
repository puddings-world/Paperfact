# Portable reference edges

Reference relationships in `refs(paper_id, ref_paper_id, influential)` are now a
closed `research_content` feature. A distinct ordered paper pair is one conflict
domain. A changed edge never rewrites an entire paper's reference graph.

```json
{
  "scope": {"kind": "paper", "id": "SOURCE_PORTABLE_UUID"},
  "feature": "reference_edge",
  "key": "TARGET_PORTABLE_UUID",
  "data": {"influential": 1},
  "source_document_hash": null
}
```

The entity ID is the existing deterministic `content_id(scope, feature, key)`.
Both endpoints are portable paper UUIDs; local SQLite paper IDs never enter the
wire payload. This is a paper relationship, not a claim about a particular PDF.
`influential` remains the closed 0/1 flag. Unsupported legacy values or missing
paper metadata fail rather than being normalized or silently omitted.

## Both paper lifetimes are dependencies

The existing v2 `parents` array is ordered source paper first, target paper second,
with the exact incarnation of each. A self-reference is preserved and has one
unique paper dependency. The schema permits two parents of the same `paper` kind
only for this feature and its identifiable two-parent deletion. Identity checks
reject reversed endpoints, duplicate parents, missing endpoints and unrelated
entity IDs. Existing one-parent research features keep their original contract.

The graph, authority, local builder and receiver compare full `(kind, id,
incarnation)` identities. Creation touches both parent structure markers.
Projection orders roots before children, even when an endpoint's latest metadata
revision is newer than the edge. A pending root defers the edge. An inactive or
replaced root removes the live SQL projection and keeps retained graph/history;
it cannot silently attach an old edge to the recreated paper.

The generic content projection marker already identifies the directed pair and
its edge incarnation. A restored edge receives a new incarnation, so an old
delete cannot remove it. Edge puts additionally verify that both portable paper
mappings have their exact materialized paper incarnations. No second manifest,
parallel reference graph, or new projection table is introduced.

**Paper deletion itself remains outside the current v2 retention contract.**
Existing unsupported local paper deletion rolls back rather than leaving dangling
live references. Fixtures exercise unavailable/replaced root states to validate
reference safety; those fixtures do not claim a public paper-delete/restore API
has shipped. Real edge deletion and explicit edge restoration are supported.

## SQL writers, observations and retries

Ordinary existing `refs` SQL inserts, updates and deletes on `CaptureConnection`
are captured at its actual commit boundary. Primary-key changes cannot reparent
an edge. Repeated identical SQL inserts/replacements create no duplicate intent.
Transaction rollback rolls back both SQL and outbox. Initial `capture_existing`
uses the same serializers and dependency ordering, preserving all supported
reference rows, including reciprocal relationships and self-edges.

A short reference collection transaction can use its write-time observation.
A long-lived editor should carry `observe_content` or
`observe_target(conn, 'paper', local_source_id, 'reference_edge', portable_target)`
through `expecting`. An absent edge observes both endpoint lifetimes as well as
its absence. A stale explicit observation retains a candidate and leaves live
research unchanged. No empty payload or missing parent is treated as permission
to overwrite current content.

Typed callers use the shared `research_content` builder and save boundary. A
recreated edge requires explicit `restore=True`; an ordinary SQL reinsert cannot
implicitly restore a retained tombstone. Original operation envelopes are the
retry identities. The existing authority receipts reject changed retry content
and return the original receipt for an identical retry.

## Recovery, packages and mobile

The complete-or-fail recovery format already includes `refs`, research-content
projection markers, journals and graph history. The new feature is validated
through the same operation registry. Detached recovery preserves rows/history
without activating old device credentials or identities.

List packages already carry ordinary local reference pairs and the papers at
both ends. That sharing contract remains unchanged; importing a package does not
copy a device's sync identity. There is no new package data field requiring a
`reference_edges` capability, and existing format-2 capability validation is
unchanged. Sync wire support is separate from package compatibility.

The independent mobile reader validates the same ordered endpoint closure,
retains reference history offline and projects current relationships in
`paper.references` with portable target IDs. It hides relationships when either
endpoint is unavailable and suppresses stale snapshot copies after a canonical
change. Mobile reference editing/UI navigation is not added by this slice.

Older services/readers with closed feature or parent validation reject this wire
feature and retain their previous cursor/state. There is no automatic protocol
upgrade or capability negotiation in this change. Update participating clients
before enabling reference-edge replication; ordinary compatible list packages
remain the sharing fallback.

## Evidence and remaining enrollment gates

`tests/test_reference_edges.py` covers actual trusted SQL mappings with different
local IDs on two devices, normal SQL capture, unchanged writes, explicit stale
observations, edge conflicts/delete/restore, source and target lifetime checks,
root-first batched receive, retry identity, rollback, independent recovery and
legacy package sharing. `mobile/tests/reference-edges.test.mjs` covers the same
closed wire contract, both dependency markers, offline restart, unavailable
endpoints and atomic rejection of malformed/future data.

References are no longer an unsupported writer scope in the bounded
[first-enrollment service](workspace-enrollment.md). That does not complete
arbitrary workspace enrollment: pins/queue/reading-log writers, remaining
file/annotation scope coverage, shared maintenance locking, reviewed adoption
and physical multi-device acceptance remain separate gates. No user research,
external model, credential, network service, release or migration is exercised
by these fixture tests.
