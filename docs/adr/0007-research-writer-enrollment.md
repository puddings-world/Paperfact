# ADR 0007: Enroll existing research writers at the transaction boundary

Status: transaction boundary implemented in isolated fixtures; full writer enrollment remains incomplete. 2026-10-26.
This follows ADRs 0003-0006. It does not enable sync, enroll real data, or authorize
hosting. Existing store/list/intake actions and the actual desktop note editor now
exercise capture; there is no user-facing enrollment switch yet.

## Decision and source evidence

Use **transactional change capture in the existing research store**, with typed
serializers and feature-scoped research documents. Retain the existing graph
operations for lists, papers, memberships, reading state, order and primary PDFs.
Keep `ResearchOperations` as the explicit action API, sharing the same transaction
and serializers; it is not a parallel database or a mandatory transport hop.

- `store.connect()` owns ordinary SQLite connections, but `lists.py`, AI writers,
  `pipeline.py`, `bundle.py`, `pocket.py` and others also call `conn.commit()` inside
  that context. Capturing only when the context exits is too late.
- `desktop/main.py` directly saves notes, chat, dives, pins and reading state.
  `local_operations.commit()` already makes research, a request fingerprint and
  its result atomic. Preserve that receipt and the 500-candidate public contract;
  do not redirect it to the experimental 200-paper action limit.
- `Journal.apply_in()` already supports a caller-owned transaction and rollback;
  its writer must not commit. The existing graph/client handles retry, causality,
  parent lifecycle, conflict history and acknowledgment-before-receive gaps.
- `presentations.save_deck()` writes assets/history/current JSON without SQLite.
  `_atomic_json()` is shared with unrelated cache files. Neither is automatically
  covered by a store wrapper. `bundle.import_()` combines dynamic table writes
  with staged file installation; `repdf.py` also rewrites note/chat anchors.

| Alternative | Decision |
|---|---|
| Replace every caller with a new operation facade first | Too easy to leave supported CLI, import or AI writers uncaptured. Use facades for intent and retry, not as the only coverage mechanism. |
| Replicate SQLite rows through triggers | Reject: local integer IDs, paths, derived columns and missing lifecycle/document identity are not a portable protocol. |
| Trigger dirty scopes, serialize at the actual commit boundary | Choose for SQL coverage. Triggers capture affected identity and first observed base, not raw research payloads for upload. |
| Whole workspace/list snapshot per edit | Reject: huge transfers and unrelated edits conflict. |
| Versioned documents per existing research feature | Choose for rich content. Reuse current feature validators; whole-feature conflicts are an explicit first implementation tradeoff, with both versions retained. |

## Actual transaction boundary

Implement an enrolled connection factory behind `store.connect()`; ordinary
unenrolled workspaces keep existing behavior. Every enrolled commit, including
explicit `conn.commit()` and connection-context exit, must perform this sequence:

1. Record first-touch dirty scopes and their observed graph heads/predecessors
   inside the same SQLite transaction. Narrow INSERT/UPDATE/DELETE triggers cover
   allowlisted tables/columns, including cascades, bulk writes and deletion.
   Ignore changes only to ranking/cache/local columns.
2. Build closed portable row/feature snapshots from the transaction's final state. Coalesce
   repeated touches of a scope; retain pre-delete identity/parent information.
   Allocate portable mappings in this transaction. Plan roots before children,
   lifecycle changes before dependent state/order, and deletions with the existing
   structure dependency rules. A rename is not a new incarnation.
3. Validate all envelopes and append them through `Journal.apply_in()` with a
   idempotent projection writer under capture suppression, preserving portable
   identities and projection-incarnation markers for already-written rows. Store request/result
   receipts in the same transaction. On any validation/capture failure, roll back
   the original SQL, mappings, dirty records and outbox together.
4. Clear captured dirty records and commit once. Only then invalidate views and
   schedule transfers. Network/AI work never runs under this write transaction.

Do not assume overriding `commit()` alone is sufficient: deny raw SQL COMMIT/END,
implicit-commit `executescript`, and unmanaged transaction exits on enrolled
mutation connections. Keep initialization/migration on a separate trusted path.
Test these routes explicitly. SAVEPOINT rollback must also roll back dirty scopes.
Remote projection and explicit `Journal.apply_in()` writers use a private,
connection-scoped capture suppression mode so they do not echo operations.
The suppression mode is not an argument exposed by CLI/MCP.

Triggers on enrolled tables must fail closed if their connection lacks the capture
runtime; an old process/direct SQLite writer must not silently commit unsynced
research. This is a compatibility boundary, not support for arbitrary external SQL.
Schema checks and a writer registry prevent a newly added research table from
silently escaping coverage. Dirty triggers alone are not considered enrollment.

### Observed-base policy

- Immediate commands such as toggling a pin or marking selected memberships read
  observe their target inside the write transaction; the first-touch trigger base
  is correct. Recompute such commands against the selected active incarnation.
- A note/deck editor, import preview and AI job capture a base token **when loading
  or starting**, containing workspace, entity/parent incarnations, accepted revision
  and outstanding local predecessor (including acknowledged-but-not-received work).
  Carry it through the save/completion path; do not substitute the latest head.
