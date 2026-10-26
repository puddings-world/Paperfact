# ADR 0009: Versioned research files through owned manifests

Status: next implementation slice; not implemented. 2026-10-26.
Scope: editable decks and saved research JSON/assets in an explicitly bound
workspace. No hosting, real-data enrollment, credentials or network activation.
Use ADR0007 for the database transaction boundary and ADR0008 for producer
observation/provenance; this decision adds the missing file publication boundary.

## Existing behavior that the implementation must preserve

- `presentations.save_deck()` validates a deck, copies used PNG figures into
  `assets/<sha256>.png`, archives the previous JSON only when `deck_id` changes,
  then atomically replaces `<mode>.json`. It has no SQLite transaction. Manual
  edits keep `deck_id`, so the history directory is not complete revision history.
- `generate()` separately writes `evidence/<source_hash>.json` before `save_deck`.
  `restore_version()` creates a fresh deck ID and calls the same save function.
  Desktop save, figure/layout edits, undo/redo and single-slide AI revision also
  converge on `save_deck`; this is the first production seam to change.
- `PresentationPane.save_recovery()` writes a local recovery file and restores it
  only for the matching deck ID. Recovery may contain invalid/partially typed
  content. Keep it local and usable after a failed save; do not upload it as a deck.
- `paper_highlights.generate`, `reading_links.prepare`, `research_questions._ensure`
  and `materials._locate_materials` call `_atomic_json` independently. Intercepting
  that generic helper would also capture diagnostics/recovery and lose provenance.
- `BlobStore` and authenticated `blob_*` methods already store arbitrary verified
  bytes. The restrictions are in `paper_document` schema/owned-manifest validation
  and `DocumentTransfers._target`, which intentionally accept primary PDFs only.
  Keep those guarantees; JSON and PNG must not masquerade as `application/pdf`.
- The operation envelope is bounded to 256 KiB and inline research content to
  240 KiB. Full decks plus source evidence can exceed this; do not raise the
  operation limit or split one save into unrelated partial deck operations.

## Chosen wire unit: one typed artifact and its immutable closure

Add graph kind `research_file`, with one exact paper parent and a deterministic
UUID derived from `[portable_paper_id, feature, slot]`. The first features are
`deck` with slot `notes` or `guide`, then named slots for `key_sentences`,
`reading_links`, `research_questions`, `material_positions` and `figure_index`.
Every feature has a closed validator and a fixed local projection adapter;
unknown features fail closed. Entity identity is independent of a deck generation
ID, content hash, file path and device-local paper ID.

A put payload has exactly:

```text
paper_id, feature, slot, format_version,
source_document_hash, input_versions,
body: {sha256, size, media_type},
assets: [{id, role, sha256, size, media_type}]
```

- `body` is canonical UTF-8 JSON with a maximum of 8 MiB. Initial asset roles are
  `figure` (PNG), `evidence` (typed JSON) and `source_text` (UTF-8 plain text).
  At most 256 unique asset IDs, 64 MiB combined assets, PNG at most 8,000,000 bytes
  each, JSON/text at most 8 MiB each. Reject oversize saves while retaining the
  candidate; never truncate research to meet a limit. All manifests use lowercase
  SHA-256, exact byte size and an allowlisted media type. These are initial bounds,
  not a promise that existing oversized local files are silently migratable.
- Asset IDs are logical references within the artifact, not filenames. Preserve
  existing figure/source IDs when they are valid. Body references must resolve
  exactly to declared assets, without duplicate IDs or undeclared external files.
  A body cannot request a URL fetch, filesystem traversal or script execution.
- `input_versions` uses the bounded observation/provenance contract from ADR0008,
  not a second independent causality protocol. The normal operation base,
  predecessor, parent lifecycle and resolution fields still govern conflicts.
- `source_document_hash` is the actual PDF byte hash or null for explicitly
  unproven legacy content. Current `Deck.source_hash` hashes an evidence snapshot;
  key-sentence and question `source_hash` fields hash text/input data. Preserve
  these as input/evidence hashes and never relabel them as PDF hashes.
