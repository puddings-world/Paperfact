# Active presentation and material sources: remaining integration

Status: ordinary saved-deck and independent material source adapters locally integrated;
exact historical passage focus, detached originals and other local receipt formats
remain incomplete. Updated 2026-11-02.
Current exact evidence: [source actions](testing/active-source-scenarios.md).
The retained Review path is covered separately in
[recovered-original scenarios](testing/recovered-original-scenarios.md).
This work remains required for the v0.5 source/material continuity scope.

## Current observed boundary

`PresentationPane._open_source` emits an actual saved source dictionary;
`MaterialsPanel` emits source-aware material positions. ReaderPage's
`_jump_to_source` handles the current PDF and keeps its final `anchor_allowed`
check. Ordinary saved-slide A references now use a separate owned worker/read-only
view. The material path now uses its own sealed collection/selection and original
proof, with [selected UI evidence](testing/material-ui-scenarios.md); it never borrows
the deck grant. Claims/audit navigation has its
own boolean passage-focus seam; it must not be mistaken for slide navigation.

`presentations.load_deck` already retains `_file_observation`, including the
actual managed artifact observation. The public active file and its retained
scientific proposal are different records. A deck's `source_hash` is not a PDF
identity. A digest or a copied sender owner is not a read capability.

## Intended reader behavior

- Current verified PDF matches the source: locate the left reader exactly as now;
  keep its final document/anchor checks and visible failure feedback.
- A declared source version differs: open its verified exact original in an
  independent read-only view, with page/passage focus when available. Keep the
  selected PDF and unsaved slide/text drafts. Do not silently activate a PDF.
- No exact owned original or unknown identity: keep content visible and explain
  that the original cannot be verified. No hash-only global-cache lookup,
  download, login, model invocation or paid fallback.
- A source edited but not saved cannot inherit a saved artifact grant. Preserve
  the draft and ask for an explicit save/review where needed; do not manufacture
  an observation from the current global workspace.

## Implementation contract and remaining adapters

The saved-deck and material slices have local evidence linked above. The contract
below is retained for those implementations and the remaining detached/receipt
adapters; it is not a list of wholly unimplemented tasks.

1. Add a pure, transport-independent active-deck original read adapter. Bind the
   actual database native identity, active workspace/device binding, paper local
   lifetime, portable identity, applied artifact operation and exact displayed
   source identity/content. Read the declared original only after checking its
   same-paper source ownership, complete CAS descriptor and source availability.
2. Worker preparation may parse/hash bounded bytes. Its sealed proof retains the
   exact source bytes/version and actual owner/artifact observations. GUI delivery
   and subsequent view checks use bounded readonly metadata/file versions, never
   parsing or hashing an entire PDF on the UI thread. Retired sources remain
   retired even if identical bytes are present.
3. Reuse OriginalVersionDialog through a typed optional proof branch, not a fake
   claim set or retained native proposal. Existing claim/local/retained proofs
   remain distinct. Page-only navigation must not claim a located quotation.
4. Put generation/coalescing/cancel/close ownership in a focused desktop controller.
   ReaderPage and PresentationPane keep thin admission/delivery hooks, preserving
   existing Main edits. Rapid clicks share one preparation/view. Switching paper,
   source, workspace or closing invalidates late delivery and drains owned renderers.
5. Cover ordinary unbound saved slides through actual same-paper local-source
   ownership; cover managed slides through their real applied artifact/source
   operations. Never translate an archive-backed virtual ID into native authority.
   Detached original inspection needs a separate descriptor/archive-lifetime read
   adapter and remains readonly; do not replay old source paths.

Do not route source reads through a new model or through MCP. UI/CLI/MCP may later
call the same bounded research read operation without granting arbitrary files.

## Required acceptance

- Actual public package/enrollment/Apply creates active slides referencing A while
  current B remains selected. Source and material actions read exact A without a
  claim set, inactive-catalog assumption, source-folder fallback or research writes.
- A current-PDF passage still focuses the left reader; invalid/missing/wrong-version
  anchors never focus B or claim success from a page-only fallback.
- Source removal, parent recreation, native database/store replacement, changed
  applied artifact, corrupt/incomplete CAS and same-byte mutation revoke proofs.
- Real Qt duplicate clicks, error/retry, changing selection/workspace before queued
  delivery, accepted close with renderer/Apply held and reopening a closing view
  preserve drafts and produce no late read window or write.
- Unbound, managed and detached paths each have actual native/physical-byte tests;
  supported capability does not fall back to another mode after refusal.
- Existing source/figure navigation assertions stay unchanged. Matching selected
  integration and the default full gate are required before checkpoint/release.
  Installed Windows/Mac, phone and professional source-accuracy evaluation remain
  separately recorded acceptance, not inferred from simulated Qt success.
