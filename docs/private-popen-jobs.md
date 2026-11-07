# Private routes for desktop Popen jobs

Desktop analysis and citation jobs now freeze their resolved default and declared
task routes before CLI argv evaluation, under the original admitted callback
scope. The command remains the existing logical command; its physical launch
adds `_desktop-job-v1` and a nonsecret request ID. Model/account credentials and
private connection options travel only in a bounded anonymous binary stdin
frame, never in argv, environment additions, temporary handoff files or logs.

The child must send the versioned matching hello before any frame is written,
and matching ready after validation. The existing ActivityHub output reader
performs handshake and frame writes off the GUI thread, then parses ordinary
progress. Citation launches previously discarded output; private citation
children now have one background drain using the same handoff implementation.
There is no competing stdout reader. One deadline-only watchdog bounds startup
(including blocked writes). Zero exit before ready is an error. A transport-triggered negative kill code is
also an error; an explicitly canceled activity remains canceled after drain. Failed startup
kills the exact owned process, closes pipes, drops retained frame references and
reaps outside the GUI thread. Even after stdout EOF, a ready job remains
owned until actual native exit; existing user cancellation can stop that wait.
Bounded nonsecret phase timestamps support local
startup diagnosis. The reader joins the watchdog before reporting
drain. This releases Python references, not a cryptographic memory wipe.

Declared routes follow actual callers: analyze uses ANALYSIS_TASKS (including
`ask` for candidate questions and `paper_highlights` for explanation links);
dive-ahead uses dive; cites uses citations; followups uses followups/overview
and additionally citations for --with-cites. List-add uses list_parse only when
the shared lists.needs_ai_parse predicate says its actual append path can parse
a long/multiline citation. DOI assignment happens after that parse and does not
bypass it. Short titles, cleaned noise, bare arXiv IDs, cite-links and unrelated
commands keep their existing ordinary stdin/process behavior.

The existing activity single-flight, source/workspace guards, focus rules and
original-workspace environment remain. Settings changed after dispatch affect
the next request, including in nested child pools. Existing cancellation stops
the owned child; late reader events cannot turn a canceled activity into success.
Ordinary CLI/MCP entry stdin and the independently owned QProcess transport are
unchanged.

## Evidence and limits

Disposable actual subprocesses exercise the real bootstrap, synthetic CLI stub,
private frame validation, nested pools, route/profile changes, partial writes,
malformed/missing controls, startup deadlines, canceled children, retries and
non-AI passthrough. Actual MainWindow tests retain unsent input and suppress
late navigation. No provider login, model execution, real research or third-party
service is used. Existing thin process fixtures adapt only physical transport;
logical argv, saved-data, cancellation and deduplication assertions remain.
Those thin fixtures use explicit synthetic routes, so they never freeze ambient
account configuration or credentials.

Startup deadline is 30 seconds; normal model execution retains existing producer
timeouts. Existing Cites missing-login presentation is not redesigned here.
Cites private jobs retain their existing background completion/reload contract;
they do not gain an ActivityHub notice in this slice. This is active analysis
and citation integration, not proof that every AI launcher is already converted.
The merged application still requires the parent's complete gate and other
launcher integrations; a focused transport pass is not a release certification.

A known admitted baseline gap is recorded separately: presentation export
fixtures still reference a removed thumbnail cache. Those assertions are not
skipped, weakened or repaired here. The reviewed deep-analysis parallelism
fixture now targets actual retained producer APIs, with unchanged Event,
concurrent-chain and candidate-question assertions.
