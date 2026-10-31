# Legacy model-envelope reconciliation

Status: isolated development adaptation; full integrated gate remains required.

Only model replies in reading links, research questions, presentation generation
and its one repair, citation analysis, and followup judgment/overview use the
shared llm.reply_json extractor. Prefaces, fences and bracketed citations are
formatting envelopes. They do not supply research authority.

All existing source/quote/section/figure/row-ID validators remain in place. The
same observed generation, grouped annotation, compound and editable-deck writers
perform publication. Existing account/model routing, timeouts, request budgets,
source hashes, provenance, retry receipts and accepted-call counts stay unchanged.
No additional model/search call or fallback is introduced by parsing.

Citation/judgment replies must be arrays of objects. A numeric citation preface
such as [12] is skipped. Heterogeneous scalar/object arrays now fail closed rather
than contributing partial rows; invalid fields inside object arrays still pass
through the existing per-row validation. Existing tests guarding valid partial
object results remain unchanged.

On malformed output or invalid original-quote/evidence references, saved research,
manual edits and editable decks remain intact. Source-bound annotation jobs keep
their observed PDF hash and retry without duplicating publication. A presentation
repair still receives only failed slides and can run at most once.

This is not a decoder migration for saved files, caches, API/network payloads,
claim/appraisal records, source snapshots, history archives, recovery or sync wire
formats. Their strict decoders and duplicate-key checks are untouched. The helper
chooses the first syntactically matching typed JSON value; feature validation may
reject that value. It does not search for a later semantically preferred answer or
verify research correctness.

Evidence is fixture-only: fake prefaced/fenced/bracketed replies, actual isolated
SQLite observed publication, original PDFs and editable-deck files. No live
provider/account/search, owner research or release action was performed.
