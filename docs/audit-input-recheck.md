# Read-only Audit input recheck

`audit_input_recheck.recheck(capture, *, document, owner, current, cancelled)`
is a worker-only foundation. It returns a **new actual `AuditCapture`**, or a
safe `AuditError`, after one bounded semantic observation. It never changes the
original capture or its strict `current()` result.

The inputs must be the actual process-sealed capture, its original loaded
`ResolvedDocument`, and the actual `HighlightOwner` observed for that paper and
workspace. Both required predicates must return booleans and be cheap,
worker-safe caller-scope/cancellation observations. A copied document, another
resolver, a serialized dictionary, or matching paths/hashes are insufficient.
Missing original native database identity or paper lifecycle remains unknown;
opening the helper cannot create ownership or retro-certify it.

The helper uses the maintained read-only capture factory exactly once. It
requires byte-identical complete captured state (including binding and paper
lifecycle), saved-output corpus, source description, and original PDF bytes.
The database native identity, loaded document/resolver context, source native
version, scope and fresh physical lease must remain valid through the final
observation. The factory retains its existing stable-read checks. Continued
interference produces `recheck_interference`; there is no stat retry, GC,
connection-cache workaround, or loop that samples until it happens to pass.

A persisted non-content reading-state write can invalidate the original
DB/WAL lease while these exact scientific inputs remain equal. A successful
recheck then supplies a fresh **point-in-time read-only proof**; the old capture
stays invalid. Saved note, reference, highlight, parent or binding changes,
native database replacement, changed source bytes/version/object, cancellation,
unknown identity and input-limit failures reject. A retained loaded original A
can remain the input when desired primary B changes: the maintained source
`intact` contract validates A; the helper never substitutes or activates B.

The existing snapshot bounds apply, including bounded saved-item count/text/JSON
and original PDF bytes. At most the already bounded original and fresh PDF
buffers coexist. Predicate checks surround the core capture but do not interrupt
an individual existing filesystem/SQLite call. No SQL, PDF hashing or capture
runs on the Python main thread. The helper performs no schema/lifecycle install,
research/outbox write, model call, provider/account read, download or sync.
Its proof is not publication, restoration, replay, enrollment or writer authority.

## Explicit caller integration

The helper alone cannot resume a model job. The local candidate's bounded
pending-comparison integration is described in [reading continuity](audit-reading-continuity.md).
It keeps the parent capture immutable and carries a separate verified execution
capture. Other callers remain strict unless they explicitly opt in with their
actual reading owner; the helper supplies no general writer or restore authority.
