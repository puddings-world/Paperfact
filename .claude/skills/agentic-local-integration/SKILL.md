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
