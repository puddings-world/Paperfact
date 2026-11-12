# Adoption record-read schema scope

`recovery_adoption._records` now wraps its unchanged synchronous row loop,
`finish()` and return in a fresh `schema_definition_scope`. The scope reuses only
the existing immutable schema-section/column definitions during that operation.
It yields no value or authority and caches no rows, SQLite handles/statements,
paths, source hashes, lifecycle observations or native identity proofs.

Each independent, reentrant or concurrent record-read operation gets a fresh
scope. Success and exceptions clear metadata and restore the previous context.
Copied contexts cannot keep completed metadata alive. Standalone `decode`
outside an explicit operation remains fresh. Depth-zero group validation keeps
its existing separate fresh scope; deeper groups share only that group's metadata.

Every original scalar, JSON/hash, source/blob, closure, depth, lifecycle and
publication check still runs. Neither the protected recovery schema factory nor
the manifest parser changes. Other direct record-read pipelines remain outside
this optimization. Deterministic tests count calls through the real complete
schema factory and inspect exact nested archive data; elapsed time is not a pass
threshold or evidence of a whole-pipeline speedup.