- A deck body keeps editable layout, slide array order, speaker notes, citation
  sources and figure bindings. `Slide` currently has no stable slide UUID; whole
  deck revisions do not require inventing one. Do not claim per-slide merging.
  Normalize the body paper ID to its portable ID on publication and map back only
  in the local adapter. Preserve `deck_id` as generation metadata, not sync identity.
- Wire validation wraps `deck_from_dict`, `validate_slide` and layout validation
  with explicit closed fields/count/depth bounds. Existing validators accept some
  nested dictionaries that are too permissive for a wire contract. JSON rejects
  duplicate keys, NaN and excessive nesting. PNG validation includes decoding and
  bounded dimensions/pixel count, not only a signature. No SVG, HTML or executables.
- Publish only allowlisted generation metadata: chosen inputs and bounded model/
  backend labels where useful. Omit local profile names, request receipts, CLI
  identifiers, errors, credentials and arbitrary `generation` dictionaries.

A delete uses an empty payload and ordinary graph lifecycle rules. It detaches
the current artifact without deleting bytes/history. Restore is an explicit new
operation/incarnation where required; resolving a conflict never mutates its old
manifest or silently reattaches it to a restored parent.

## Actual producer save and recovery transaction

Introduce one shared `publish_research_file` action, used by the existing save
entry points rather than a second UI/API. The unbound path retains its current
local behavior. In a bound workspace:

1. The editor/job supplies its loaded observation and exact captured document/input
   provenance. Copy the candidate; do not modify the visible `Deck.figures` while
   resolving assets. Validate, serialize and stage all immutable bytes into the
   owned BlobStore outside a SQLite write transaction. Resolve existing local
   source paths only through trusted `figure_bytes`/document adapters.
2. In one research transaction, recheck owner/incarnation and observed base, append
   the manifest operation, store the retry receipt, desired artifact binding and
   durable local materialization intent. Register every referenced blob as retained.
   A stale candidate survives separately; it does not replace the current deck.
   An exact request retry returns its original result, not a new revision.
3. Materialize the complete verified closure into a version directory keyed by
   operation/content identity. Set the applied binding only after all required
   files are ready. Readers resolve the applied version, not whichever loose file
   happened to be overwritten last. A compatibility `<mode>.json` copy may be
   refreshed afterwards, but is no longer the authoritative managed reader source.
4. Notify the UI after the durable local commit. Keep the existing open deck and
   dirty recovery draft until an explicit refresh/save decision. Report saved
   locally, awaiting files, pending upload or conflicted distinctly. A successful
   local save does not imply remote acceptance or Google Slides publication.

Failure windows have defined outcomes: before commit, staged unreferenced bytes
are harmless orphans; after commit/before materialization, retry the durable
intent; after directory installation/before applied binding, reuse verified bytes
and recheck the target. Never compensate by deleting a newer current version.
Old/current/conflicted asset references stay separate even when figure IDs match.

The local undo stack remains an editor behavior. A persisted undo/redo or history
restore is a new research save against the loaded base, with the previous revision
retained. Recovery drafts are version-keyed locally, not only paper/mode; receiving
another deck must not overwrite them or auto-apply an old draft to new content.

## Service and transfer extension

Reuse the existing authenticated begin/append/commit/read endpoints, namespace,
device-bound sessions, quota reservations, revocation and bounded block integrity.
No new download-by-hash capability, signed URL, public enrollment or arbitrary path
endpoint is needed. Owning the manifest body does not grant access to its assets.

Extend the service's owned-blob precondition to `research_file`: before allocating
an accepted/conflict event, every declared blob must be committed and owned by
that workspace, with matching size/hash. Validate the body and its asset closure
with the feature schema. A missing/incomplete blob is a retryable precondition,
not a partly accepted artifact. Existing exact operation retries still return the
original event even if bytes are subsequently unavailable. Reauthenticate after
any out-of-transaction validation; never trust a cached successful session.