- If that token has changed locally, retain the submitted content as a durable
  candidate and return a conflict outcome without changing the current projection.
  Resolve explicitly using existing resolution semantics; never automatically
  rebase a stale full snapshot. Preserve candidate bytes before reporting failure.
  The candidate/conflict record and its eventual publication need fixture coverage;
  an exception that drops an AI result is not an acceptable implementation.
- If only an unseen remote edit occurred, normal server base checks retain both
  versions. Sequential offline saves use their actual local predecessor. A legacy
  body-replacement caller without an observed token is rejected and retained once enrolled;
  classify it as such rather than pretending it is an immediate command.

## Complete domain map

Document identity is a stable UUID derived from portable owner identity plus a
closed feature/slot name, not a filename or local row number. Paper features parent
the exact paper incarnation; list surveys parent the exact list incarnation.
Retain existing graph delete/restore/retirement rules. PDF-bound content records
the exact source hash; changing the primary PDF does not retarget old annotations.

| Data and source seam | Capture/projection unit |
|---|---|
| `store.upsert_papers`; pipeline/venues/enrichment/brief metadata updates | Existing typed paper payload. Preserve local IDs via `research_paper_identity`; exclude scores, crawl timestamps and derived metrics. Ordered author names already belong here. |
| `lists.py`, `list_create.py`, `research_plan.commit`, `local_operations.commit`, desktop state/pin handlers | Existing list/membership/state/order ops; add typed pin per scope/paper, preserving list lifecycle. Membership remove is not paper deletion. |
| `notes`, desktop note handlers, `pocket.import`, `repdf` | Extend the existing portable note operation to kind/body/created time plus versioned anchor; preserve note UUID across edits/deletes. No collection-wide replacement for independent notes. |
| `chat`, desktop question saves, `scripts/guide_deck.py` | Stable turn UUID per row with role/body/time/anchor. Preserve turn sequence and pair ordering on import; cross-device conversation ordering still needs its explicit contract. |
| `dives`, `close_readings`, `paper_context`, `list_surveys` | Separate documents per feature, including spec, edited flag, timestamps and typed context reading recommendations. |
| `cites`, `followups`, `resources` and their edit helpers | Separate typed row operations, stable row keys (`ref_key`, `work_id`, URL), all displayed/curated fields and provenance. Preserve edited corrections when AI refreshes. |
| `refs`, `citegraph.py`, selected graph KV | Per-paper reference/graph document with portable referenced paper IDs; create metadata-only referenced papers first. Do not synchronize raw graph-cache paths. |
| `pdf_highlights`, `pdf_ai_highlights` | Separate manual/AI mark rows per paper and PDF hash, stable mark identities, exact anchors, quote/reason/source/analysis hash and hidden state. |
| `paper_highlights`, `reading_links`, `research_questions`, `materials` | Separate validated derived-research documents with source PDF/analysis hashes. Failure diagnostics and execution receipts stay local. |
| `presentations.save_deck`, restore-version, AI single-slide rewrite | One editable deck document per paper/mode; retain deck/slide/source IDs, layout, speaker notes, citations and immutable asset references. Explicit save creates history; recovery drafts stay local. |
| `fetch`, `pdf_downloads`, `repdf`, `figures` | Existing primary PDF op plus immutable versioned text/figure manifests. Figures keep PDF hash and extraction identity; never publish local paths. |
| Optional `queue`, `reading_log`, queue pins, brief completion | Explicit daily-module records per paper and portable log entry; include user state/curation/delivery metadata, omit brief paths and rebuildable ranks. Queue rebuilds must not delete reading history. |
| `authors`, `paper_authors`, ranking columns, provider/device/UI KV | Rebuildable enrichment/local state excluded; paper author names remain shared. `lists.order` uses its typed operation. Review each additional research key individually. |

The implemented `research_content` contract uses closed per-row schemas under a
240 KiB payload bound within the 256 KiB envelope; analysis/context/survey records
are natural singletons. Rich notes keep the existing note identity and add explicit
anchor fields. See [the content contract](../sync-content.md). Oversized content is
rejected without truncation. Large decks/derived JSON and assets require a subsequent
typed owned-blob manifest extension; they are not passed through the PDF transfer
API or falsely treated as covered by these SQL serializers. Reuse deck validators
and existing asset bounds; no opaque ZIP or table dump becomes a sync kind.

## Files, imports and existing workspaces

Refactor feature save entry points, not the generic `_atomic_json()` helper.
Stage immutable verified bytes before the DB transaction; commit their desired
manifest, capture and receipt together; materialize legacy files after commit.
Use durable projection intents so interruption retries installation. Missing bytes
defer that feature's projection without blocking metadata/history/cursor or erasing
the last valid files. A partially available deck must not replace an editable one.
Retain blobs referenced by current, conflict and historical versions; cache pruning
is not a research delete. PDF replacement preserves old anchored content.

