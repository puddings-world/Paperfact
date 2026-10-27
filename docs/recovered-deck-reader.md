# Restored slides in the normal reader

Detached recovery now connects to `presentations.load_deck`, the desktop canvas,
HTML export and native PDF export. A recovered deck retains its original narrative,
speaker notes, citations, source hashes and figure identities. Unknown
`deck.source_hash` remains unknown; PNG/evidence content hashes never become a
claim about the input PDF.

The reader selects one exact archived applied artifact, or one explicitly captured
legacy current slot. It checks the local saved deck against that retained owner,
verifies the original bounded JSON/PNG closure, and binds asset lookups to the
selected recovery database and backup identity. A workspace/file replacement
invalidates the captured reader. Corrupt/missing PNGs fail on reopen and on export;
native PDF export preflights them before creating a successful destination file.
The asynchronous PDF job retains those verified pixels in memory, so a file change
between preflight and the queued rendering callback cannot silently blank a page.

`slide_revise.evidence` reads this captured evidence. It never silently gathers
today's paper when the historical evidence is unavailable. The normal reader uses
the archived artifact/receipt ownership and exact immutable bytes, including the
unknown-evidence lookup case; it does not infer provenance from a lookup filename.

`recovery_decks.document_status(deck)` separates historical PDF object availability
from whether the current reader PDF alias matches that version. A changed current
PDF does not relabel slide sources or invalidate independently retained figures.
The original per-source document hashes remain available to existing anchor guards.

## Explicit legacy current slots

`research_legacy_deck_recovery(paper_id, slot, request_id, parent_token, deck)`
is an archive-only record. The captured parent token must match the archived active paper lifecycle;
a deleted/recreated local ID cannot inherit the previous paper's deck. `deck` is
a bounded SHA256/size descriptor for the exact saved slot bytes.
Collection accepts it only from a trusted owned presentation folder and only when
its contents match a verified retained original/result. A separate saved-slot
record chooses the current deck: receipt status or creation order never chooses it.

Restoration validates that the receipt has the same unbound paper/slot and supplies
the exact asset/source closure. It projects the selected saved deck, while completed
but unaccepted results remain in retained recovery records. Duplicate or ambiguous
current slots reject the whole backup. These records never create live journal,
provider, transfer, job, or publication bindings.

## Editing boundary and next layer

This slice enables the normal reading/export journey. The desktop identifies a
recovered deck explicitly. Original recovered slots are read/export-only;
editing controls and canvas mutations are disabled while navigation and export
remain available. The save boundary also rejects programmatic writes, including
a stale editor copy after the user switches workspaces. Single-slide AI revision is blocked before a job/model call begins.

The immediate next layer is an explicit **create editable local copy** action that
retains the archived original, creates a fresh local deck identity and observed
save context, and includes the copy in subsequent backup. It must not pretend that
adoption verifies an unknown original PDF. AI revision additionally requires a
fresh captured and verified source context. Read-only recovery is not the final
editing experience promised for v0.5.

Fixture tests use actual backup/restore, normal deck loading, desktop canvas,
native PDF and HTML exports; no user database, real provider or network is used.
