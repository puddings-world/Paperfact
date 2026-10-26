# Observed research generation

The actual `closeread.write` and `survey.write` callers use the shared observation
boundary. `survey.edit` and its desktop dialog use the target-only reader for
manual edits. This does
not enroll workspaces or imply that every producer in ADR 0008 is wired.

## Caller contract

```python
context = begin_generation(
    conn, table="list_surveys", owner_id=list_id, input_reader="survey"
)
# Render only context.inputs; perform the model call outside the connection.
result = publish_generation(context, row=complete_output_row)
```

`GenerationContext` freezes the explicit database path/file identity, optional
workspace/device binding, original target row (including absence), graph revision,
pending predecessor, parent lifecycle and bounded actual SQL input snapshot.
`context.inputs` and `context.target` return defensive copies. `context.started_at`
is captured once, allowing deterministic normalization of an invalid legacy
timestamp while retaining its original value in the target snapshot. Valid original
generation timestamps can remain unchanged during manual edits.

The survey snapshot exposes exactly `list` and `papers`; paper rows keep the
existing `dive`, `context` and `later` aliases and year/position order. A private
membership snapshot detects changes to positions even if rendered cards would
look unchanged. `input_reader="target"` checks only the loaded target and owner,
not generation dependencies. It is appropriate for a manual editor, not an AI job.

`publish_generation` accepts only the registry's exact output columns. It opens
the captured database, checks the actual current read set and output bases in a
short write transaction, and commits output, captured sync operation and local
receipt together. It never substitutes a current global workspace or refreshes a
stale expected base. `Publication.status` is `accepted` or `candidate`; candidates
include a durable `candidate_id` and reason. Failed/short model responses do not
create successful generation receipts.

Same request/context/output returns the same outcome. Reusing a request ID for
different content fails. Keep the original output timestamp for retries.
`retry_publication(database_path, request_id)` reads a durable outcome without
another model call. It does not automatically rebase a rejected candidate; explicit
review/regeneration remains required. `research_job_lock.claim` prevents concurrent
close-reading or survey launches for the same database and owner across
threads/processes; a duplicate returns busy instead of waiting to run again.

## Exact input PDF and prompt

`brief.pack_text` retains its two-item `(text, pdf_path)` interface through
`PreparedPack`, adding the SQL snapshot and verified document. Text is extracted
from that exact path, including legacy PDFs; an old alias text cache is not used
as provenance. Figure extraction receives the same captured document. Legacy
figures are refreshed rather than accepting an unversioned figure cache.

`bind_inputs` carries the captured document hash/target into the local context.
Publication checks bytes off the database write lock, then checks current target
metadata again under the write transaction. A missing, changed or detached PDF
retains the generated output instead of assigning it the newest hash. Managed
documents never fall through to legacy aliases or remote paper URLs. Bound SQL
capture receives the explicit source hash through its observation context; it does
not infer the hash from whichever PDF is current at completion.

Ordinary unbound callers retain the historical two-item pack injection seam for
compatibility. Such a custom pack has no verified PDF provenance; an enrolled
close-reading caller rejects it. The default pack implementation verifies PDFs in
both modes. Unbound workspaces compare local rows and input snapshots; identical
delete/recreate events without a persistent graph cannot prove lifecycle identity.

## Durable candidates and recovery

`research_generation_requests` has these columns:

| Column | Meaning |
|---|---|
| `request_id` | Primary key, explicit or generated once per job |
| `context_json` | Immutable original input/target observations and local provenance |
| `row_json` | Exact intended output, including its original completion timestamp |
| `status` | `accepted` or `candidate` |
| `candidate_id` | Stable SHA-256 for retained candidates, otherwise null |
| `reason` | Fixed publication outcome description |

This private table is created only when publishing valid output; it is not a sync
content table. A stale candidate leaves the current research/outbox unchanged.
Inputs are capped at 2,000 survey records and a 3 MiB encoded context; complete
retained records have an 8 MiB limit. Wire content validation remains stricter.

If the original database is missing, replaced or rebound, even a candidate must
not be inserted into the replacement workspace. It is retained atomically under
the original database's parent directory:

```
.paperfact-generation/<original-context-namespace>/<request-hash>.json
```

Both names are hashes, not caller-provided paths. Files are exclusively installed
after flushing their content; links/reparse points are rejected. No original
research file is overwritten. `retry_publication(context)` also reads this owned
recovery location. `list_recovery_requests(database_path)` returns validated
sidecars matching the exact original path and current workspace/device binding,
including a changed inode within that same binding. Backup must treat all embedded
paths as provenance, never active restore destinations. Invalid/partial files or
exceeded scan limits produce an explicit error rather than a false complete backup.

`validate_request_record` is the recovery validation seam. No credential, provider
configuration or model transcript is added to these records. Research inputs and
generated text are private research data, not anonymous telemetry.

`input_versions(context)` exports the bounded portable artifact provenance shape:
schema version, entity/document references, an input digest and `complete`.
Currently SQL prompts can consume untracked legacy/ranking data, so completeness
is false. Actual document IDs/hashes are retained; local paths and device/database
bindings are excluded. Completeness describes reference coverage only and never
authorizes publication; the local input and lifecycle checks remain authoritative.

## Fixture verification

Tests exercise actual close-reading completion with simulated model responses,
first generation and replacement in bound/unbound stores, concurrent manual edits,
changed SQL/PDF inputs, missing files, managed desired-version replacement, global
workspace switching, real database replacement/rebinding, durable retry and request
collision, duplicate launches, survey snapshots, recovery validation and original
PDF byte extraction. Native database replacement also checks that reader metadata
connections are closed on Windows. No paid model calls or real research data are
used. Whole-project validation is required at the integration checkpoint.