Keep validation bounded and instrument bytes read/lock duration in fixtures. Do
not introduce a stat-only integrity cache to speed closure validation. Reuse the
server-owned block digests and full-manifest verification rules from ADR0006.

Extract a narrow common blob-transfer engine from `DocumentTransfers` while
retaining its PDF-specific target/activation adapter. The new artifact adapter
enumerates the body/assets, deduplicates hashes, resumes transfers and validates
the complete closure before activation. Upload all required blobs before pushing
the artifact operation. Received metadata/history/cursor commit immediately;
unavailable body/assets defer only this artifact's projection, preserving the
previous complete editable deck. Session change, paper navigation, cancellation
and close invalidate activation, not the already transmitted bytes.

## Other producers and backup prerequisites

| Existing producer | Required publication adaptation |
|---|---|
| `presentations.save_deck`, `generate`, `restore_version`; pane save/revise/undo | First complete vertical: one deck plus its used figures/evidence closure and observed base. Generation and edit share this action. |
| `paper_highlights.generate` | Publish ranked sentences, reasons, coverage and exact input/PDF provenance; strip execution receipts. Coordinate SQL AI marks through the same research transaction. |
| `reading_links.prepare` | Publish links with explicit input analysis versions; quote indexes are meaningful only within that version, not the latest array. |
| `research_questions._ensure` | Publish useful validated questions only. Keep `reason`/`failed_source_hash` retry diagnostics local and preserve the prior useful result on failure. |
| `materials._locate_materials` | Publish only proven version-bound positions when needed as research; rebuildable lookup caches may remain local. Never attach legacy geometry to a new PDF. |
| `figures.py`, extracted text | Versioned manifests keyed by captured PDF plus extractor/options. Deck-referenced historical PNGs are retained even after extraction refresh. No AI call on projection. |
| bundle/pocket import | Validate and map into the same action; imported snapshots are new local changes, never remote receipts or device identities. Keep existing merge/replace choices. |

Before enabling capture for a populated workspace, inventory current decks,
history, evidence and recovery files without modifying them. Back up the SQLite
snapshot, all referenced immutable blobs, legacy files not yet migrated, and local
recovery drafts. A normal list bundle excludes deck history and is not this backup.
Verify restore into an isolated directory, including missing/corrupt asset reports;
never copy device credentials into a joining device.

Initialize one baseline binding per artifact slot. Import valid existing historical
decks into retained version records, not repeated overwrites of the current slot.
Keep invalid/oversized legacy content recoverable and report it; it must not be
deleted or marked synchronized. Source hashes that cannot be proven remain unknown.
`storage.prune` currently reasons about live paper claims and legacy paths, not all
sync history. Exclude the owned store/version directories until reference-aware
retention covers accepted, pending, conflicted, historical and draft-dependent
assets. No automatic history/blob garbage collection in this slice.

## Implementation order and acceptance

1. Add the closed artifact schema/projector, owned-closure service checks and
   generic transfer adapter. Pin cross-workspace known-hash denial, partial closure,
   changed bytes, malformed nested JSON, quota, cancellation and exact retries.
2. Wire **actual `save_deck` and pane save/generate/revise/restore** immediately.
   Fixtures must create an editable deck with citations, speaker notes, layout and
   multiple PNGs, sync it to an empty peer and reopen/export it without AI. A stale
   edit keeps both versions and the draft; failure between every publication step
   recovers after restart without a half-updated deck.
3. Wire the other named producers through the same helper and add per-producer
   fixtures. Verify PDF A-to-B changes preserve old deck figures and source links,
   and regeneration does not rewrite history. Add backup/restore and prune tests
   before any user-facing enrollment can be called complete.

Reuse `tests/test_presentations.py`, presentation pane/workspace tests, JSON
producer tests, `test_bundle_recovery.py`, document/transfer/blob integrity tests;
add dedicated artifact service/action/recovery cases. Run the full project check
for every implementation batch. This ADR adds no runtime behavior or test claim.
