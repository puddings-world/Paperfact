---
name: agentic-job-progress
description: Implement observable long-running app actions with truthful progress, duplicate-job prevention and safe completion navigation. Use for AI generation, imports and exports that run beyond a click; not for quota polling or durable server job orchestration.
---

# Background action feedback

Register a job before starting its worker. Put the registration at the shared
execution boundary so a new feature cannot silently bypass feedback. Keep local
controls disabled or in their running/stop state, with a semantic single-flight
key when closing and reopening a view can launch the same work again.

Send structured stage events through a thread-safe channel; update widgets on
the UI thread. Drain child-process output continuously and deliver its final
events before declaring completion. Ordinary console output is not a progress
protocol and may contain content unsuitable for a compact status display.

Use an indeterminate indicator and elapsed time while the provider supplies no
measurable total. Use counts only for an explicit unit (completed papers, rendered
pages, stored analysis sections); scope nested counts to their own document.
Distinguish succeeded, partially completed, failed and cancelled. Exit code zero
alone does not establish that every requested artifact exists.

Capture document/list/view context and a user-interaction generation when a job
starts. Visually highlight its notice immediately. Return to the result only if
the context and interaction generation are unchanged and no newer job superseded
it; otherwise offer an explicit result action. Validate that the destination still
exists. Keep typing focus in editable controls. Dialogs can mirror the shared
notice so modal surfaces do not obscure it.

Keep session history bounded, and keep progress reporting separate from telemetry.
Handle worker shutdown and failed startup explicitly so controls can recover and
late events cannot resurrect completed jobs. Decide close/cancel behavior according
to the operation's persistence guarantees; a progress bar does not make work durable.

Verify visible state and saved results with gated fake providers and isolated
processes: rapid activation, retry after failure, partial completion, split output
frames, navigation while pending, destroyed views, and closing while active.
Do not spend real account tokens for a click-flood test. A shared-runner test does
not prove every feature-specific callback or external provider is correct.

For local evidence and limitations, read [the evidence record](references/evidence.md).
