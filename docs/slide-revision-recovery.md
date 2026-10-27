# Detached recovery of single-slide revisions

`sync_recovery` includes validated private `.revision-requests` files found under
the explicitly selected workspace's `presentations` directory (and the optional
explicit legacy root). No path embedded in a receipt selects an input/output file.

The synthetic protocol table is `research_slide_revision_recovery`, with columns
`request_id, manifest`. The closed version-1 manifest contains:

- `request_id`, `workspace_id` and `body: {sha256, size}`;
- `figures`, mapping source IDs to `{sha256, size}`;
- `sources`, a complete list of original PDF descriptors;
- `artifacts`, the validated original loaded/observed artifact payloads.

The body retains the private receipt fields exactly, except inline PNG base64 is
replaced by descriptors. Images are separate immutable objects. This preserves
valid receipts larger than the recovery format's 16 MiB SQL row limit. Rebuilding
the private record restores those base64 values exactly. Private prompts,
instructions, original decks, completed results and failure explanations remain
private research content; they are not telemetry.

Creation verifies ownership against the selected database identity/workspace,
all receipt PNG hashes and decoding, original immutable figure identities, original
artifact closures, and every referenced original PDF's bytes and readability.
An original unbound database moved to another filename is recognized by its file
identity; a replacement at its old path cannot claim those receipts. Mutable
legacy files bypass the migration check only when their exact verified content is
already represented by retained typed records. Omitted layout defaults may be
normalized; existing fields may never be silently removed. Unclassified research,
missing/corrupt source bytes and ambiguous ownership fail the whole backup.

Limits are explicit: 2,000 receipts, 256 MiB receipt/inventory bytes, each receipt
at most 48 MiB, 128 figures/32 MiB per receipt, and 16 original PDFs per receipt.
Existing archive-wide row/blob/8 GiB limits also apply. Inventory visits each paper
folder once. No source BlobStore, research row or active workspace is modified.

## Restored capabilities

Rows are archived in `recovery_records`; bytes are retained in `objects`. No
active `.revision-requests`, original sync binding, writer observation, job,
credentials or retry queue is installed.

`sync_slide_recovery.read_detached(database, request_id)` verifies the retained
closure and returns the complete private record with explicit capabilities:
`publish=false`, `retry=false`, `sync=false`, `requires_explicit_review=true`.
The record is data, not a `slide_revision.Revision` or publication authority.
Accepted managed decks still use the existing applied-artifact reconstruction;
stale candidates never replace that current deck. Legacy unbound deck contents
are retained for explicit review, not silently promoted into an applied manifest.

## Unknown historical evidence identity

Some valid imported decks have an empty/non-hash logical `source_hash`. That value
remains unchanged in the retained record **and the detached deck**. A verified
evidence asset is not re-labelled as a historical input/PDF digest.

For these cases, restore writes a bounded local
`recovery-evidence-<slot>.json` mapping and a verified
`recovered-evidence/<asset-sha256>.json` copy. The closed mapping records the paper,
slot, deck ID, original logical source hash and asset descriptor. It carries no
external path or writer capability.

`read_detached_evidence(database, paper_id, slot)` opens and verifies these exact
bytes, reports `historical_input_digest_known=false`, and allows read/export only.
`export_detached_evidence(..., destination)` writes those same bytes to a new file
and refuses to overwrite an existing destination. Both reject changed mappings,
links, sizes, hashes and ownership. Ordinary deck-reader adoption of this mapping
is **not implemented in this slice**; the explicit recovery reader/exporter works
now. No normal-reader readiness is inferred from byte availability.

Fixture coverage includes completed/stale/storage-failed jobs, no-AI publication
retry checkpoints, large receipts, absent/corrupt images and PDFs, original DB and
ZIP replacement, original content/provenance preservation, inactive capabilities,
and byte-exact evidence export. There are no real model/network or user-data tests.

## Existing-user legacy PDF adoption

The available-bytes/no-manifest gap is now covered by
[archive-only legacy source adoption](legacy-source-recovery.md). Required PDF
hashes are resolved only under explicitly trusted workspace PDF roots and verified
before entering the archive. No live manifest, binding or operation is created.
The existing-user fixture now verifies successful complete backup, unchanged live
data, exact retained PDF bytes, and inactive detached capabilities. Missing,
changed or outside-root sources still fail unless the caller explicitly selects
an owned source directory.
