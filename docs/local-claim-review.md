# Local structured claim review

Unreleased `0.5.0.dev` integration candidate. Desktop uses the typed native review
service; JSON CLI and local stdio MCP share nine bounded operation adapters over
the same service. These tools perform local work, without another model call,
login, remote sync request or changing the PDF selected in the reader.

## Workflow

```mermaid
flowchart LR
    A[Choose retained proposal] --> B[Choose receiver paper]
    B --> C[Open and edit private draft]
    C --> D[Save and read after restart]
    D --> E[Inspect actual original and quote locations]
    E --> F[Explicitly confirm Apply]
    F --> G[Claims, source, outbox and receipts commit together]
```

| Operation | Required inputs / optional controls | Observable result |
| --- | --- | --- |
| `review.claims.list` | Optional opaque `after`, `limit` 1–100 | Retained proposal IDs, next cursor and editable status |
| `review.claims.inspect` | `origin_id` | Scientific proposal, preserved baseline/original and source hash; no draft created |
| `review.claims.targets` | `origin_id`; optional `after`, `limit` | Explicit receiver IDs; live remote conflicts offer only their own paper |
| `review.claims.open` | `origin_id`, `target_id`, `operation_id`; optional edited `draft` | Private `draft_id` and `revision`, leaving formal research unchanged |
| `review.claims.read` | `draft_id` | Exact saved structured draft and its last-reviewed comparison |
| `review.claims.save` | `draft_id`, `revision`, structured `draft`, `operation_id` | Next private revision, preserving baseline/source identity |
| `review.claims.verify` | `draft_id`, `revision`; optional `restore_deleted` | Fresh original/quote-location report; no permission token for later use |
| `review.claims.page` | `draft_id`, `revision`, zero-based `page_index`; optional `offset`, `limit` 1–500, `restore_deleted` | Actual original words and raw anchor indices, source hash, next word offset |
| `review.claims.apply` | `draft_id`, `revision`, `operation_id`, explicit `confirm=true`; optional `restore_deleted` | Fresh verification and one atomic formal change with an accepted retry receipt |

Use exactly the returned IDs, revision and structured proposal. Change editable
claims, reasons, judgments and passages; preserve `baseline_digest` and `source`.
Retarget explicitly through `open` with a new operation ID. This captures a new
comparison without silently moving the earlier private draft.

The CLI is `paperfact integration OPERATION --workspace ABSOLUTE_FOLDER` with a
UTF-8 JSON object on stdin, or `--file INPUT_JSON`. For source/platform command
paths and MCP launch configuration, see [local integration](local-integration.md).
CLI returns one JSON envelope and exit 0/2. MCP uses the official SDK and the
same results/domain errors; strict SDK schemas additionally reject wrong types.

## Authority, retries and recovery

- Discovery and saved comparisons are historical. `inspect`/`read` return
  `fresh_source_checked=false` and `can_apply=false`; fresh `verify`/`page` do
  not grant persistent Apply authority. Apply rechecks in its own owned session.
- Quote location establishes where text appears, not whether it supports a
  research conclusion. Manual revisions retain their manual provenance.
- Private saves and retry receipts commit together. Apply also commits source
  ownership, claims, synchronization outbox, native decision receipt, private
  revision and public receipt in one transaction. Late private edits abort the
  whole formal write and keep the newer text.
- Reuse an operation ID only for an identical request, including the observed
  revision and restoration flag. A changed payload returns `conflict`. Accepted
  retries return the original result even while unrelated source work is busy;
  they never overwrite later accepted research.
- New local source inspections are serialized with the existing OS job lock.
  A bounded wait returns `in_progress`; retain the same operation ID and retry.
  Process exit releases the lock. Source/native ownership checks still run;
  the lock does not authorize a write or replace a source-integrity check.
- Detached recovery supports list/inspect without schema migration. Create an
  editable managed copy before opening a private draft or applying changes.
  Runtime receipts/private drafts are local bookkeeping, not replicated authority.
- Paths, SQL, shell commands, source bytes, credentials and serialized native
  capabilities are not input fields. Research text returned to an external agent
  can enter that host's model context. Nothing here controls host retention.

Live remote claims retain the full reviewed conflict observation and use the
transactional resolution API on Apply. Version1 remote private drafts remain
readable but require reselection. See [compatibility and causality](claim-conflict-continuity.md).

## Validation and limits

The [executed operation map](testing/claim-review-operation-scenarios.md) names the
actual actions and saved results, including real CLI subprocesses and official
MCP restart/reconnect. The registry now contains 26 tools, including these nine.
This does not prove installed binaries, host-specific account settings, real
Mac/phone behavior, production sync or scholarly quality. [Actual sidecar/remote/offline journeys](claim-conflict-continuity.md) now have local
evidence, including versioned conflict intent and independent recovery. Dedicated
native-button journeys, remaining formats, production and physical devices remain open.
