# Observed compound research publication

Implemented producer scope: `cites.analyse`, `followups.fetch`, `followups.judge`,
`followups.analyse`, `resources.find`/`refresh`, and the citation/followup item
editors. No automatic workspace enrollment, network calls, or model calls occur
inside the publication module.

## Boundary

`research_compound.begin(conn, phase=..., owner_id=..., key=None)` captures a
bounded owner-feature inventory, the metadata that phase actually consumes,
existing graph observations (including tombstones), and the local parent lifecycle
token. New discovered keys use the captured absent base and captured parent; they
do not acquire a fresh base when the lookup or model finishes. Manual editors
observe only their selected row, so an unrelated reference edit does not conflict.

The shared `research_lifecycle` helper is installed in an explicit preparatory
transaction before observations. It does not enroll synchronization. It detects
identical delete/recreate in unbound databases, where matching paper metadata is
insufficient evidence of identity.

`read_text(context, pdf_root=..., text_root=...)` resolves the exact PDF using the
captured database. Managed missing/detached documents cannot fall back to a legacy
alias or URL. Readable legacy PDFs also receive a verified source hash. A legacy
text-only cache has a separately checked content digest and never claims a PDF
hash. `with_prompt(context, prompt)` retains the exact private model input,
including bounded external lookup results represented in that prompt.

All producer calls capture their database and AI connection snapshot before
preparation. Local OS job locks exclude duplicate work. The followup pipeline
holds one lock through fetching, judging and overview generation. Separate
features continue to have separate canonical row conflict domains.

## Typed publication

`row(context, key, /, **values)` builds a full row from its captured predecessor.
It preserves unspecified fields and normalizes only invalid legacy timestamps,
using the observation's fixed start time. The original timestamp remains in the
captured inventory. `publish(context, puts=[...], deletes=[...], completion=None,
manual=False)` validates exact allowlisted columns against the portable content
contract. It never accepts SQL or a caller-selected table name.

| Phase | Output table / key | Allowed completion |
| --- | --- | --- |
| `citations` | `cites` / `ref_key` | None |
| `fetch` | `followups` / `work_id` | Captured completion timestamp |
| `judge` | `followups` / `work_id` | None |
| `resources` | `resources` / `url` | `text` or `notext` |
| `edit_reference` | One `cites` row | None |
| `edit_followup` | One `followups` row | None |

Publication rechecks the original database identity/binding, parent lifecycle,
local input metadata, feature inventory, touched graph bases and input document.
The mutations, captured outbox operations, completion flag and durable receipt
commit together. A failure after pruning or after an earlier insert rolls all of
them back. This is local transaction atomicity; portable rows retain independent
conflict histories, and the transport does not claim a server-wide group commit.

Re-analysis preserves manually edited citations/followups. Resource discovery
preserves rows explicitly marked with non-generated sources, such as `manual`.
Resources no longer delete/reinsert everything or commit their caller's work.
On-disk callers with a pending transaction must finish it before external work;
the actual analysis pipeline commits venue preparation in a separate block.
Unbound in-memory legacy callers use a savepoint and retain ownership of commit.

## Durable outcomes and review

`research_compound_requests` has exactly these columns:

```text
request_id TEXT PRIMARY KEY
context_json TEXT NOT NULL
mutations_json TEXT NOT NULL
status TEXT NOT NULL                 # accepted or candidate
candidate_id TEXT                    # SHA256 for retained candidate
reason TEXT NOT NULL
```

Mutations are the closed object `{puts, deletes, completion}`. Observations and
prompts are private local research provenance, not provider credentials, telemetry,
portable executable instructions or restoration paths. A stale phase retains the
whole intended group without pruning current rows. Manual saves derive retry
identity from the original observation and exact draft: repeat saves reuse the
outcome; a changed stale draft gets its own candidate.

If SQL fails or the original database is replaced/rebound, the completed result
is retained under the owned `.paperfact-compound/<namespace>/<request-hash>.json`
directory beside the original database. The namespace binds the original path,
inode and workspace/device binding. Replacement databases receive no old-job
tables or candidates. Sidecar writes use fsync, atomic publication and link guards.

`validate_request_record(record)` validates SQL/sidecar records without following
their provenance paths. `list_recovery_requests(database_path)` enumerates bounded,
validated sidecars belonging to that path/binding. `retry_publication(context)`
returns an existing durable outcome without another lookup/model call or automatic
rebase. Review, explicit reattachment and backup adapters consume these public
validators; they must not replay arbitrary SQL.

Bounds: 2,000 output/inventory records, 2,000 captured paper-child graph references,
3 MiB retained context, 256 KiB per model prompt, at most 64 prompts, 8 MiB per
receipt, and 64 MiB / 10,000 entries per sidecar archive enumeration. Exceeding a
bound fails explicitly rather than silently truncating research.

## Actual UI and pipeline behavior

Citation/followup dialogs load and save the same original owner and row. Failed
or stale saves keep the dialog and current draft open. Save succeeds before the
dialog closes. Native child-process jobs receive an explicit `PAPERFACT_DATA`.
The analysis pipeline uses explicit connections for venue/resource preparation,
for supported producers and for status writes. A workspace switch stops remaining
legacy phases that lack an explicit workspace interface; completed phases remain
in the original store and final status reports partial work.

Fixture tests cover real producers and native dialogs, concurrent feature edits,
first results, unchanged/changed retries, duplicate activation, cancellation,
provider/workspace switching, PDF/text replacement, managed-document unavailability,
parent deletion/recreation, post-prune storage failure, outbox rollback, explicit
manual content and unchanged legacy behavior. They use simulated lookups/providers
and isolated databases only. Full-project checks remain the integration checkpoint.


## Detached backup integration

The recovery registry validates both `research_compound_requests` and owned
`research_compound_recovery` sidecars. A complete archive retains accepted and
candidate groups, while detached restore copies only canonical research into
live tables and archives job records as inactive provenance. Source PDF hashes
must have retained manifests and bytes; a hash alone is not a complete backup.
The combined compound/chat/review/recovery adoption set passed 46 cases, including
new actual storage-failure sidecars and missing-source rejection. No old AI job
is replayed by inspection or restoration. Typed compound candidate application
in the review UI remains required work.
