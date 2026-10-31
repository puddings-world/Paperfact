# Initial enrollment: history and known deletion

Status: isolated implementation with fixture verification. Preparing a reviewed
copy does not adopt it or upload research; runtime adoption has separate gates.

## Authority boundary

```mermaid
flowchart LR
  S[Local research and original observations] --> V[Closed schema and source closure checks]
  V --> L[Fresh live research graph and local parent epochs]
  V --> A[Private nonreplayable history archive]
  L --> P[Authenticated metadata and owned file sync]
  A --> B[Complete recovery backup]
```

`research_history_archive` is a lazy, private protocol table. It is created only
for a nonempty validated batch inside the caller transaction, never by the global
research schema or startup migration. Records contain a deterministic ID, an
explicit registered protocol and canonical JSON retaining the original typed
record. Original request/context/row strings remain unchanged. Archived database
paths, bindings and local epochs are observations; migration never follows them
as file capabilities, restores a pending job or reuses an old runtime identity.

Supported archive adapters:

| Original protocol | Closed validator | Live treatment |
|---|---|---|
| `research_generation_requests` | `research_generation.validate_request_record`, bounded closed input snapshots | Preserve accepted/candidate output and original inputs privately; no active request table is copied. |
| `research_generation_recovery` | Same validator plus trusted sidecar ownership/location checks | Preserve completed cancelled/failed-delivery output, including its original source. |
| `research_chat_requests` / `research_chat_recovery` | Maintained QA validator plus closed nested input, graph observation, target and source checks; strict owned sidecar decoding | Retain prepared questions and completed candidates privately. Never synthesize an assistant turn or reactivate a request. |
| `research_chat_links` | Typed message/exchange/reply/source identity plus exact current SQL turn validation | Install only links whose current turns exist, after adapter initialization and before baseline capture. Orphan links remain archive-only. |
| `research_parent_lifecycle` | `research_lifecycle.validate_record` plus exact six trusted trigger definitions | Archive original epochs; install fresh local epochs for copied live parents. |

Unknown protocols, columns, nested inputs, malformed records, duplicate JSON keys,
nonfinite values and missing byte closure block the copy. Coverage reports expose
archive counts by protocol, distinct historical originals and known deletions.
No archive row is promoted to a current reader, source owner or replay authority.

## Exact originals and live content

Source dependencies include the captured document, prior annotation target and
source-dependent highlight/reading inputs. Lookup uses declared hashes within
explicit trusted PDF roots or the owned source registry; context paths are never
opened. Originals needed only by history stay local and in the complete backup,
without automatically joining shared live source artifacts. Byte hashes dedupe
storage. Current claim A can remain grounded in original A while primary B and
completed candidate B are retained separately.

Every explicitly declared live chat source or anchor also publishes its exact
`original_source` artifact in the isolated candidate/outbox. A peer can therefore
fetch the original A while primary B stays current. Missing or changed A blocks
preparation. Lookup uses trusted roots/owned source declarations, never archived
context paths. Preparing still performs no remote upload. Message/exchange/reply
UUIDs are semantic identities; old workspace, device, database, lifecycle and job
observations remain private history. An explicit reply to an absent UUID remains
unresolved and is counted; a present target must be a user turn in the same paper
and exchange. Legacy unlinked rows remain unpaired, with unknown provenance.

Live research is checked losslessly after projection. Only declared structured
JSON columns normalize representation by canonical re-encoding: whitespace and
object key order may change. Unicode codepoints, array order, numeric types and
all prose/other cells remain exact; booleans never compare equal to integers.
Original historical strings keep their original representation in the archive.

SQLite row/schema digests identify committed research changes. Main database
path/device/inode still detect replacement; WAL/SHM/journal inode and checkpoint
mtime are device-local storage mechanics, not research revisions. Closed idle
`.research-jobs/<64hex>.lock` files contain only one `0` byte and are not copied.
A nonblocking OS lock check rejects active producers; unknown lock entries block.
Preparing a copy still does not replace the source or complete runtime adoption.

## Known-empty annotations

The four registered singleton annotations are claims, highlight analysis, reading
links and research questions. First enrollment represents a known deletion as an
ordinary version-2 empty `research_content` delete for its deterministic
paper/feature/main ID and exact fresh paper-parent incarnation. It creates no
placeholder `put`, claim, quote or analysis body.

The typed initial-deletion operation requires absent current content, a current
paper and an unused child incarnation. Projection recognizes only those four
IDs under that exact parent, then commits the known-empty marker/projection with
the tombstone and outbox. Identical retries do not duplicate data; caller rollback
removes the whole result. Peer reads remain known-empty, including forced cache
reads, and do not invoke AI. A separately confirmed source-aware restoration
creates a new incarnation through the existing typed claim workflow.

Mobile mirrors the four-ID rule, suppresses stale snapshot content/highlights and
retains unrelated deep/close reading. Unknown IDs, wrong parents and nonempty or
unsupported payloads cannot infer a deletion. Actual enrollment-to-HTTP fixtures
exercise a stream with no prior annotation `put`, offline restart and retry.

## Remaining adapters

This slice does not claim arbitrary workspaces are fully migratable. The central
recovery registry also lists these stable formats that need separate closed
initial-enrollment adapters:

- Chat review receipts: retain reviewed question/answer/source observations
  without reviving old request authority.
- Compound requests/recovery: preserve each typed mutation and all original sources.
- Capture candidates: strengthen the current shallow observation/mutation wrapper
  validator before treating nested SQL-row snapshots as an archive contract.
- Review drafts/receipts: retain private edits and preview bases without reviving
  old database/parent authority.
- File candidates/drafts and slide/legacy deck recovery: preserve full validated
  JSON/image/evidence/source closure through the shared file codec.
- Integration/action receipts: identify closed result variants and preserve retry
  provenance without making old commands replayable.
- Already-enrolled or detached recovery workspaces: explicit rejoin/adoption and
  identity policies remain separate from this first-enrollment copy.

Unknown/unmigrated formats remain visible blockers. Passing the focused fixtures
is partial evidence; the combined candidate still requires the project's full gate.
