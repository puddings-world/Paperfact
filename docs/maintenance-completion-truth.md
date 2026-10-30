# Maintenance completion truth in 0.5

The 0.5 port keeps observed publication, durable candidates, source identity and
portable capture. It does not reinstate the maintenance branch's global SQL writers.

- Claude, Codex and Gemini CLI error answers are failures, including zero-exit
  error prefixes. Visible reasons and local usage receipts contain categories,
  never the provider's raw stdout/stderr, questions or credentials.
- Scheduled citation/dive rewrites use `--scheduled` and respect manual-only or
  zero-budget analysis preferences. Explicit manual commands remain available.
- Close-time UI preference flushes and the background writer serialize complete
  batches. A stale batch cannot land after a newer close flush. `ui.*` stays local.
- Citation completion metadata lives in the existing atomic compound receipt:
  `completion={kind: citation_coverage, sent: [...], answered: [...]}`. Keys are
  exact, sorted, unique, bounded, and tied to the captured owner/source and actual
  saved research. An answer must explain purpose, gist and verdict/reason; a title
  or invented reference key does not count. At least 80% of the requested keys
  must be explained for this phase to be called complete. This threshold measures
  requested-reference coverage, not confidence in scientific correctness.
- Partial replies retain prior good rows and record partial coverage. Only a
  sufficiently complete reply may prune old unedited references. Manual edits
  and observed target/lifecycle guards remain authoritative. Retry does not add
  an automatic second model call or reuse a request for different output.
- Legacy or imported rows without this local receipt are unknown, never inferred
  complete from a row count or text-file heuristic. The receipt is local derived
  evidence, not a new shared research domain; portable completion evidence is a
  future protocol concern. Existing row sharing/recovery remains unchanged.
- `cites.coverage(conn, paper_id)` is metadata-only and returns unverified rather
  than hashing on a GUI caller. Workers explicitly request `verify_source=True`;
  `analyze.status(..., verify_sources=True)` uses the same bounded exact-byte
  verification as existing generation publication. Path/mtime/size caches cannot
  certify PDF bytes, including on Windows where ctime can be creation time.
- The analysis bar requests this status on a coalescing worker, preserving its
  current visible state while checking. Results require the same database,
  binding, paper lifetime, source and view epoch; close/context changes discard
  stale work. Errors are sanitized and retryable. The helper admits one running
  read and one replaceable pending scope, without AI or background network.
- Later-work retrieval timestamps alone do not mark the research context complete.
  A nonempty saved explanation is required. Combined analysis writes that story
  after both parallel chains finish and checks the original PDF bytes again;
  a replaced original is not silently adopted. An empty/no-story result remains
  incomplete with its reason instead of inventing a success marker.
- RichView initializes its native WebEngine surface before displaying the main
  window, so the first paper does not recreate a visible Windows window.

This slice does not add the maintenance claim-card SQL writer, change the release
version, loosen requested slide counts, migrate research databases, or enable
synchronization/upload. Remaining maintenance items are in the separate read-only
reconciliation audit. Focused tests use isolated SQLite/PDF fixtures and simulated
providers. A root full check and platform release acceptance remain required.
