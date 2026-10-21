---
name: agentic-private-events
description: Design lightweight opt-in workflow events for agentic apps without collecting raw prompts, answers or document content. Use for operation-node traces, retention and withdrawal behavior. Do not equate local event storage with consent to cloud upload or with legal anonymization.
---

# Observe workflow structure with minimal content

1. Start with an improvement question, such as where an import fails or whether
   users retry an AI action. Define a small allowlist of event/feature names.
   If a field cannot answer a concrete question, omit it.
2. Record bounded categorical data: schema version, event ID, ephemeral session,
   flow/node/parent IDs, feature, backend/model family, outcome, duration and
   coarse input-size bucket. Map unknown names to a safe category. Reject
   arbitrary metadata, prompts, answers, document titles, paths and raw errors.
3. Default collection off. Separate local-recording consent from export/upload.
   Version the consent purpose. Check consent and insert events in one transaction
   so withdrawal cannot race with a write and recreate deleted local events.
   For first-use notices, reminder preferences and policy renewal, use
   [the consent lifecycle](references/consent-lifecycle.md). A dismissed reminder
   or imported research bundle must never grant consent.
4. Propagate trace context explicitly across background threads. For subprocesses,
   define a separate safe propagation contract; do not assume thread-local context
   crosses process boundaries. Missing terminal events mean incomplete/unknown,
   not success.
5. Bound retention and size. Make recorder failure nonfatal to the research
   operation. Record action completion only after the operation's actual result,
   not just after a click handler starts.
6. Separate the local diagnostic ledger from the shared report. If improvement
   questions only need totals, aggregate locally and exclude persistent IDs and
   individual timelines from export. Allowlist output categories too; do not copy
   arbitrary fields from local records. Explain which analyses totals cannot support
   and how overlapping snapshots must be handled. Aggregation alone is not proof
   of anonymity, particularly when a person directly shares their own report.
   For reviewed exports, preview the exact payload; cancellation writes nothing.
   Recheck consent before saving. Do not attach credentials or raw input logs.
   Withdrawal semantics must state whether they cover local, queued, cloud and
   derived copies. Random IDs alone are pseudonymization, not proven anonymity.
7. Test default-off, repeated consent, invalid/free-text fields, parent-child
   context, failed operations, retention, withdrawal, canceled/failed/retried
   export, and recorder failure preserving the app action.

Cloud collection is a separate integration. Define validation, idempotency,
installation abuse controls, deletion propagation and retention before enabling
an uploader. A key distributed in a desktop app is not a confidential credential.
Keep raw telemetry out of skill instructions; reviewed developer evidence can
inform a candidate pattern, which still needs implementation tests.

See [Paperfact evidence and limits](references/evidence.md).
