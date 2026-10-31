# Bounded saved-deck evidence audit

Status: isolated v0.5 adapter candidate, not complete A1/A3 or a release claim.
The action lives in the existing presentation toolbar as **Saved evidence**. It
checks the actual selected saved typed deck. It makes no model call and adds no
account settings. Unsaved slide/canvas edits must be finished or saved through the
normal editor first; the check never saves, discards or publishes them.

## Retained deck, not a cache filename

The reader binds the actual workspace path/native identity before its first
worker. The native entry also retains the loaded deck observation, paper owner,
pane epoch, exact operation and dirty flags. Its worker checks the current binding
and owner, exact retained operation/header identity, live desired file lifetime,
active paper parent and registered read-only artifact store. Within that lifetime,
an explicitly selected retained older revision remains that revision even if a
newer deck is pending. Retirement or a new file/paper incarnation refuses the old
selection. The visible editor narrative must match the selected saved portable
version. Device-only figure/cache fields are not file ownership grants.

The complete declared JSON/PNG/evidence closure is verified from the registered
owned store. The reader never calls `load_managed_deck`, `materialize`, a global
presentation/cache path, a mutable figure lookup or a file adoption helper. Missing
body/figure assets, malformed saved content and contradictory figure/source version
metadata fail without a partial successful report. It creates no audit SQL tables,
files, projections, ownership receipts or sync records.

## Each source keeps its own original

A deck source row has an optional PDF `document_hash`, not a paper owner field.
The input digest `deck.source_hash` is not a PDF digest. Nor is the focal manifest's
source hash permission to bind every source to the focal paper. A used source is
resolvable only when its recorded PDF hash matches exactly one explicit document
reference in the saved file's `input_versions.documents`.

That reference must match the actual retained document target's workspace, paper
UUID, operation, document incarnation, parent incarnation and hash. The same paper
parent must still exist. Its exact owned `original_source` artifact and retained
operation must match that parent and pass full byte/PDF closure verification.
Known source bytes are read only from that registered ownership, never from a
nearby file or a hash/title lookup across papers. A known hash with missing scope,
missing originals, replaced parents or multiple recorded paper owners remains an
explicit blocker. The same PDF in two distinct paper records is never merged.

An owned original A remains A when the current primary is B. The report separately
states whether the current primary matches; it does not activate A or relabel it
as B. A replaced paper parent is different from a valid retained historical source.
The new deck-specific proof does not impersonate a primary `ResolvedDocument`, an
`EvidenceSnapshot`, a claim owner or an old source receipt.

## Findings and readable text

All saved slide titles, sections, takeaways, bullets, speaker notes, canvas text and
table cell text remain available. Full saved source text and figure captions are
included; captions and slide prose are not automatically quotations. Recorded
coverage notes stay visible. Only a source explicitly declared as `original` with
text contributes a declared quotation. The check locates it in that source's exact
owned PDF or reports missing/ambiguous/out-of-range evidence. Figures are verified
as exact saved PNG assets, without interpreting their scientific content or
certifying their page location.

Lexical number/unit occurrences are checked independently against each cited
original. Finding a number or quote never proves support, a comparison, causality,
uncertainty, correctness or scientific validity. Unknown source scope yields no
located/observed claim. The view has no confidence score, overall quality grade,
paid appraisal selection, original-source jump, search, download or automatic
replay. A separate source-viewer adapter remains a named gap.

The native dialog is bilingual and read-only. Construction, polling, result
selection, rendering and GUI delivery do no SQL or hashing. The worker owns file,
PDF and SQL verification. Final native file/DB/WAL witnesses, the actual loaded
owner/epoch and draft state reject stale delivery without accepting newer
observations blindly. Repeated activation reuses one dialog/job; cancellation and
parent close drain owned work. Parentless workers also survive forced widget
destruction long enough to cancel and release safely. The actual presentation
pane remains busy until every owned audit worker drains, including after dialog
destruction. This same pane seam blocks MainWindow restart/update preparation and
the configured update banner before installer launch, even if the audit dialog is
hidden and no modal widget remains. Reader question/note drafts
and the selected primary PDF stay intact.

## Bounds and remaining scope

The entire selected deck is checked within these limits; nothing is truncated to
make a report pass:

- 1 MiB declared deck body and 16 MiB declared assets; full typed closure required.
- 32 used source IDs and four distinct recorded original scopes.
- 32 MiB aggregate PDF bytes, 96 pages and 50000 extracted words.
- 256 aggregate source/item pairs, 1 MiB aggregate item JSON, 512 declared passages
  and 512 lexical quantity checks; existing 120000-character item and
  4000-character quotation limits still apply.
- A 4 MiB derived report and bounded fixed metadata reads; output exceeding a
  limit fails whole rather than silently reducing coverage.

This first slice supports enrolled typed retained decks with existing registered
local artifacts. Unbound legacy caches, detached/recovered deck selection and
source catalogs that lack a representable owner are not adopted. Unused catalog
entries are validated as saved data but are outside deterministic cited-source
coverage. File closure is not scientific appraisal or a fact sheet. List surveys,
typed lineage/corpus adapters, A3 consistency and richer research agents remain
outside this slice. Neither blocked lineage recovery/export hook is applied.

Focused fixture evidence and exact hashes belong to the frozen handoff. It uses
actual saved typed deck/original operations, malformed and missing closure cases,
same-hash distinct owners, old A/current B, parent replacement, budgets and native
lifecycle/off-thread checks. No user research database, real account/provider,
external service, release or publication is used. Full canonical integration and
its complete check, physical device/OS and accessibility acceptance remain pending.
