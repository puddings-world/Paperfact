---
name: agentic-local-integration
description: Expose a desktop app's bounded local operations through CLI and MCP with fixed workspace binding, retry-safe commits and non-disruptive UI refresh. Use for local agent/project integrations, not remote authentication or model routing.
---

# Local agent integration

Keep the product operation independent of transport. Desktop, JSON CLI and MCP
adapters call the same validation and persistence boundary; do not make local
buttons serialize through a server just to share behavior.

- Bind the workspace before importing modules that cache configuration paths.
  A process serves one workspace; changing a CLI argument after those modules
  load must not silently write to the previous workspace. Use an explicit child
  process when a caller needs a different workspace.
- A structured submission from an external agent should not invoke another model
  merely to store it. Separate validation/storage from explicit analysis jobs.
- For retryable creates, persist request identity, payload fingerprint and result
  in the same transaction as the research data. Return the original result for
  identical retries; reject an operation ID reused for a different payload.
  An ordinary SQL transaction alone does not prevent duplicate retries.
- When extending local operations into replication, distinguish remote acceptance
  from local application. An acknowledged write not yet received in a contiguous
  event stream remains a causal predecessor; older pages must not replace its newer
  local content. Commit received research, history and cursor together. This is a
  replication boundary, not an extra protocol required for ordinary local CLI calls.
- A compound operation needs one transaction owner. Pass its existing connection
  through typed writes, outbox capture and action receipts; an independently committed
  sub-operation cannot provide all-or-nothing retry behavior. Keep remote work outside
  the transaction and test failure after an earlier successful child write.
- When replicating related entities, apply their dependency graph before latest-revision
  order: a parent renamed after its child was created must still materialize first.
  Parent deletion/restoration needs an explicit lifecycle boundary so retained children
  cannot silently attach themselves to a new incarnation. This applies to replication,
  not every ordinary local integration.
- For a command that reorders a complete collection, validate the observed members
  separately from the order record's revision. A canonical digest of exact active
  identities/incarnations can avoid false conflicts from unrelated metadata edits.
  It does not replace authorization, scope lifecycle checks, or competing-order
  revision checks; define what happens when membership changes after acceptance.
- When research metadata references transferred files, keep desired metadata and
  verified applied bytes separate. Receiving a manifest must not block unrelated
  research or its cursor. Bind completed bytes only after rechecking the exact
  target version, parent incarnation and active session; stale work may populate a
  private cache but cannot activate the wrong document.
- Validate the requested source before a cache fast path, not only before remote
  work. A cache entry from another source cannot satisfy a version-pinned request;
  explicitly known deletion is not missing work to regenerate. Keep semantic
  verification separate from merely locating a quote.
- Keep activation of a new document separate from retaining an already-open
  verified version. A background revision should announce a choice without moving
  focus or discarding drafts. Key derived assets and their references by source
  version; a positional figure/page number is not stable cross-version identity.
- Before sending private bytes with an opaque credential, authenticate its intended
  workspace/device binding. A valid token and a local cancellation generation do not
  prove they refer to the same workspace. Recheck binding after credential changes;
  preserve per-request authorization and do not persist tokens in transfer state.
- Treat file publication and database ownership as separate durability boundaries.
  Publish verified bytes before granting ownership, fail closed on unowned or
  damaged objects, and make retry repair the interrupted boundary. A local verified
  flag alone is not current availability, and cancellation cannot retract sent bytes.
- Capture SQL changes at the actual commit boundary, including inner commits.
  A first-write snapshot cannot infer what a long-lived editor or AI job originally
  read: carry its observed base through the save, and retain a stale candidate
  without overwriting newer research. Retry of that candidate should not create
  another copy. Test both local research and outbox rollback.
- For delayed generated output, observe target absence as well as existing rows,
  and capture the bounded inputs actually used. Carry the original database binding
  and PDF version through completion; current global settings are not a destination.
  If that database has been replaced or rebound, preserve the result outside its
  replacement rather than inserting even a conflict candidate into the wrong store.
- A delayed offline job can outlive deletion and recreation of the same local ID.
  Capture a persistent local parent epoch before observing work; an ID or creation
  timestamp alone cannot prove continuity. Installation must not commit unrelated
  caller work. Old records without epochs stay readable but need explicit reviewed
  reattachment, rather than a retrospectively assigned identity.
- Treat a cached byte proof as a captured file version, not permanent trust.
  Reuse needs source/owner guards and reliable platform mutation observations;
  creation or rounded timestamps can alias same-size rapid writes. Keep initial
  hashes and independent transfer-byte checks. If change tracking is unavailable,
  require fresh verification or report unavailable. Test restored mtime and
  same-clock-tick writes; do not hide the failure by sleeping in the test.
- Close database/file handles explicitly before workspace replacement. In Python,
  a SQLite connection context manages its transaction, not its lifetime; a read-only
  helper can still retain a Windows file lock. Verify replacement with actual handles,
  not only a mocked path change.
- Keep retry identity separate from entity identity. Use stable identifiers for
  automatic reuse, surface uncertain title/name matches, and preserve curated
  content. Concurrent submissions must recheck matches inside the write transaction.
- For a local stdio adapter, let the host own the helper lifetime. Keep protocol
  stdout clean and avoid loading desktop/model modules. Verify the installed SDK
  rather than copying protocol messages or outdated SDK examples.
- Notify a long-lived UI through a small committed revision signal. Preserve
  active selection, filters, scroll and unsaved editors; defer refresh around
  modal interactions. Never treat a refresh as permission to invoke a model.
  If older commands or ordinary database writers remain supported, their writes
  must invalidate views too; an event emitted by only the newest adapter is not
  workspace-wide tracking. Compare the actual database and membership before
  diagnosing a stale screen: separate workspaces do not synchronize implicitly.
- Treat helper configuration as a capability grant for its selected workspace.
  Expose bounded operations rather than paths, shell or SQL. Explain that data
  returned to an external host may enter that host's model context.

Verify observable behavior: two concurrent retries create one result; a changed
payload conflicts; partial failure rolls back; stale previews and deleted targets
fail safely; separate workspaces remain isolated; an SDK client discovers and
calls tools through an actual child process; the packaged executable passes the
same transport check. Host-specific login/settings require separate live checks.

Use a staged preview when selection or ambiguous identity benefits from review.
It is not a universal approval modal requirement. Fixed workspace/stdin transport
does not solve remote authorization, quotas, or arbitrary external host behavior.

See [local evidence and limits](references/evidence.md).
