# ADR 0005: Activate readers through an exact document identity

Status: **planned next implementation slice**, 2026-10-26. Documentation only;
no reader, cache, legacy research or production workspace was changed by this ADR.
Build on [ADR 0004](0004-owned-document-transfer.md) and
[document bindings](../sync-documents.md); do not replace their transfer contract.

## Decision and acceptance journey

Introduce one explicit document resolver shared by the desktop reader, analysis
input and derived-material workers. Continue reading a verified synchronized PDF
on another machine without silently opening a legacy alias, using stale figures,
or applying an anchor from a different PDF. Keep ordinary unsynchronized research
usable. Arrival of remote metadata must not fetch publisher URLs or invoke AI.

The first vertical slice is: receive manifest and bytes -> resolve the exact bound
document -> display it in both PDF backends -> create a hash-tagged local note or
highlight -> navigate only on that PDF -> restart without using another version.
Full annotation/deck synchronization remains separate work, not an implied result
of reader activation; the current synced note contract is plain unanchored text.

## Concrete source seams

| Existing seam | Required change |
|---|---|
| `desktop/main.py:Paper.pdf_path/has_pdf`, `ReaderPage._load_pdf`, external-open handler | Consume resolved document/status instead of reconstructing a sanitized local filename. Never hash on a list-row repaint. |
| `desktop/fetcher.py:_FetchWorker.run`, `FetchRunner` | Carry captured document/workspace/request identity; managed missing bytes use the authorized transfer coordinator, not `fetch.prepare`. |
| `fetch.py:ensure_pdf/_ensure_pdf_locked/extract_text`, `pdf_downloads.py:download` | Shared source resolution and explicit managed-document guard before URL lookup or legacy-cache reuse. Keep legacy downloading for un-enrolled papers. |
| `desktop/pdfpane.py:_QtPdfPane.load/_PixmapPdfPane.load`, `pdfselect.py:SelectionOverlay.set_document` | Load one resolved path/hash together; close old native handles before activation and clear stale selection/page maps on failure. |
| `desktop/main.py:_where/_jump_to` and material/source navigation | Store document hash with new anchors; apply managed anchors/rectangles/page targets only to the loaded exact hash. |
| `pdf_highlights.py:list_marks/sync_ai` | Retain exact-hash filtering and pass the resolved document through callers; do not re-resolve a legacy alias midway. |
| `figures.py:extract`, `materials.py:figure_entries/_pages/collect/_locate_materials` | Read hash-keyed artifacts and propagate source hash with every coordinate/anchor. |
| `paper_highlights.py:read_original/cached/prepare_reading`, `reading_links.py:cached/prepare` | Derive from the captured document/version; preserve old analysis, never automatically rerun AI when a document changes. |
| `pocket.py:has_pdf/pocket_pdf/anchor_for` | Use the resolver; a compressed PDF is a derivative with its own hash and source-hash link, never the original asset identity. |

Two current hazards need explicit tests: `_safe_name` maps different local IDs to
the same filename; `_locate_materials` can accept an existing figure rectangle and
stamp the current PDF hash without proving that rectangle came from that PDF.
Do not solve either by assigning new hashes to old cached coordinates.

## Resolver and activation boundary

Add a proposed `document_reader.py` seam taking explicit research DB/workspace and
BlobStore/cache roots. Return an immutable result containing portable/local paper
identity, source mode (`managed` or `legacy`), desired operation/incarnation when
managed, verified SHA256, reader path, and availability/reason. Paths stay local;
they are not wire or DTO fields. Verification and material preparation run in
workers. UI consumers use cached status plus cheap identity checks.

Bind the workspace once at application startup. `runtime.data_dir` honors
`PAPERFACT_DATA`/`PAPER_DAILY_DATA`; otherwise installed builds use platform app-data
and source builds use checkout `data`. `config.py` derives `papers.db`, `pdf` and
`text` there. Pass this bound context explicitly; do not rediscover roots from the
current working directory or copy another machine's persisted local paths.

- Detect managed mode from document history/binding, including a detached manifest;
  a null desired target must not accidentally reactivate an old legacy alias.
- For managed default opening require desired and applied targets to agree, a
  current paper parent, and fresh verification of their exact immutable bytes.
  Missing, invalid or superseded bytes show the corresponding state. Never fall
  through to `PDF_DIR`, `paper.pdf_url`, arXiv discovery or the legacy fetch worker.
- If an older verified version is already open, retain it with an explicit older-
  version indicator while the user has an edit/selection. Offer activation of the
  new available version; do not reset focus, scroll, drafts or selections on a
  background receipt. An explicit "open previous version" is separate from opening
  the desired version and must retain that previous version's hash.
