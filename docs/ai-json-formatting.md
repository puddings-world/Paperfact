# AI response formatting compatibility

Status: integrated unreleased development candidate; complete gate pending.

The existing master JSON reader is adapted only for topic-query/selection objects
and bibliography arrays. A preface, code fence or bracketed citation such as
`[12]` must not prevent reading the actual typed payload. Extraction makes no AI
or network call and does not alter the selected provider/account/model route.

Extracted values still pass the feature's own validation: topic selections must
refer to actual search results, malformed replies do not create a list, and a
stored bibliography retains its parsed order. This utility is not source or
quotation verification. Source-pinned claim, appraisal and other strict decoders
are deliberately unchanged, as are observed publication and history writers.

Evidence uses fake model/search responses plus real isolated SQLite list writes.
No live account/model, owner research, hosting or release is involved. Other
maintenance parser callers remain separate parity tasks; this is not a claim
that every AI output adapter has been migrated.
