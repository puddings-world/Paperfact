# Recovery provenance schema metadata

Closed provenance-group validation builds its trusted row-column registry lazily
once per call, including nested declared archives. The registry is an immutable
mapping of section names and column tuples. It holds no SQLite connection,
statement, research row, source hash, path, device or native identity proof.

The operation scope resets on success or exception, clears its metadata even in
copied contexts, and is not shared by independent calls or execution threads.
Standalone `decode` remains fresh. Empty input and an already-exceeded depth limit
do not construct a schema. The maintained manifest parser still builds its own
fresh registry once per manifest; this change does not intercept that factory.
Existing pipelines that call standalone `decode` outside group validation also
keep constructing fresh metadata; this is not a cache around an entire backup.

Every original row, canonical JSON/hash, table inventory/hash, source/blob closure,
depth and size/count check still runs. Recovered records remain archive-only.
Performance regression checks count calls through the real complete in-memory
schema factory, rather than asserting machine-dependent elapsed-time thresholds.