- Recheck workspace, local paper mapping, desired operation/hash, parent/session
  generation and request generation immediately before publishing a worker result.
  Closing or switching paper/workspace makes old results inert. Repeated activation
  shares one verification/job; failure never leaves an old page map labelled new.
- For papers with no managed document history, preserve the existing legacy path
  workflow. Validate/hash the explicitly resolved legacy PDF in a worker; never
  auto-enroll or rename it. Detect ambiguous sanitized aliases before adoption.
  Existing legacy notes remain readable. Entering managed mode activates the strict
  provenance gate below; do not claim historical legacy anchors were verified.

## Reader paths and native handles

Current verification tests open extensionless BlobStore objects with PyMuPDF.
Qt's extensionless-path behavior and external OS associations have not been
manually verified; use one owned `reader-documents/<sha256>.pdf` projection for a
consistent backend filename. Verify the source, copy to a same-directory bounded
temporary file, flush/fsync, verify the copied bytes, then atomically publish.
Never hard-link this projection to a mutable legacy alias or authoritative blob.
Validate ownership/containment and reject symlinks/reparse points at every boundary.

Different hashes use different paths, so a new version does not overwrite an open
Windows handle. Release Qt, PyMuPDF and selection-overlay handles when switching or
closing. Keep verified blobs if projection/binding fails; retries repair only the
owned projection. Account projection copies against a bounded local cache budget.
External editing, if offered, uses an explicit disposable/exported copy rather
than mutating the canonical blob. This adds no history-blob garbage collection.

## Anchor provenance and cache migration

New note/chat anchors include `document_hash` alongside existing word coordinates;
materials carry the same hash alongside rectangles, figures and page references.
Every navigation path checks the loaded document hash before calling `focus` or
scrolling to a source page. A mismatched or unknown hash in managed mode preserves
text but disables direct navigation with a clear reason. Quote search/reanchoring
is a separate explicit action producing new provenance; never rewrite or delete
old anchors during activation and never call `repdf.replace/reanchor` remotely.

Managed derived caches use `(document_sha256, producer_version, options_digest)`:

- Text extraction includes normalization/extractor version and truncation options,
  or caches full bounded text and truncates only when serving a caller.
- Figure indexes/PNGs include source hash, renderer version and rendering options.
  Keep previous directories so existing editable decks do not lose their images.
- Material positions include document hash and the input signature already used
  by `_locate_materials`; supplied rectangles must have matching provenance.
- AI highlight/reading-link records retain their analysis/source hashes and gain
  explicit PDF provenance. A text hash alone does not establish coordinate identity.
- Compressed pocket PDFs record their own byte hash plus original source hash;
  coordinate compatibility requires validation, not equal paper IDs or mtimes.

Do not bulk move/delete paper-ID caches or guess their provenance. Legacy mode can
continue reading its existing caches. Managed mode reuses only proven matching
entries and otherwise rebuilds cheap deterministic derivatives on demand. Preserve
unmatched analyses and slide content for reading/review; AI regeneration is explicit.

## Observable tests and delivery boundary

Use actual-schema fixtures, synthetic PDFs with different page/word arrangements,
simulated workers and both available PDF backend seams. No real account or research.

- Un-enrolled legacy papers still open; managed missing/detached/corrupt documents
  cannot fall back to an unrelated legacy file or make network/model calls.
- Two colliding sanitized local IDs and two devices' different local IDs resolve
  correctly through portable identity; file presence alone never sets availability.
- Version B arrives while A is selected/edited; drafts and view state survive,
  late A verification cannot activate, explicit switching clears old overlays.
- New anchors carry A's hash; old/missing-hash managed anchors and stale figure
  rectangles never focus B. Existing text, highlights and deck assets stay intact.
- Hash/version/options cache keys prevent A's text, figures or positions appearing
  under B. Unknown legacy caches are retained and never stamped as verified B data.
- `.pdf` projection interruption, quota failure, locked handles and retry preserve
  old bytes/binding; repeated activation produces no duplicate jobs or needless writes.
- Paper/workspace/session switches and closing during verification prevent stale
  callbacks. List repaint/filtering does not hash files or run PDF extraction.
- Restart verifies availability again; missing/replaced/symlinked/corrupt projections
  fail closed. External-open/exported-copy changes cannot corrupt authoritative blobs.

Run the full repository check before claiming activation complete. Record live
Windows/macOS Qt/external-viewer checks separately; fixture success does not prove
every installed PDF backend. Only after these gates should the DTO/feature advertise
reader activation for managed documents. PWA annotation operations, analysis/deck
replication and broader v0.5 acceptance remain explicit subsequent milestones.