Reuse `bundle._validated`, `_owns_file` and file hashes for archive membership,
owner/path and integrity checks; reuse `bundle_files.stage` for bounded staging.
They are not closed sync schemas: `_insert` intersects local table columns and
`_validated` does not validate every row field. Extract shared serializers rather
than importing arbitrary bundle SQL into remote apply. Reuse `deck_from_dict`,
`validate_slide`, highlight/question validators and `sync_projection._anchor` as
building blocks; the latter is deliberately lossy/read-only and not a bootstrap.

`bundle.import_` and pocket import retain their existing merge/replace semantics.
Their accepted changes are new local actions, never imported server receipts or
device credentials. Preserve imported portable identities only for an explicitly
identified same-workspace snapshot; foreign snapshots receive destination mappings.
Reuse verified DOI/arXiv matches, never title guessing. Retry identity must survive
restarting the import and include merge decisions, not only archive bytes.

For existing-workspace enrollment, take a verified local backup, bind identity,
allocate mappings and emit a complete baseline before allowing captured edits.
Use bounded resumable batches with a durable baseline cursor and a mutation gate;
do not hold a transaction while hashing all PDFs or turn on partial capture.
Joining an existing remote workspace is distinct from publishing local content:
preserve remote mappings/cursor and import unrelated local research explicitly.
No on-startup guessing, reset of identities, or copying device credentials.

## Next changes and acceptance

1. **Wire actual SQL writes next.** Implement enrolled store capture and registry;
   route existing list creation/import preview commit, rename/add/remove/order,
   state/pin and desktop note saves through it. Keep legacy signatures where safe.
   Test existing UI handlers, real CLI dispatch and MCP tools against two isolated
   fixtures. Verify actual resulting research and outbox, not helper invocation.
2. **Enroll rich SQL and file producers together.** Add closed feature documents,
   load/start base tokens and durable stale-result handling; wire desktop editors,
   all AI completion functions and save_deck/restore/rewrite. Then wire bundle,
   pocket, PDF replacement, figure extraction, daily commands and pipeline writes.
   Each inventory row gets production-path round-trip/conflict tests before marked
   covered; adapters alone do not count. Do not enable enrollment before coverage
   of all supported actions is complete.
3. **Prove the complete journey.** Populate a fixture via existing app actions,
   sync to an empty peer, edit offline, resolve conflicts, export/import, restart
   both peers and compare semantic research plus verified assets. Exercise parent
   delete/restore, stale AI/deck results, PDF A-to-B replacement, interrupted imports,
   missing bytes, repeated clicks and close/navigation while workers run. Remote
   application must produce zero new outbox entries and zero AI calls.

Required lower-level tests: explicit inner commit captures once; SQL transaction
bypass fails closed; a later serializer/receipt failure rolls back earlier SQL;
savepoint rollback removes dirty scopes; duplicate request returns the original
result; changed-payload retry fails; a non-research UPDATE creates no operation;
same-device stale drafts cannot silently chain onto a newer local edit. Run the
full project check after each implementation batch. This ADR itself changes no
runtime behavior and claims no additional passing implementation tests.

The material product tradeoff is whole-document conflict granularity for long
analyses and future decks. Preserve complete versions now;
fine-grained collaborative merging can follow demonstrated need. It does not block
writer enrollment. Public hosting/authentication and mobile UI remain separate
release work, not prerequisites for testing these actual local write paths.


## Implemented boundary and remaining activation gates

- `sync_capture.install` persists a fixture-only binding/triggers on an initialized
  store transaction; `capture_existing` uses the same serializers for a baseline.
  This helper is not a complete production backup/bootstrap/join workflow.
- `store.connect` captures inner commits as well as exit commits. Raw COMMIT,
  scripts, unmanaged writers and a top-level SAVEPOINT that could commit through
  RELEASE fail closed. Nested savepoints require an explicit outer transaction.
  Journal connections suppress capture, and typed operations on a captured
  connection do not echo. Failed commits poison that connection for further writes.
- `observe_note`/`observe_content` and `expecting` carry observed bases. Stale or
  missing required bases roll back the complete mutation and retain a local durable
  candidate, deduplicated across identical retries. Candidate resolution UI and
  publication are not yet implemented; do not count those candidates as synced.
- `tests/test_sync_capture.py` exercises the existing intake receipt, actual store
  writers, baseline, child deletion, strict boundaries and rich-content round trip.
  `tests/test_note_observation.py` exercises the desktop note editor with a bound
  fixture. Other long-running editors/AI producers still require start-token and
  captured-document provenance wiring. A graph token alone does not prove which
  PDF a model analyzed; no current AI producer is claimed enrolled by this change.
- A disposable 500-candidate `local_operations` intake produced 500 papers and
  1,503 outbox operations. Transaction-local incremental graph projection reduced
  observed elapsed time from 100.759 s to 7.917 s on this development machine.
  The regression asserts bounded graph replay count, not wall-clock timing.
  Cache lifetime is one transaction, invalidated by commit/rollback/explicit typed
  append; it never predicts an accepted server sequence.
- SQL pins, refs, daily module records, research KV outside typed order, and all
  file-only feature saves still need enrollment. Unsupported research SQL fails
  closed; file-only writers have no capture interception yet. Enabling an entire
  real workspace before these routes and bootstrap are covered remains unsafe.
