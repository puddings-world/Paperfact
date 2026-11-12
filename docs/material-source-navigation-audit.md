# Historical material source continuity audit

Status: reproduced required gap, not an implementation. 2026-11-01.
Source reference is Root's frozen 919-input checkpoint; the wider copied
src/tests/scripts + project-file inventory has 940 paths, all unchanged.

## One actual user journey

The single new native audit attaches a synthetic managed PDF A through maintained
document actions, publishes its exact `original_source` against the real portable
paper incarnation, opens A, and clicks the actual materials toggle. The real
collector extracts and locates A's numbered heading. No deck/proposal is present.

The actual **Use Latest** action then loads separately attached B. The original
A item stays in the paper-cached material tree. A real viewport mouse click emits
that collected A item. Its current-B anchor check remains false. No B focus or
scroll happens, and no deck-original controller is called. Loaded B object/hash/
bytes, the unsaved reading note, all logical SQL and all non-WAL/SHM fixture file
hashes remain unchanged. The sole desired-outcome failure is **zero independent
original-A views**, despite a still-active same-paper original-A operation whose
complete PDF closure was verified. A's old resolved document is intact but no
longer the current primary; those are distinct states.

Result: **1 genuine failure, 10.48s** (11.469s wrapper), zero skips/drift; Ruff
passes. The final test hash is tied to that receipt. The prior 1-failure/7.29s run
never reached navigation: its newly authored lowercase fixture headings were
rejected by the maintained title-case recognizer. Root approved only title-case
PDF labels and matching label literals; first source/log and exact diff remain.
Neither run is added to Root's passing integration count.

## Exact flow and earliest boundaries

| User step | Current seam and observed meaning |
| --- | --- |
| Open materials while A is current | `PresentationPane._load_materials` (1012) calls real `materials.collect` (272). It currently captures the desired/current document implicitly, rather than an explicit reader-loaded context. |
| Extract A item | `headings_from_pages` (239) and `_locate_materials` (341) produce A's actual heading/page/rectangle and hash. Source identity is not inferred from arbitrary caption geometry. |
| Return/display collection | `Materials` (56) contains paper_id, exhibits, headings, sentences, highlights only. The actual resolved-document/owner context used while collecting is not retained as a typed read capability. `MaterialsPanel.load` (161) copies scientific item dictionaries into tree data. |
| Use Latest B | Real document worker activates B; existing panel stays populated with A. `_materials_for` is keyed only by paper_id (`_toggle_materials`, 979), so ordinary hide/reopen does not itself establish a source-version refresh. |
| Select A item | `MaterialsPanel._locate_selected` (318) emits its plain item dictionary; `main.py:994` routes it to ordinary `_jump_to_source` (1908). It intentionally does not borrow `_jump_to_deck_source` (1898). |
| Try current reader | `anchor_allowed` (document_flow.py:111) rejects A versus B. This correct refusal preserves B; removing it would create wrong-version navigation. There is no independently authorized material-original branch. |
| Recollect from B | The audit separately invokes the actual collector and gets B-only headings, without A. This is current-material enumeration, not a historical catalog. It does not retroactively change the already-displayed A item. |

Fresh enumeration lacking A and a selectable old A item lacking a read route are
different outcomes. This case proves the latter with actual owned A still
available; it does not prove that every unavailable historical cache has an A
PDF or that current collection must enumerate all past versions.

## Ownership observations and mode boundaries

Managed positive ownership is real: original operation/workspace/device,
portable parent incarnation, native research DB, exact A descriptor/verified
bytes and original resolved-document object are recorded. No sender observation,
claim set, deck grant or hash-only global lookup is constructed. The material
dictionary alone is not that authority; neither is `navigation_available=True`.

Unbound behavior was inspected, not native-tested here. `fetch.capture_document`
(70) returns None for ordinary unbound current content; `materials` then reads
the configured legacy alias/cache and derives coordinates/hash. Once that alias
is B, an old A hash/rectangle cannot recreate original-A ownership or bytes.
Historical unbound source opening needs a real same-paper/native/lifetime owned
original (where present); absent or ambiguous proof must be explicitly unavailable.
It must not synthesize a managed identity or a deck/claim preview.

`figures.image_path(..., historical=True)` (426) can resolve a bounded historical
PNG cache path. That is a preview-path selector, not PDF ownership or a grant to
open an arbitrary original. Figure-cache paths/hashes and loose saved analysis
text must not be promoted into source authority. Figure/quote/heading origins
need their own recorded item and source proof; a located heading is not semantic
support or a certified quotation.

## Bounded next adapter, Root-owned

1. Retain a sealed ephemeral collection observation alongside its plain scientific
   items: exact native DB/binding/paper lifetime, actual selected/loaded source,
   source byte/version witnesses and immutable collection/item identity. Do not
   serialize process ownership through `Materials.to_dict`/asdict, MIME or export.
2. Bind a source action to the actual panel collection and exact selected item.
   A bare emitted hash/dictionary cannot gain this grant. Keep the existing
   no-deck-grant regression valid. A refreshed B collection is a new context;
   never relabel old A coordinates or silently adopt a newer source after delay.
3. Worker preparation verifies exact same-paper original ownership and A bytes,
   independently of any active deck. Share bounded low-level source verification
   only where authority matches; never fabricate an active-deck/retained/claim
   record. Missing/retired/foreign/ambiguous originals refuse without fallback.
4. A distinct thin material dispatch/controller and typed original-view branch
   may open verified A while preserving B/drafts. Keep matching-current-PDF focus
   and its final anchor guard. PDF/SQL/hash/cache work stays off Qt; GUI admission
   checks native versions, real window/view/source epochs and selected collection.
   Unrelated note changes may be revalidated without recapturing changed sources.

Required later acceptance: turn this exact journey green while keeping every
B/draft/state/guard assertion, then test unavailable/retired/foreign A, parent or
native replacement, changed item/cache/source bytes, duplicate clicks, delayed
paper/PDF/workspace switches, retry and close/drain. Ordinary current-source and
legacy actions remain intact. No such implementation, wider matrix, full check,
unbound native journey, installed-platform or scientific evaluation was run here.
